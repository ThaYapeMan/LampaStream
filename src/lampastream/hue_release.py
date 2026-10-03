"""Bounded, asynchronous Hue v2 state snapshots and release actions."""
import asyncio
import logging

import httpx

log = logging.getLogger(__name__)


class HueReleaseRest:
    def __init__(self, bridge, area_id):
        self.bridge, self.area_id = bridge, area_id
        self.snapshot = None
        self.light_ids = []

    async def _request(self, method, path='', body=None):
        async with httpx.AsyncClient(verify=False, timeout=3) as client:
            response = await asyncio.wait_for(client.request(
                method, f'https://{self.bridge.host}/clip/v2/resource{path}',
                headers={'hue-application-key': self.bridge.app_key}, json=body), 3)
            response.raise_for_status()
            result = response.json()
            if result.get('errors'):
                raise ValueError('Hue rejected the light state request')
            return result.get('data', [])

    async def stop_area(self):
        await self._request('PUT', '/entertainment_configuration/' + self.area_id,
                            {'action': 'stop'})

    async def available(self):
        async with asyncio.timeout(10):
            rows = await self._request('GET', '/entertainment_configuration')
            return not any(r.get('status') == 'active' for r in rows)

    async def capture(self):
        self.snapshot = None
        self.light_ids = []
        try:
            async with asyncio.timeout(10):
                rows = await self._request('GET')
                resources = {r['id']: r for r in rows}
                area = resources[self.area_id]
                refs = list(area.get('light_services', []))
                refs += [m['service'] for c in area.get('channels', [])
                         for m in c.get('members', [])]
                ids = set()
                for ref in refs:
                    resource = resources.get(ref['rid'], {})
                    if resource.get('type') == 'light':
                        ids.add(resource['id'])
                    else:
                        device = resources.get(resource.get('owner', {}).get('rid'), {})
                        ids.update(s['rid'] for s in device.get('services', [])
                                   if s.get('rtype') == 'light')
                if not ids:
                    raise ValueError('No lights found in the entertainment area')
                self.light_ids = sorted(ids)
                snapshot = {}
                for identity in self.light_ids:
                    light = resources[identity]
                    state = {}
                    if 'on' in light:
                        state['on'] = {'on': light['on']['on']}
                    if 'brightness' in light.get('dimming', {}):
                        state['dimming'] = {'brightness': light['dimming']['brightness']}
                    temperature = light.get('color_temperature', {})
                    if temperature.get('mirek_valid') and temperature.get('mirek') is not None:
                        state['color_temperature'] = {'mirek': temperature['mirek']}
                    elif light.get('color', {}).get('xy'):
                        state['color'] = {'xy': light['color']['xy']}
                    snapshot[identity] = state
                self.snapshot = snapshot
        except (Exception, TimeoutError):
            log.warning('Light state snapshot unavailable; restoration will be skipped')

    async def finish(self, mode, *, external=False):
        if mode == 'leave' or mode == 'off' and external:
            return
        if mode == 'restore' and self.snapshot is None:
            log.warning('No light state snapshot available; restoration skipped')
            return
        try:
            async with asyncio.timeout(10):
                for identity in self.light_ids:
                    body = self.snapshot[identity] if mode == 'restore' else {'on': {'on': False}}
                    try:
                        await self._request('PUT', '/light/' + identity, body)
                    except Exception:
                        log.warning('Light release request failed within its budget')
        except (Exception, TimeoutError):
            log.warning('Light release action could not finish within its budget')
