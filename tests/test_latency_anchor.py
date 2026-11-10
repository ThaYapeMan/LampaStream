"""Native content-clock anchors through a fake LMS CLI on loopback."""

import asyncio
from dataclasses import replace

import pytest
from test_auto_latency import FOLLOW, OWN, fixture_probe


@pytest.mark.parametrize("scenario", ["slide", "large step", "small step", "track", "seek"])
def test_native_latency_guard(scenario, caplog):
    async def exercise():
        probe, follower, contexts, now, saved = fixture_probe(trim_ms=7)
        now[0] = 0
        probe.startup_at = 0
        follower.position_alignment = (1, 0)
        probe.position_clock = lambda: (100 + now[0] + 0.012, now[0], 0)
        residual_ms = -80
        commands = []

        async def handle(reader, writer):
            line = (await reader.readline()).decode().strip()
            commands.append(line)
            position = 100 + now[0]
            value = (
                5
                if "playerpref" in line
                else (position if line.startswith(OWN) else position - residual_ms / 1000)
            )
            writer.write((line.removesuffix("?") + str(value) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async def sample(at):
            now[0] = at
            await probe.tick()
            return probe.status()

        async with await asyncio.start_server(handle, "127.0.0.1", 0) as server:
            follower._port = server.sockets[0].getsockname()[1]
            for at in range(1, 32):
                if scenario == "slide" and at > 4:
                    residual_ms = -80 + 0.5 * (at - 4)
                startup = await sample(at)
            anchor_at = startup["session_anchor_at"]
            anchor = startup["applied_delay_ms"]
            generation = probe.mapping_generation
            assert anchor_at is not None
            assert anchor == pytest.approx(-56)
            assert startup["startup_step_used"] and generation == 1
            assert saved[-1][0] == 17  # Native bias plus Player Delay.

            if scenario == "slide":
                for at in range(46, 432, 15):
                    residual_ms = -80 + 0.5 * (at - 4)
                    status = await sample(at)
                    assert status["applied_delay_ms"] == pytest.approx(anchor, abs=2)
                    assert status["session_anchor_at"] == anchor_at
                    assert status["state"] == "stable"
                assert status["guard_residual_ms"] > 200
                logs = [
                    record
                    for record in caplog.records
                    if "latency guard: residual slide" in record.message
                ]
                assert len(logs) == 6
                assert all("0.50 ms/s" in record.message for record in logs)
            elif scenario in {"track", "seek"}:
                track = 2 if scenario == "track" else 1
                contexts[0] = replace(contexts[0], track=track, transition=2, changed_at=50)
                follower.position_alignment = (track, 0)
                residual_ms += 150
                for at in (51, 52, 53):
                    status = await sample(at)
                    assert status["session_anchor_at"] is None
                    assert status["applied_delay_ms"] == pytest.approx(anchor)
                status = await sample(54)
                assert status["startup_step_used"]
                assert status["session_anchor_at"] > anchor_at
                assert status["applied_delay_ms"] == pytest.approx(anchor + 150)
                generation += 1
                assert (await sample(55))["session_anchor_at"] == status["session_anchor_at"]
            else:
                step = 150 if scenario == "large step" else 40
                residual_ms += step
                for at in (46, 61, 76):
                    status = await sample(at)
                    assert status["session_anchor_at"] == anchor_at
                    assert status["applied_delay_ms"] == pytest.approx(anchor)
                status = await sample(91)
                assert status["applied_delay_ms"] == pytest.approx(anchor)
                if scenario == "large step":
                    assert status["session_anchor_at"] > anchor_at
                    assert status["state"] == "measuring"
                    for elapsed in range(1, 31):
                        now[0] = 91 + elapsed
                        assert probe.current_delay_ms() == pytest.approx(anchor + 5 * elapsed)
                    assert probe.status()["state"] == "stable"
                else:
                    assert status["session_anchor_at"] == anchor_at
                    assert (await sample(136))["applied_delay_ms"] == pytest.approx(anchor)
            assert probe.mapping_generation == generation
            assert commands.count(f"{FOLLOW} playerpref playDelay ?") == 1

    with caplog.at_level("INFO", logger="lampastream.latency"):
        asyncio.run(exercise())
