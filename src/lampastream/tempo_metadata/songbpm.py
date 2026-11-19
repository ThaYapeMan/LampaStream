"""Opt-in SongBPM search results; reference display only."""
from .search_page import Document, lookup, no_result, select, title_parts, valid_tempo


def candidates_from(html):
    document = Document(html).root
    candidates = []
    for link in document.all('a'):
        href = link.attrs.get('href') or ''
        if not href.startswith('/@'):
            continue
        paragraphs = [' '.join(p.text().split()) for p in link.all('p')]
        spans = [' '.join(s.text().split()) for s in link.all('span')]
        try:
            bpm = float(spans[spans.index('BPM') + 1])
            artist, title = paragraphs[:2]
            if not valid_tempo(bpm):
                continue
        except (ValueError, IndexError):
            continue
        duration = None
        try:
            minutes, seconds = spans[spans.index('Duration') + 1].split(':')
            duration = int(minutes) * 60 + int(seconds)
        except (ValueError, IndexError):
            pass
        key = spans[spans.index('Key') + 1:spans.index('Key') + 2] if 'Key' in spans else []
        base, version, feature = title_parts(title)
        raw = dict(artist=artist, title=title, tempo=bpm, duration=duration, href=href)
        candidates.append(dict(artists=[artist], title=base, version=version, feature=feature,
                               tempo=bpm, duration=duration, key=next(iter(key), None), raw=raw))
    no_results = any(' '.join(node.text().casefold().split()) in ('no results', 'no results found')
                     for tag in ('p', 'h1', 'h2', 'div') for node in document.all(tag))
    return candidates if candidates or no_results else None


def parse(html, identity):
    candidates = candidates_from(html)
    return no_result('unreadable') if candidates is None else select(candidates, identity, .7)


class Adapter:
    def __init__(self, *, url='https://songbpm.com/searches', client=None):
        self.url, self.client = url, client

    def lookup(self, identity):
        return lookup('songbpm', identity, self.url, self.client, candidates_from, .7, post=True)
