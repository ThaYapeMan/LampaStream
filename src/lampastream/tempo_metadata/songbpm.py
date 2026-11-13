"""Opt-in SongBPM search results; reference display only."""
from .http_page import fetch
from .registry import LookupResult
from .search_page import Document, no_result, select, valid_tempo


def parse(html, identity):
    document = Document(html).root
    candidates = []
    links = [a for a in document.all('a') if a.attrs.get('href', '').startswith('/@')]
    for link in links:
        paragraphs = [' '.join(p.text().split()) for p in link.all('p')]
        spans = [' '.join(s.text().split()) for s in link.all('span')]
        try:
            bpm = float(spans[spans.index('BPM')+1])
            minutes, seconds = spans[spans.index('Duration')+1].split(':')
            if len(paragraphs) < 2 or not valid_tempo(bpm):
                continue
            candidates.append(dict(artist=paragraphs[0], title=paragraphs[1], tempo=bpm,
                                   duration=int(minutes)*60+int(seconds),
                                   href=link.attrs['href']))
        except (ValueError, IndexError):
            continue
    row = select(candidates, identity)
    if row:
        return LookupResult({'tempo': row['tempo']}, row, .7)
    return no_result('not_found' if candidates or 'no results' in html.casefold()
                     else 'layout_changed')


class Adapter:
    def __init__(self, *, url='https://songbpm.com/searches', client=None):
        self.url, self.client = url, client

    def lookup(self, identity):
        page = fetch(self.url, method='POST', data={'query': f'{identity.artist} {identity.title}'},
                     client=self.client)
        if page.status != 'ready':
            return no_result(page.status, {'url': page.url, 'http_status': page.http_status})
        result = parse(page.body, identity)
        return LookupResult(result.fields, dict(url=page.url, track=result.raw_payload),
                            result.confidence, result.status)
