"""Small HTML reader and conservative search-result identity matching."""
import re
import unicodedata
from html.parser import HTMLParser

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


def normalized(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))


def select(candidates, identity):
    matches = [r for r in candidates if normalized(r['artist']) == normalized(identity.artist)
               and normalized(r['title']) == normalized(identity.title)]
    # Search ranking is not evidence of mix identity. Prefer a matching duration.
    if identity.duration and len(matches) > 1:
        matches = [r for r in matches if abs(r.get('duration', 0)-identity.duration) <= 2]
    if len(matches) != 1:
        return None
    return matches[0]


def no_result(status, raw=None):
    return LookupResult({}, raw or {}, 0., status)


def valid_tempo(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 20 <= value <= 400
