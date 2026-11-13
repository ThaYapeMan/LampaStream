"""Personal, nonredistributable Beatport search metadata over plain HTTP."""
import json

from .http_page import fetch
from .registry import LookupResult
from .search_page import Document, no_result, select, valid_tempo


def parse(html, identity):
    try:
        script = next(s for s in Document(html).root.all('script')
                      if s.attrs.get('id') == '__NEXT_DATA__')
        queries = json.loads(script.text())['props']['pageProps']['dehydratedState']['queries']
        tracks = next(q['state']['data']['tracks']['data'] for q in queries
                      if 'tracks' in q['state']['data'])
        candidates = []
        for track in tracks:
            artists = [a['artist_name'] for a in track['artists']
                       if a['artist_type_name'] == 'Artist']
            if not valid_tempo(track.get('bpm')):
                continue
            candidates.append(dict(artist=', '.join(artists), title=track['track_name'],
                                   duration=track['length']/1000, raw=track))
        row = select(candidates, identity)
        if row is None:
            return no_result('not_found')
        track = row['raw']
        return LookupResult(dict(tempo=track['bpm'], key=track['key_name'],
                                 genre=', '.join(g['genre_name'] for g in track['genre'])),
                            track, .9)
    except (StopIteration, KeyError, ValueError, TypeError):
        return no_result('layout_changed')


class Adapter:
    def __init__(self, *, url='https://www.beatport.com/nl/search', client=None):
        self.url, self.client = url, client

    def lookup(self, identity):
        page = fetch(self.url, params={'q': f'{identity.artist} {identity.title}'},
                     client=self.client)
        if page.status != 'ready':
            return no_result(page.status, {'url': page.url, 'http_status': page.http_status})
        result = parse(page.body, identity)
        # Store the selected raw track only; session tokens in the page are discarded.
        return LookupResult(result.fields, dict(url=page.url, track=result.raw_payload),
                            result.confidence, result.status)
