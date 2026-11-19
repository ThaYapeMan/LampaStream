"""Small HTML reader and conservative search-result identity matching."""
import json
import logging
import re
import time
import unicodedata
from html.parser import HTMLParser

from .http_page import fetch
from .registry import LookupResult


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ''.join(c.text() if isinstance(c, Node) else c for c in self.children)

    def all(self, tag):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    yield child
                yield from child.all(tag)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                       'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


_ARTIST_SEPARATOR = re.compile(
    r'\s*(?:[&,]|\b(?:feat\.|ft\.|featuring\b))\s*|\s+(?:and|x|with)\s+', re.I)
_FEATURE = re.compile(r'\s*(?:[([]\s*)?\b(?:feat\.|ft\.|featuring\b)\s*', re.I)
_BRACKET_SUFFIX = re.compile(r'\s*[([]([^()\[\]]+)[)\]]$')
_DASH_SUFFIX = re.compile(r'\s+[-–—]\s+(?:(?!\s+[-–—]\s+).)+$')
_VERSION = re.compile(
    r'\b(?:mix|remix|edit|version|extended|original|dub|rework|remaster|remastered)\b', re.I)
log = logging.getLogger(__name__)


def normalized(value):
    folded = unicodedata.normalize('NFKD', value.casefold())
    folded = ''.join(c for c in folded if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[^\W_]+', folded))


def version_key(version):
    folded = re.sub(r'(?:^| )(?:mix|version)$', '', normalized(version))
    return '' if folded == 'original' else folded


def title_parts(title):
    version = ''
    suffix = _BRACKET_SUFFIX.search(title) or _DASH_SUFFIX.search(title)
    if suffix:
        text = suffix[1] if suffix.re is _BRACKET_SUFFIX else suffix[0].strip()[1:].strip()
        if _VERSION.search(text) and not _FEATURE.match(text):
            title, version = title[:suffix.start()], text
    base, feature = featured_title(title)
    return base, version, feature


def featured_title(title):
    base, *feature = _FEATURE.split(title, maxsplit=1)
    return base.strip(), feature[0].rstrip(')] ') if feature else ''


def _artist_parts(*credits):
    for credit in credits:
        for part in _ARTIST_SEPARATOR.split(credit):
            if normalized(part):
                yield part.strip()


def artist_names(*credits):
    return {normalized(part) for part in _artist_parts(*credits)}


def search_query(identity):
    artist = next(_artist_parts(identity.artist, identity.album_artist), '')
    title, _, _ = title_parts(identity.title)
    return ' '.join(filter(None, (artist, title)))


def isrc_key(isrc):
    return ''.join(c for c in isrc.upper() if c.isalnum())


def select(candidates, identity, confidence, *, strict_version=False):
    base, version, feature = title_parts(identity.title)
    isrc = isrc_key(identity.isrc)
    if isrc:
        for row in candidates:
            if strict_version and version and version_key(row['version']) != version_key(version):
                continue
            if isrc_key(row.get('isrc') or '') == isrc:
                return accepted([row], 'isrc', 1.)

    names = artist_names(identity.artist, identity.album_artist, feature)
    base_matches = [row for row in candidates if normalized(row['title']) == normalized(base)]
    matches = [row for row in base_matches if names.intersection(
        artist_names(*row['artists'], row.get('feature', '')))]

    def duration_matches(rows):
        return [row for row in rows if identity.duration is not None
                and row.get('duration') is not None
                and abs(row['duration'] - identity.duration) <= 2]

    if strict_version:
        matches = [row for row in matches if version_key(row['version']) == version_key(version)]
        if not matches:
            return no_result('not_found')

    if not matches:
        fallback = duration_matches(base_matches)
        if len(fallback) == 1:
            return accepted(fallback, 'title_duration', .4)
        return no_result('not_found')

    same_version = [row for row in matches if version_key(row['version']) == version_key(version)]
    if same_version:
        if len(same_version) == 1:
            return accepted(same_version, 'exact', confidence)
        by_duration = duration_matches(same_version)
        if len(by_duration) == 1:
            return accepted(by_duration, 'exact', confidence)
        matches = same_version
    else:
        by_duration = duration_matches(matches)
        if len(by_duration) == 1:
            return accepted(by_duration, 'duration', confidence)

    tempos = [row['tempo'] for row in matches]
    low, high = min(tempos), max(tempos)
    if high - low <= .5:
        return accepted(matches, 'base_title', confidence)
    if strict_version and abs(high - 2 * low) <= .5 and all(
            min(abs(tempo - low), abs(tempo - high)) <= .5 for tempo in tempos):
        return no_result('octave_ambiguous')
    return no_result('ambiguous')


def accepted(rows, match, confidence):
    first = rows[0]
    # A consensus cannot inherit metadata from a search-ranked row.
    fields = dict(tempo=min(row['tempo'] for row in rows), match=match)
    for key in ('key', 'genre', 'duration'):
        value = first.get(key)
        if value is not None and all(row.get(key) == value for row in rows):
            fields[key] = value
    if match == 'title_duration':
        fields['artist'] = ', '.join(first['artists'])
    raw = first['raw'] if len(rows) == 1 else {'tracks': [row['raw'] for row in rows]}
    return LookupResult(fields, raw, confidence)


def lookup(provider, identity, url, client, candidates_from, confidence, *, post=False):
    start = time.monotonic()
    query = search_query(identity)
    request = {'method': 'POST', 'data': {'query': query}} if post else {'params': {'q': query}}
    page = fetch(url, client=client, **request)
    candidates = candidates_from(page.body) if page.status == 'ready' else None
    if page.status != 'ready':
        status = {401: 'authentication_failed', 429: 'rate_limited'}.get(page.http_status)
        status = status or {'too_large': 'unreadable', 'not_found': 'http_error',
                            'network_error': 'network_error'}.get(page.status, page.status)
        result = no_result(status)
    elif candidates is None:
        result = no_result('unreadable')
    else:
        result = select(candidates, identity, confidence)
    elapsed = round((time.monotonic() - start) * 1000)
    prefix = (provider, json.dumps(query, ensure_ascii=False), page.http_status or '-',
              page.byte_count, len(candidates or ()))
    message = 'provider=%s query=%s http=%s bytes=%d candidates=%d'
    if result.status == 'ready':
        track = result.raw_payload
        track = track['tracks'][0] if 'tracks' in track else track
        title = track.get('track_name', track.get('title', ''))
        version = track.get('mix_name') or title_parts(title)[1]
        if provider == 'songbpm' and version:
            title = title_parts(title)[0]
        label = f'{title} / {version}' if version else title
        log.info(message + ' accepted=%s match=%s tempo=%g elapsed_ms=%d', *prefix,
                 json.dumps(label, ensure_ascii=False), result.fields['match'],
                 result.fields['tempo'], elapsed)
    else:
        log.info(message + ' accepted=- reason=%s elapsed_ms=%d', *prefix, result.status, elapsed)
    return LookupResult(result.fields, dict(url=page.url, track=result.raw_payload),
                        result.confidence, result.status, page.http_status)


def no_result(status, raw=None):
    return LookupResult({}, raw or {}, 0., status)


def valid_tempo(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 20 <= value <= 400
