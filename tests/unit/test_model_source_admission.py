from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.resilience.model_source_admission import (
    GLM_CAPS,
    ModelSourceAdmission,
    ModelSourceAdmissionError,
    _NativeLock,
    safe_rate_headers,
)
from app.modules.model_sources import forwarding

pytestmark = pytest.mark.unit


def lease(root: Path, model: str = "glm-5.3-flashx", wait: float = 0.05) -> ModelSourceAdmission:
    return ModelSourceAdmission(root=root, model=model, credential="fake-test-account", wait_seconds=wait)


@pytest.mark.parametrize("model,cap", list(GLM_CAPS.items()))
async def test_exact_cap_refuses_without_free_slot(tmp_path: Path, model: str, cap: int) -> None:
    async with AsyncExitStack() as stack:
        for _ in range(cap):
            await stack.enter_async_context(lease(tmp_path, model))
        with pytest.raises(ModelSourceAdmissionError):
            async with lease(tmp_path, model):
                pytest.fail("over-cap request admitted")
    async with lease(tmp_path, model):
        pass
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert max(e["active"] for e in events) == cap
    assert sum(e["event"] == "admitted" for e in events) == cap + 1
    assert sum(e["event"] == "released" for e in events) == cap + 1


async def test_waiter_and_cancelled_waiter_do_not_leak_slots(tmp_path: Path) -> None:
    first, second = lease(tmp_path), lease(tmp_path)
    await first.__aenter__()
    await second.__aenter__()
    waiting = lease(tmp_path, wait=5)
    task = asyncio.create_task(waiting.__aenter__())
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert waiting.slot is None
    await first.__aexit__()
    async with lease(tmp_path):
        pass
    await second.__aexit__()


async def test_other_process_and_process_death_share_native_slots(tmp_path: Path) -> None:
    code = """
import asyncio, sys
from pathlib import Path
from app.core.resilience.model_source_admission import ModelSourceAdmission
async def main():
    gate = ModelSourceAdmission(root=Path(sys.argv[1]), model='glm-5.3-flashx',
                                credential='fake-test-account', wait_seconds=2)
    async with gate:
        print('HELD', flush=True)
        sys.stdin.readline()
asyncio.run(main())
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert await asyncio.to_thread(child.stdout.readline) == "HELD\n"
        async with lease(tmp_path):
            with pytest.raises(ModelSourceAdmissionError):
                async with lease(tmp_path):
                    pytest.fail("cross-process cap escaped")
            child.terminate()
            await asyncio.to_thread(child.wait, 5)
            async with lease(tmp_path):
                pass
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()


def test_capture_allowlist_rejects_secrets_and_arbitrary_values() -> None:
    assert safe_rate_headers(
        {
            "Authorization": "Bearer secret",
            "x-ratelimit-limit-requests": "5",
            "x-ratelimit-reset-requests": "1m",
            "x-ratelimit-remaining": "secret",
            "Retry-After": "Tue, 13 Oct 2026 19:00:00 GMT",
            "x-ratelimit-limit": "5\nAuthorization: secret",
        }
    ) == {
        "x-ratelimit-limit-requests": "5",
        "x-ratelimit-reset-requests": "1m",
        "retry-after": "Tue, 13 Oct 2026 19:00:00 GMT",
    }


def test_only_exact_capped_zai_models_are_admitted(tmp_path: Path) -> None:
    for host, model in [
        ("https://api.example.com/v1", "glm-5.3-flash"),
        ("https://api.z.ai.attacker.test/v1", "glm-5.3-flash"),
        ("https://api.z.ai/api/coding/paas/v4", "gpt-6.1-sol"),
    ]:
        assert (
            ModelSourceAdmission.for_request(
                base_url=host, model=model, credential="secret", data_dir=tmp_path, wait_seconds=1
            )
            is None
        )


class FakeResponse:
    def __init__(self, status: int, block: asyncio.Event | None = None) -> None:
        self.status = status
        self.headers = {"Retry-After": "7", "Authorization": "Bearer response-secret"}
        self.content = self
        self.block = block
        self.closed = False
        self.frames = [b'data: {"choices": []}\n\n', b"data: [DONE]\n\n"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        self.closed = True

    async def json(self, **_kwargs):
        return {"choices": [], "output": [], "error": {"message": "fake error"}}

    async def iter_chunked(self, _size):
        while self.frames:
            if len(self.frames) == 1 and self.block is not None:
                await self.block.wait()
            yield self.frames.pop(0)

    async def readany(self):
        return self.frames.pop(0) if self.frames else b""


@pytest.fixture
def fake_boundary(monkeypatch, tmp_path: Path):
    responses: list[FakeResponse] = []
    calls: list[str] = []
    settings = SimpleNamespace(
        data_dir=tmp_path, proxy_admission_wait_timeout_seconds=0.02, stream_idle_timeout_seconds=100
    )
    monkeypatch.setattr(forwarding, "get_settings", lambda: settings)
    monkeypatch.setattr(forwarding, "with_dashboard_overrides", lambda x: x)
    source = SimpleNamespace(
        base_url="https://api.z.ai/api/coding/paas/v4", api_key_encrypted=None, timeout_seconds=30, request_headers={}
    )
    monkeypatch.setattr(forwarding, "_source_api_key_secret", lambda *_a, **_k: "fake-test-account")

    class Session:
        def post(self, url, **_kwargs):
            calls.append(url)
            return responses.pop(0)

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(forwarding, "lease_model_source_session", session)
    return source, responses, calls


async def test_forwarding_keeps_stream_slots_until_close_and_refuses_upstream(fake_boundary, tmp_path: Path):
    source, responses, calls = fake_boundary
    responses.extend([FakeResponse(200), FakeResponse(200), FakeResponse(200)])
    payload = {"model": "glm-5.3-flashx", "messages": []}
    a = await forwarding.stream_chat_completion(source, payload)
    b = await forwarding.stream_chat_completion(source, payload)
    assert len(calls) == 2
    with pytest.raises(forwarding.ModelSourceForwardingError) as error:
        await forwarding.forward_chat_completion(source, payload)
    assert error.value.status_code == 503
    assert len(calls) == 2
    await a.aclose()  # Even a stream never iterated must release its slot.
    await forwarding.forward_chat_completion(source, payload)
    assert len(calls) == 3
    await b.aclose()
    async with lease(tmp_path / "model-source-admission"):
        pass


async def test_stream_completion_error_and_cancellation_release(fake_boundary, tmp_path: Path):
    source, responses, calls = fake_boundary
    payload = {"model": "glm-5.3-flashx", "messages": []}
    responses.append(FakeResponse(200))
    stream = await forwarding.stream_chat_completion(source, payload)
    assert len([chunk async for chunk in stream.body]) == 2
    responses.append(FakeResponse(429))
    with pytest.raises(forwarding.ModelSourceForwardingError):
        await forwarding.forward_chat_completion(source, payload)
    block = asyncio.Event()
    responses.append(FakeResponse(200, block))
    stream = await forwarding.stream_chat_completion(source, payload)

    async def consume():
        async for _ in stream.body:
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with lease(tmp_path / "model-source-admission"):
        async with lease(tmp_path / "model-source-admission"):
            pass
    events = [json.loads(line) for line in (tmp_path / "model-source-admission/events.jsonl").read_text().splitlines()]
    assert sum(e["event"] == "response" and e["status"] == 429 for e in events) == 1
    released = [e for e in events if e["event"] == "released"]
    assert released[0]["outcome"] == "stream_eof"
    assert sum(e["outcome"] == "aborted_or_unconsumed" for e in released) == 4
    assert not any("secret" in json.dumps(e) for e in events)


async def test_contended_telemetry_refuses_within_admission_budget(fake_boundary, tmp_path: Path):
    source, responses, calls = fake_boundary
    responses.append(FakeResponse(200))
    root = tmp_path / "model-source-admission"
    root.mkdir()
    lock = _NativeLock(root / "events.lock")
    lock.acquire()
    try:
        started = asyncio.get_running_loop().time()
        with pytest.raises(forwarding.ModelSourceForwardingError) as error:
            await forwarding.forward_chat_completion(source, {"model": "glm-5.3-flashx"})
        assert error.value.status_code == 503
        assert asyncio.get_running_loop().time() - started < 0.2
        assert calls == []
    finally:
        lock.release()
    # Refused admission left no reservation behind.
    async with lease(root):
        async with lease(root):
            pass


async def test_responses_repeated_cancel_does_not_release_before_response_close(fake_boundary, tmp_path: Path):
    source, responses, _calls = fake_boundary
    reading, closing, close_allowed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SlowResponse(FakeResponse):
        async def json(self, **_kwargs):
            reading.set()
            await asyncio.Event().wait()

        async def __aexit__(self, *_exc):
            closing.set()
            await close_allowed.wait()
            self.closed = True

    response = SlowResponse(200)
    responses.append(response)
    root = tmp_path / "model-source-admission"
    # One existing request occupies the other slot.
    async with lease(root):
        task = asyncio.create_task(forwarding.forward_responses(source, {"model": "glm-5.3-flashx"}))
        try:
            await asyncio.wait_for(reading.wait(), 1)
            task.cancel()
            await asyncio.wait_for(closing.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            assert not response.closed
            with pytest.raises(ModelSourceAdmissionError):
                async with lease(root):
                    pytest.fail("slot released before response cleanup")
        finally:
            close_allowed.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert response.closed
    async with lease(root):
        async with lease(root):
            pass


@pytest.mark.parametrize("streaming", [False, True])
async def test_responses_cap_and_completion(fake_boundary, tmp_path: Path, streaming: bool):
    source, responses, calls = fake_boundary
    root = tmp_path / "model-source-admission"
    payload = {"model": "glm-5.3-flashx"}
    async with lease(root):
        async with lease(root):
            with pytest.raises(forwarding.ModelSourceForwardingError) as error:
                if streaming:
                    await forwarding.stream_responses(source, payload)
                else:
                    await forwarding.forward_responses(source, payload)
            assert error.value.status_code == 503
    assert calls == []
    response = FakeResponse(200)
    responses.append(response)
    if streaming:
        stream = await forwarding.stream_responses(source, payload)
        assert len([chunk async for chunk in stream.body]) == 2
    else:
        await forwarding.forward_responses(source, payload)
    assert response.closed
    assert calls == ["https://api.z.ai/api/coding/paas/v4/responses"]


async def test_non_zai_forwarding_does_not_require_admission_settings(fake_boundary, monkeypatch):
    source, responses, calls = fake_boundary
    source.base_url = "https://example.test/v1"
    monkeypatch.setattr(forwarding, "get_settings", lambda: SimpleNamespace())
    responses.append(FakeResponse(200))
    await forwarding.forward_chat_completion(source, {"model": "glm-5.3-flashx"})
    assert calls == ["https://example.test/v1/chat/completions"]
