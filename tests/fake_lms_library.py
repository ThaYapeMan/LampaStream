"""Loopback-only library extension of the fake_lms.Session wire-fixture pattern.

Unlike the native SlimProto Session, this session owns only HTTP and CLI;
no player subprocess, SHM reader, real LMS or speaker is involved.
"""
import asyncio
import re
from urllib.parse import quote


class Session:
    def __init__(self, path, *, advertised_size=None, status=200, next_path=None, duration=16):
        self.path = path
        self.next_path = next_path
        self.duration = duration
        self.current_id = "44436"
        self.listeners = set()
        self.ranges = []
        self.size = path.stat().st_size if advertised_size is None else advertised_size
        self.status = status
        self.requests = []
        self.commands = []
        self.tasks = set()

    async def __aenter__(self):
        self.http = await asyncio.start_server(self._http, '127.0.0.1', 0)
        self.cli = await asyncio.start_server(self._cli, '127.0.0.1', 0)
        self.web_port = self.http.sockets[0].getsockname()[1]
        self.cli_port = self.cli.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        for server in (self.http, self.cli):
            server.close()
            await server.wait_closed()
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _http(self, reader, writer):
        self.tasks.add(asyncio.current_task())
        try:
            lines = (await reader.readuntil(b'\r\n\r\n')).decode().splitlines()
            request = lines[0]
            headers = dict(line.lower().split(': ', 1) for line in lines[1:] if ': ' in line)
            self.requests.append(request)
            paths = {'/music/44436/download': self.path}
            if self.next_path:
                paths['/music/44437/download'] = self.next_path
            path = paths.get(request.split()[1])
            body = (path or self.path).read_bytes()
            total = len(body)
            status = self.status if path else 404
            extra = ''
            match = re.fullmatch(r'bytes=0-(\d+)', headers.get('range', ''))
            if match and status == 200:
                end = min(total-1, int(match[1]))
                body = body[:end+1]
                status = 206
                extra = f'Content-Range: bytes 0-{end}/{total}\r\n'
            self.ranges.append(headers.get('range'))
            writer.write((f'HTTP/1.1 {status} fixture\r\nContent-Length: {len(body)}\r\n'
                          f'{extra}Content-Type: audio/x-flac\r\n'
                          'Connection: close\r\n\r\n').encode())
            for i in range(0, len(body), 7919):
                writer.write(body[i:i+7919])
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.tasks.discard(asyncio.current_task())

    async def append(self, path):
        self.next_path = path
        for writer in tuple(self.listeners):
            writer.write(b'aa playlist addtracks count:1\n')
            await writer.drain()

    def _tags(self):
        following = self.current_id == '44437'
        path = self.next_path if following else self.path
        size = path.stat().st_size if following else self.size
        return ['mode:play', f'playlist_cur_index:{int(following)}',
                f'id:{self.current_id}', f'filesize:{size}', f'duration:{self.duration}',
                'url:file:///fixture.flac', 'time:0', 'title:Fixture']

    async def _cli(self, reader, writer):
        self.tasks.add(asyncio.current_task())
        try:
            command = (await reader.readline()).decode().strip()
            self.commands.append(command)
            if command == 'listen 1':
                self.listeners.add(writer)
                await reader.read()
                return
            tags = self._tags()
            if 'subscribe:10' not in command:
                tags = (['id:44437', f'filesize:{self.next_path.stat().st_size}',
                         'url:file:///next.flac']
                        if self.next_path and 'status 1 1' in command else [])
            writer.write((command+' '+' '.join(quote(t, safe='') for t in tags)+'\n').encode())
            await writer.drain()
            if 'subscribe:10' in command:
                while True:
                    try:
                        await asyncio.wait_for(reader.read(), 10)
                        break
                    except TimeoutError:
                        tags = self._tags()
                        writer.write((command+' '+' '.join(quote(t, safe='') for t in tags)
                                      +'\n').encode())
                        await writer.drain()
        finally:
            self.listeners.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.tasks.discard(asyncio.current_task())
