"""Local cross-process admission for the operator's temporary GLM caps.

This gates physical requests at model-source forwarding, not agent/task counts.
All participating workers must share data_dir and the same credential. Direct
clients and replicas with different data directories are outside this boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

try:
    import fcntl
except ImportError:  # Fail closed only for capped requests on non-POSIX hosts.
    fcntl = None


logger = logging.getLogger(__name__)
GLM_CAPS = {"glm-5.3-flashx": 2, "glm-5.3-flash": 5}
_RATE_HEADERS = frozenset(
    {
        "retry-after",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-ratelimit-limit-requests",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-reset-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-tokens",
        "x-ratelimit-concurrency",
    }
)
_NUMERIC_RATE = re.compile(r"\d+(?:\.\d+)?(?:ms|s|m|h)?\Z")
_MAX_EVENTS_BYTES = 16 * 1024 * 1024


class ModelSourceAdmissionError(Exception):
    """The local cap could not admit a request; no upstream attempt occurred."""


class _SlotBusy(Exception):
    pass


class _NativeLock:
    """Kernel-owned POSIX lock: process death releases it without a TTL or sweeper."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def acquire(self, timeout: float = 0) -> None:
        # All callers poll asynchronously. Never block the event loop in flock.
        if timeout != 0:
            raise ValueError("Native admission locks are nonblocking")
        if fcntl is None:
            raise ModelSourceAdmissionError("GLM request admission requires POSIX file locks")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise _SlotBusy from None
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def release(self) -> None:
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)

    def __enter__(self) -> _NativeLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def safe_rate_headers(headers: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, raw in headers.items():
        name = name.lower()
        if name not in _RATE_HEADERS:
            continue
        value = str(raw).strip()
        if len(value) > 96 or "\n" in value or "\r" in value:
            continue
        if _NUMERIC_RATE.fullmatch(value):
            values[name] = value
        elif name == "retry-after":
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is not None:
                    values[name] = format_datetime(date.astimezone(timezone.utc), usegmt=True)
            except (ValueError, TypeError, OverflowError):
                pass
    return values


def is_capped_request(base_url: str, model: str) -> bool:
    return urlsplit(base_url).hostname == "api.z.ai" and model.lower().rsplit("/", 1)[-1] in GLM_CAPS


class ModelSourceAdmission:
    def __init__(self, *, root: Path, model: str, credential: str, wait_seconds: float) -> None:
        self.root = root
        self.model = model
        # Only the opaque digest is used for slot identity; never written to telemetry.
        self.group = root / hashlib.sha256(credential.encode()).hexdigest() / model
        self.cap = GLM_CAPS[model]
        self.wait_seconds = wait_seconds
        self.request_id = uuid.uuid4().hex
        self.slot: _NativeLock | None = None
        self.status: int | None = None
        self._response_seen = False
        self.outcome = "aborted_or_unconsumed"

    @classmethod
    def for_request(
        cls,
        *,
        base_url: str,
        model: str,
        credential: str,
        data_dir: Path,
        wait_seconds: float,
    ) -> ModelSourceAdmission | None:
        model = model.lower().rsplit("/", 1)[-1]
        if not is_capped_request(base_url, model):
            return None
        if not credential:
            raise ModelSourceAdmissionError("Capped Z.AI request has no credential identity")
        return cls(
            root=data_dir / "model-source-admission", model=model, credential=credential, wait_seconds=wait_seconds
        )

    def _active(self) -> int:
        active = 0
        for i in range(self.cap):
            probe = _NativeLock(self.group / f"slot-{i}.lock")
            try:
                probe.acquire(timeout=0)
            except _SlotBusy:
                active += 1
            else:
                probe.release()
        return active

    def _record(self, event: str, *, active: int, headers: Mapping[str, str] | None = None) -> None:
        data: dict[str, str | int | None | dict[str, str]] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "request_id": self.request_id,
            "model": self.model,
            "active": active,
            "cap": self.cap,
            "status": self.status,
            "outcome": self.outcome,
        }
        if headers is not None:
            data["rate_headers"] = safe_rate_headers(headers)
        # One lock for the bounded metadata log; it contains no prompt/body/key/URL.
        with _NativeLock(self.root / "events.lock"):
            target = self.root / "events.jsonl"
            if target.exists() and target.stat().st_size >= _MAX_EVENTS_BYTES:
                target.replace(self.root / "events.previous.jsonl")
            with target.open("a", encoding="utf-8") as out:
                out.write(json.dumps(data, separators=(",", ":")) + "\n")

    def _acquire_slot(self) -> bool:
        guard = _NativeLock(self.group / "admission.lock")
        with guard:
            for i in range(self.cap):
                slot = _NativeLock(self.group / f"slot-{i}.lock")
                try:
                    slot.acquire()
                except _SlotBusy:
                    continue
                self.slot = slot
                try:
                    self._record("admitted", active=self._active())
                except BaseException:
                    self.slot.release()
                    self.slot = None
                    raise
                return True
        return False

    async def __aenter__(self) -> ModelSourceAdmission:
        try:
            self.group.mkdir(parents=True, mode=0o700, exist_ok=True)
        except OSError as exc:
            raise ModelSourceAdmissionError("GLM request admission store unavailable") from exc
        deadline = time.monotonic() + self.wait_seconds
        while True:
            try:
                if self._acquire_slot():
                    return self
            except _SlotBusy:
                # Guard and telemetry contention share the same async deadline.
                pass
            except OSError as exc:
                raise ModelSourceAdmissionError("GLM request admission store unavailable") from exc
            if time.monotonic() >= deadline:
                raise ModelSourceAdmissionError("GLM request admission timeout")
            await asyncio.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def mark_body_received(self, *, streaming: bool = False) -> None:
        # This records a consumed transport body, never task/human acceptance.
        self.outcome = "stream_eof" if streaming else "body_received"

    def observe_response(self, status: int, headers: Mapping[str, str]) -> None:
        if self._response_seen:
            return
        self._response_seen = True
        self.status = status
        try:
            self._record("response", active=self._active(), headers=headers)
        except (OSError, _SlotBusy):
            # A provider request already occurred. Do not turn missing telemetry into
            # a retry; the warning makes the natural-window receipt incomplete.
            logger.warning("GLM admission response telemetry unavailable; window proof incomplete")

    async def __aexit__(self, *_exc: object) -> None:
        if self.slot is None:
            return
        slot, self.slot = self.slot, None
        # Slot release itself cannot be cancelled and must survive telemetry failure.
        slot.release()
        try:
            self._record("released", active=self._active())
        except (OSError, _SlotBusy):
            logger.warning("GLM admission release telemetry unavailable; window proof incomplete")
