"""Bounded plain HTTP page acquisition, separate from provider parsing."""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Page:
    status: str
    url: str
    body: str = ''
    http_status: int | None = None

    def payload(self):
        return dict(status=self.status, url=self.url, http_status=self.http_status, html=self.body)


def fetch(url, *, params=None, client=None, timeout=5., max_bytes=2000000, method='GET', data=None):
    """No browser fallback. Transports can be injected for loopback-only tests."""
    own = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        with client.stream(method, url, params=params, data=data, timeout=timeout,
                           headers={'User-Agent': 'LampaStream/0.2 (personal tempo lookup)',
                                    'Accept': 'text/html,application/xhtml+xml'}) as response:
            location = str(response.url)
            status = response.status_code
            if status in (401, 403, 429):
                return Page('blocked', location, http_status=status)
            if status == 404:
                return Page('not_found', location, http_status=status)
            if not 200 <= status < 300:
                return Page('http_error', location, http_status=status)
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > max_bytes:
                    return Page('too_large', location, http_status=status)
            return Page('ready', location, chunks.decode(response.encoding or 'utf-8',
                                                       errors='replace'), status)
    except httpx.TimeoutException:
        return Page('timeout', str(url))
    except httpx.HTTPError:
        return Page('network_error', str(url))
    finally:
        if own:
            client.close()
