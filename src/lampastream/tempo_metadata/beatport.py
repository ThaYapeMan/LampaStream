"""Personal, nonredistributable Beatport search metadata over plain HTTP."""
import json

from .search_page import Document, featured_title, lookup, no_result, select, valid_tempo


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


class Adapter:
    def __init__(self, *, url='https://www.beatport.com/nl/search', client=None):
        self.url, self.client = url, client

    def lookup(self, identity):
        # Only selected track data survives; session tokens in the page are discarded.
        return lookup('beatport', identity, self.url, self.client, candidates_from, .9)
