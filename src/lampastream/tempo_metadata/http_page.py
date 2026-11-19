"""Bounded plain HTTP page acquisition, separate from provider parsing."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Page:
    status: str
    url: str
    body: str = ''
    http_status: int | None = None
    byte_count: int = 0

    def payload(self):
        return dict(status=self.status, url=self.url, http_status=self.http_status, html=self.body)


def fetch(url, *, params=None, client=None, timeout=5., max_bytes=2000000, method='GET', data=None):
    """No browser fallback. Transports can be injected for loopback-only tests."""
    if client is None:
        try:
            return asyncio.run(_fetch_song_page(url, params, timeout, max_bytes, method, data))
        except (TimeoutError, httpx.TimeoutException):
            return Page('timeout', str(url))
        except httpx.HTTPError:
            return Page('network_error', str(url))
    try:
        with client.stream(method, url, params=params, data=data, timeout=timeout,
                           headers={'User-Agent': 'LampaStream/0.2 (personal tempo lookup)',
                                    'Accept': 'text/html,application/xhtml+xml'}) as response:
            location = str(response.url)
            status = _page_status(response.status_code)
            if status != 'ready':
                return Page(status, location, http_status=response.status_code)
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > max_bytes:
                    return Page('too_large', location, http_status=response.status_code,
                                byte_count=len(chunks))
            text = chunks.decode(response.encoding or 'utf-8', errors='replace')
            return Page('ready', location, text, response.status_code, len(chunks))
    except httpx.TimeoutException:
        return Page('timeout', str(url))
    except httpx.HTTPError:
        return Page('network_error', str(url))


async def _fetch_song_page(url, params, timeout, max_bytes, method, data):
    return await _fetch_async(
        url, params=params, timeout=timeout, overall_timeout=2 * timeout,
        max_bytes=max_bytes, method=method, data=data, follow_redirects=True,
        headers={'User-Agent': 'LampaStream/0.2 (personal tempo lookup)',
                 'Accept': 'text/html,application/xhtml+xml'})


def _page_status(status):
    if status in (401, 403, 429):
        return 'blocked'
    if status == 404:
        return 'not_found'
    return 'ready' if 200 <= status < 300 else 'http_error'


async def _fetch_async(url, *, params, headers, timeout, overall_timeout, max_bytes,
                       method='GET', data=None, follow_redirects=False):
    async with asyncio.timeout(overall_timeout):
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects) as client:
            async with client.stream(method, url, params=params, headers=headers,
                                     data=data) as response:
                location = str(response.url)
                status = _page_status(response.status_code)
                if status != 'ready':
                    return Page(status, location, http_status=response.status_code)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > max_bytes:
                        return Page('too_large', location, http_status=response.status_code)
                    body.extend(chunk)
                text = body.decode(response.encoding or 'utf-8', errors='replace')
                return Page('ready', location, text, response.status_code, len(body))


def fetch_json(url, *, params, headers, timeout=3., overall_timeout=6., max_bytes=262144):
    """Bound the whole authenticated request, including DNS and streamed reads."""
    try:
        return asyncio.run(_fetch_async(url, params=params, headers=headers, timeout=timeout,
                                        overall_timeout=overall_timeout, max_bytes=max_bytes))
    except httpx.ConnectTimeout:
        return Page('connect_timeout', url)
    except httpx.ReadTimeout:
        return Page('read_timeout', url)
    except (TimeoutError, httpx.TimeoutException):
        return Page('timeout', url)
    except httpx.HTTPError:
        return Page('network_error', url)
