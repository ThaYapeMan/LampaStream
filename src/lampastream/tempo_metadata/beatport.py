"""Optional, nonredistributable Beatport v4 catalog metadata."""
import json
import logging
import time

from .http_page import fetch_json
from .registry import PROVIDERS
from .search_page import Document, featured_title, no_result, select, title_parts, valid_tempo

SEARCH_URL = 'https://api.beatport.com/v4/catalog/search/'
log = logging.getLogger(__name__)


def candidates_from(html):
    try:
        script = next(s for s in Document(html).root.all('script')
                      if s.attrs.get('id') == '__NEXT_DATA__')
        queries = json.loads(script.text())['props']['pageProps']['dehydratedState']['queries']
        tracks = next(q['state']['data']['tracks']['data'] for q in queries
                      if isinstance(q['state']['data'], dict) and 'tracks' in q['state']['data'])
    except (StopIteration, KeyError, ValueError, TypeError):
        return None
    if not isinstance(tracks, list):
        return None

    candidates = []
    for track in tracks:
        try:
            title, feature = featured_title(track['track_name'])
            artists = [a['artist_name'] for a in track['artists']
                       if a['artist_type_name'] == 'Artist']
            genre = ', '.join(g['genre_name'] for g in track.get('genre') or [])
            if not valid_tempo(track.get('bpm')):
                continue
            length = track.get('length')
            candidates.append(dict(artists=artists, title=title, feature=feature,
                                   version=track.get('mix_name') or '', isrc=track.get('isrc'),
                                   tempo=track['bpm'], key=track.get('key_name'),
                                   genre=genre or None, raw=track,
                                   duration=length / 1000 if length is not None else None))
        except (AttributeError, KeyError, TypeError):
            continue
    return candidates if candidates or not tracks else None


def parse(html, identity):
    candidates = candidates_from(html)
    return no_result('unreadable') if candidates is None else select(candidates, identity, .9)


def _name(value):
    name = value.get('name') if isinstance(value, dict) else None
    return name if isinstance(name, str) else None


def api_candidates(body):
    """Normalize the v4 search envelope and keep only catalog metadata."""
    try:
        tracks = json.loads(body)['tracks']
    except (KeyError, ValueError, TypeError, RecursionError):
        return None
    if not isinstance(tracks, list):
        return None
    candidates = []
    for track in tracks:
        if not isinstance(track, dict):
            return None
        name = _name(track)
        mix = track.get('mix_name')
        isrc = track.get('isrc')
        credits = track.get('artists')
        bpm = track.get('bpm')
        if (not name or not isinstance(credits, list)
                or (bpm is not None and not valid_tempo(bpm))
                or (mix is not None and not isinstance(mix, str))
                or (isrc is not None and not isinstance(isrc, str))):
            return None
        artists = [artist for credit in credits if (artist := _name(credit))]
        if not artists:
            return None
        if bpm is None:
            continue
        title, suffix, feature = title_parts(name)
        version = mix or suffix
        length = track.get('length_ms')
        duration = (length / 1000 if type(length) in (int, float)
                    and 0 < length <= 86400000 else None)
        key, genre = _name(track.get('key')), _name(track.get('genre'))
        raw = dict(id=track['id'] if type(track.get('id')) is int else None,
                   title=title, mix_name=version, artists=artists, bpm=bpm,
                   duration=duration, isrc=isrc, release=_name(track.get('release')),
                   key=key, genre=genre)
        candidates.append(dict(artists=artists, title=title, feature=feature, version=version,
                               isrc=isrc, tempo=bpm, duration=duration, key=key, genre=genre,
                               raw=raw))
    return candidates


class Adapter:
    def __init__(self, *, credentials=None, fetch=fetch_json):
        self.credentials = PROVIDERS['beatport'].credentials({'credentials': credentials})
        self.fetch = fetch

    def lookup(self, identity):
        if not self.credentials:
            return no_result('credentials_not_configured')
        started = time.monotonic()
        title, _, _ = title_parts(identity.title)
        query = f'{identity.artist} {title}'.strip()
        params = {'q': query, 'type': 'tracks', 'per_page': 25}
        page = self.fetch(SEARCH_URL, params=params, headers={
            'Authorization': f'Bearer {self.credentials}', 'Accept': 'application/json'})
        candidates = api_candidates(page.body) if page.status == 'ready' else None
        if page.status == 'ready':
            result = (select(candidates, identity, .9, strict_version=True)
                      if candidates is not None else no_result('unreadable'))
        else:
            status = {401: 'authentication_failed', 403: 'blocked',
                      429: 'rate_limited'}.get(page.http_status)
            result = no_result(status or {'too_large': 'unreadable', 'not_found': 'http_error'}
                               .get(page.status, page.status))
        log.info('provider=beatport http=%s bytes=%d candidates=%d status=%s match=%s '
                 'tempo=%s elapsed_ms=%d', page.http_status, page.byte_count, len(candidates or ()),
                 result.status, result.fields.get('match'), result.fields.get('tempo'),
                 round((time.monotonic() - started) * 1000))
        return result
