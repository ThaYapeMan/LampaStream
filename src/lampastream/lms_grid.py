"""LMS-only library acquisition; the analyser and grid consumer know no LMS."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import tempfile
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


class LmsGridAdapter:
    """One asynchronous worker; serial, low-priority analysis in an owned subprocess."""
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
        self.task = None
        self.process = None

    def select(self, track_id, filesize, *, new_instance=False):
        key = identity(track_id, filesize)
        if key == self.current and not new_instance:
            return False
        self.instance += 1
        self.current, self.grid = key, None
        self.cache_state = None
        self.state = 'queued'
        while not self.queue.empty():
            self.queue.get_nowait()
        self.enqueue(track_id, filesize)
        if not track_id or not filesize:
            self.state = "unavailable"
        return True

    def enqueue(self, track_id, filesize):
        if not track_id or not filesize:
            return
        if self.task is None:
            self.task = asyncio.create_task(self._worker(), name='lms-grid')
        if not self.queue.full():
            self.queue.put_nowait((str(track_id), int(filesize)))

    async def playlist_next(self, host, port, target, index):
        """One existing CLI playlist read on a track change, never periodic polling."""
        writer = None
        try:
            async with asyncio.timeout(3):
                reader, writer = await asyncio.open_connection(host, port, limit=65536)
                writer.write(f'{target} status {index+1} 1 tags:uf\n'.encode())
                await writer.drain()
                line = (await reader.readline()).decode()
                tags = dict(unquote(t).split(':', 1) for t in line.split()[4:]
                            if ':' in unquote(t))
                if identity(tags.get('id'), tags.get('filesize')) != self.current:
                    self.enqueue(tags.get('id'), tags.get('filesize'))
        except (OSError, ValueError, TimeoutError):
            log.exception('LMS next queued track unavailable')
        finally:
            if writer:
                writer.close()
                await writer.wait_closed()

    async def _worker(self):
        while True:
            track_id, filesize = await self.queue.get()
            key = identity(track_id, filesize)
            try:
                grid = await asyncio.to_thread(self.cache.get, key)
                hit = grid is not None
                if key == self.current:
                    self.cache_state = 'hit' if hit else 'miss'
                if grid is None:
                    if key == self.current:
                        self.state = 'fetching'
                    with tempfile.TemporaryDirectory(prefix='lampastream-grid-') as tmp:
                        path = Path(tmp) / 'audio'
                        await fetch_file(self.base, track_id, filesize, path)
                        content_hash = await asyncio.to_thread(
                            lambda path=path: hashlib.sha256(path.read_bytes()).hexdigest())
                        grid = await asyncio.to_thread(self.cache.get_hash, content_hash)
                        if grid is not None:
                            await asyncio.to_thread(self.cache.put, key, grid)
                            if key == self.current:
                                self.grid, self.state = grid, 'ready'
                            continue
                        if key == self.current:
                            self.state = 'analysing'
                        self.process = await asyncio.create_subprocess_exec(
                            'nice', '-n', '10', sys.executable, '-m',
                            'lampastream.grid.analyser', str(path),
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                            env={**os.environ, 'NUMBA_CACHE_DIR': str(self.cache.root / 'numba'),
                                 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
                        try:
                            output, error = await asyncio.wait_for(self.process.communicate(), 180)
                            if self.process.returncode:
                                raise ValueError(error.decode()[-2000:])
                            grid = TrackGrid.from_dict(json.loads(output))
                            if grid.file_sha256 != content_hash:
                                raise ValueError("Analyser content hash mismatch")
                        finally:
                            if self.process.returncode is None:
                                self.process.kill()
                                await self.process.wait()
                            self.process = None
                    await asyncio.to_thread(self.cache.put, key, grid)
                if key == self.current:
                    self.grid, self.state = grid, 'ready'
                log.info('Library grid %s %s %.2f BPM', key, 'hit' if hit else 'miss', grid.tempo)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Library grid unavailable for %s; retaining live tracker', key)
                if key == self.current:
                    self.state = 'failed'
            finally:
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
        # Only exact landed content coordinates enable timing acceptance.
        metadata = dict(grid_cache=self.cache_state, grid_fetch_state=self.state)
        instance = f"{self.current}@{self.instance}"
        empty = (instance, None, 0., metadata)
        if (self.grid is None or self.grid.timing_basis != 'content-v1'
                or content_position is None):
            return empty
        origin = content_position - sample_pos/48000
        return instance, self.grid, origin, metadata
