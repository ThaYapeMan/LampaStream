"""LMS-only library acquisition; the analyser and grid consumer know no LMS."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, unquote

import httpx

from .grid import TrackGrid
from .grid.cache import GridCache

log = logging.getLogger(__name__)


def identity(track_id, filesize):
    return f'lms:{track_id}:{filesize}'


async def fetch_file(base, track_id, filesize, destination, *, timeout=60):
    if not track_id or not filesize or filesize < 0:
        raise ValueError('Missing library track identity/filesize')
    size = 0
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            url = f'{base}/music/{quote(str(track_id), safe="")}/download'
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                with open(destination, 'wb', buffering=0) as out:
                    async for chunk in r.aiter_bytes(chunk_size=256*1024):
                        size += len(chunk)
                        if size > filesize:
                            raise ValueError('LMS download exceeds advertised filesize')
                        await asyncio.to_thread(out.write, chunk)
    if size != filesize:
        raise ValueError(f'LMS filesize mismatch: {size} != {filesize}')


async def fetch_head(base, track_id, filesize, destination, *, duration=None):
    """Bound the first original-byte range; a prefix is never a verified full download."""
    estimate = math.ceil(filesize*60/duration*1.25) if duration and duration > 0 else 16*1024**2
    limit = min(filesize, max(256*1024, estimate), 16*1024**2)
    size = 0
    async with asyncio.timeout(10):
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            url = f'{base}/music/{quote(str(track_id), safe="")}/download'
            headers = {'Range': f'bytes=0-{limit-1}'}
            async with client.stream('GET', url, headers=headers) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    match = re.fullmatch(r'bytes 0-(\d+)/(\d+)',
                                         response.headers.get('Content-Range', ''))
                    if not match or int(match[2]) != filesize or int(match[1])+1 != limit:
                        raise ValueError('Invalid LMS head Content-Range')
                elif response.status_code != 200:
                    raise ValueError('Unexpected LMS head response')
                with open(destination, 'wb', buffering=0) as out:
                    async for chunk in response.aiter_bytes(chunk_size=256*1024):
                        chunk = chunk[:limit-size]
                        await asyncio.to_thread(out.write, chunk)
                        size += len(chunk)
                        if size == limit:
                            break
    if size != limit:
        raise ValueError(f'LMS head size mismatch: {size} != {limit}')
    return size == filesize


class LmsGridAdapter:
    """One serial low-priority worker, with an immediate provisional head on a miss."""
    def __init__(self, host, web_port=9000, cache=None):
        host = f'[{host}]' if ':' in host else host
        self.base = f'http://{host}:{web_port}'
        self.cache = cache if cache is not None else GridCache()
        self.current = None
        self.instance = 0
        self.grid = None
        self.state = 'idle'
        self.cache_state = None
        self.queue = asyncio.Queue(maxsize=2)
        self.pending = set()
        self.task = None
        self.job = None
        self.process = None
        self.stages = []
        self.selected_at = 0.

    def select(self, track_id, filesize, *, new_instance=False, duration=None):
        key = identity(track_id, filesize)
        if key == self.current and not new_instance:
            return False
        self.instance += 1
        self.current, self.grid = key, None
        self.selected_at = time.monotonic()
        self.stages = []
        self.cache_state = None
        self.state = 'queued'
        if self.job and not self.job.done():
            self.job.cancel()
        while not self.queue.empty():
            old_id, old_size, _ = self.queue.get_nowait()
            self.pending.discard(identity(old_id, old_size))
            self.queue.task_done()
        self.enqueue(track_id, filesize, duration=duration, force=True)
        if not track_id or not filesize:
            self.state = 'unavailable'
        return True

    def enqueue(self, track_id, filesize, *, duration=None, force=False):
        if not track_id or not filesize:
            return False
        key = identity(str(track_id), int(filesize))
        if not force and key in self.pending:
            return False
        if self.task is None:
            self.task = asyncio.create_task(self._worker(), name='lms-grid')
        if self.queue.full():
            return False
        self.pending.add(key)
        self.queue.put_nowait((str(track_id), int(filesize), duration))
        return True

    async def playlist_next(self, host, port, target, index, *, trigger='start'):
        """One bounded queue read, triggered by start, existing notifications or 30 s safety net."""
        writer = None
        try:
            async with asyncio.timeout(3):
                reader, writer = await asyncio.open_connection(host, port, limit=65536)
                writer.write(f'{target} status {index+1} 1 tags:uf\n'.encode())
                await writer.drain()
                line = (await reader.readline()).decode()
                tags = dict(unquote(t).split(':', 1) for t in line.split()[4:]
                            if ':' in unquote(t))
                track_id, size = tags.get('id'), tags.get('filesize')
                if not track_id or not size:
                    result = 'no next track'
                else:
                    key = identity(track_id, size)
                    cached = await asyncio.to_thread(self.cache.get, key)
                    if cached is not None:
                        result = 'already cached'
                    elif key == self.current or key in self.pending:
                        result = 'already pending'
                    else:
                        queued = self.enqueue(track_id, size)
                        result = 'queued for pre-analysis' if queued else 'queue already busy'
                log.info('Library next lookup trigger=%s target=%s: %s id=%s',
                         trigger, target, result, track_id or '-')
        except asyncio.CancelledError:
            log.info('Library next lookup trigger=%s target=%s: superseded or closing',
                     trigger, target)
            raise
        except (OSError, ValueError, TimeoutError):
            log.exception('Library next lookup trigger=%s target=%s: failed', trigger, target)
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    def _publish(self, key, grid, stage, started):
        elapsed = time.monotonic()-started
        if key == self.current:
            self.grid = grid
            self.state = 'provisional' if grid.provisional else 'ready'
            self.stages.append(dict(stage=stage, elapsed_s=elapsed,
                                    since_start_s=time.monotonic()-self.selected_at))
        log.info('Library grid %s stage=%s provisional=%s duration=%.3fs tempo=%.2f BPM',
                 key, stage, grid.provisional, elapsed, grid.tempo)

    async def _analyse(self, path, *, head=False):
        self.process = await asyncio.create_subprocess_exec(
            'nice', '-n', '10', sys.executable, '-m', 'lampastream.grid.analyser', str(path),
            *(['--head'] if head else []), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, 'NUMBA_CACHE_DIR': str(self.cache.root/'numba'),
                 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
        try:
            output, error = await asyncio.wait_for(self.process.communicate(), 30 if head else 180)
            if self.process.returncode:
                raise ValueError(error.decode()[-2000:])
            return TrackGrid.from_dict(json.loads(output))
        finally:
            if self.process.returncode is None:
                self.process.kill()
                await self.process.wait()
            self.process = None

    async def _build(self, track_id, filesize, duration):
        key = identity(track_id, filesize)
        started = time.monotonic()
        grid = await asyncio.to_thread(self.cache.get, key)
        if key == self.current:
            self.cache_state = 'hit' if grid is not None else 'miss'
        if grid is not None:
            self._publish(key, grid, 'cache-hit', started)
            log.info('Library grid %s hit %.2f BPM', key, grid.tempo)
            return
        with tempfile.TemporaryDirectory(prefix='lampastream-grid-') as tmp:
            path = Path(tmp)/'audio'
            complete = False
            if key == self.current:
                self.state = 'fetching-head'
                try:
                    complete = await fetch_head(self.base, track_id, filesize, path,
                                                duration=duration)
                    head = await self._analyse(path, head=True)
                    self._publish(key, head, 'head', started)
                except (OSError, ValueError, TimeoutError, httpx.HTTPError):
                    log.info('Library grid %s head cannot decode partial container; '
                             'falling back to full fetch', key, exc_info=True)
            if not complete:
                await fetch_file(self.base, track_id, filesize, path)
            content_hash = await asyncio.to_thread(
                lambda: hashlib.sha256(path.read_bytes()).hexdigest())
            grid = await asyncio.to_thread(self.cache.get_hash, content_hash)
            if grid is None:
                if key == self.current and self.grid is None:
                    try:
                        head = await self._analyse(path, head=True)
                        self._publish(key, head, 'head-after-full-fetch', started)
                    except (OSError, ValueError, TimeoutError):
                        log.info('Library grid %s no provisional grid; retaining live onset', key)
                grid = await self._analyse(path)
                if grid.file_sha256 != content_hash:
                    raise ValueError('Analyser content hash mismatch')
            await asyncio.to_thread(self.cache.put, key, grid)
        self._publish(key, grid, 'full', started)
        log.info('Library grid %s miss %.2f BPM', key, grid.tempo)

    async def _worker(self):
        while True:
            track_id, filesize, duration = await self.queue.get()
            key = identity(track_id, filesize)
            self.job = asyncio.create_task(self._build(track_id, filesize, duration))
            try:
                await self.job
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                log.exception('Library grid unavailable for %s; retaining live analysis', key)
                if key == self.current:
                    self.state = 'failed'
            finally:
                self.pending.discard(key)
                self.job = None
                self.queue.task_done()

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    def prior(self, content_position, sample_pos):
        metadata = dict(grid_cache=self.cache_state, grid_fetch_state=self.state)
        instance = f'{self.current}@{self.instance}'
        if (self.grid is None or self.grid.timing_basis != 'content-v1'
                or content_position is None):
            return instance, None, 0., metadata
        return instance, self.grid, content_position-sample_pos/48000, metadata
