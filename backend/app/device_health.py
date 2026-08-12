"""Lightweight, mission-independent device readiness probes."""

from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal


HealthState = Literal["ready", "offline", "unknown"]
OFFLINE_DELAYS = (5.0, 10.0, 20.0, 30.0)
READY_DELAY = 10.0


@dataclass(frozen=True)
class HealthResult:
    device: str
    state: HealthState
    checked_at: float
    error: str = ""
    stale: bool = False
    next_check_at: float | None = None
    retry_delay: float | None = None

    def as_dict(self) -> dict[str, Any]:
        checked = datetime.fromtimestamp(self.checked_at, timezone.utc).isoformat()
        next_check = (
            datetime.fromtimestamp(self.next_check_at, timezone.utc).isoformat()
            if self.next_check_at is not None
            else None
        )
        return {
            "device": self.device,
            "state": self.state,
            "checked_at": checked,
            "last_checked_at": checked,
            "next_check_at": next_check,
            "retry_delay": self.retry_delay,
            "stale": self.stale,
            "error": self.error,
        }


class HealthProbeError(RuntimeError):
    pass


def _coerce_result(value: Any, device: str, now: float) -> HealthResult:
    if isinstance(value, HealthResult):
        return replace(value, device=device, checked_at=now)
    if isinstance(value, bool):
        return HealthResult(device, "ready" if value else "offline", now, "" if value else f"{device} unavailable")
    if isinstance(value, dict):
        state = value.get("state")
        if state not in {"ready", "offline", "unknown"}:
            state = "ready" if value.get("success", True) else "offline"
        return HealthResult(
            device,
            state,
            now,
            str(value.get("error") or value.get("message") or ""),
            bool(value.get("stale", False)),
        )
    raise HealthProbeError(f"{device} probe returned an invalid result")


class Ap3Health:
    """Check only ADB authorization and MAVLink forwarding readiness."""

    def __init__(
        self,
        *,
        adb: str | Path | None = None,
        run: Callable[..., Any] = subprocess.run,
        probe: Callable[[], Any] | None = None,
        local_port: int = 15760,
        remote_port: int = 5760,
        timeout: float = 3.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.adb = str(adb) if adb is not None else "adb"
        self.run = run
        self.probe = probe
        self.local_port = local_port
        self.remote_port = remote_port
        self.timeout = timeout
        self.clock = clock

    def check(self) -> HealthResult:
        now = self.clock()
        if self.probe is not None:
            try:
                return _coerce_result(self.probe(), "ap3", now)
            except Exception as exc:
                return HealthResult("ap3", "offline", now, f"AP3 probe failed: {exc}")
        try:
            devices = self.run(
                [self.adb, "devices"],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
            if devices.returncode != 0:
                raise HealthProbeError((devices.stderr or devices.stdout or "ADB device check failed").strip())
            authorized = any(
                line.strip().endswith("\tdevice")
                for line in (devices.stdout or "").splitlines()[1:]
            )
            if not authorized:
                return HealthResult("ap3", "offline", now, "AP3 ADB device is not authorized or connected")
            forwarded = self.run(
                [self.adb, "forward", f"tcp:{self.local_port}", f"tcp:{self.remote_port}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
            if forwarded.returncode != 0:
                raise HealthProbeError((forwarded.stderr or forwarded.stdout or "AP3 forwarding is unavailable").strip())
            return HealthResult("ap3", "ready", now)
        except (subprocess.TimeoutExpired, TimeoutError) as exc:
            return HealthResult("ap3", "unknown", now, f"AP3 health timeout: {exc}", stale=True)
        except Exception as exc:
            if "timeout" in str(exc).lower():
                return HealthResult("ap3", "unknown", now, f"AP3 health timeout: {exc}", stale=True)
            return HealthResult("ap3", "offline", now, f"AP3 unavailable: {exc}")


class RaspiHealth:
    """Bounded SSH + service-state probe; diagnostics are deliberately excluded."""

    def __init__(
        self,
        *,
        mode: str = "test",
        probe: Callable[[], Any] | None = None,
        timeout: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.mode = mode
        self.probe = probe
        self.timeout = timeout
        self.clock = clock

    def check(self) -> HealthResult:
        now = self.clock()
        try:
            probe = self.probe
            if probe is None:
                from app import usrp_ctl

                probe = lambda: usrp_ctl.get_drone_health(self.mode)
            return _coerce_result(probe(), "raspi", now)
        except (subprocess.TimeoutExpired, TimeoutError) as exc:
            return HealthResult("raspi", "unknown", now, f"Raspberry Pi health timeout: {exc}", stale=True)
        except Exception as exc:
            if "timeout" in str(exc).lower():
                return HealthResult("raspi", "unknown", now, f"Raspberry Pi health timeout: {exc}", stale=True)
            return HealthResult("raspi", "offline", now, f"Raspberry Pi unavailable: {exc}")


class DeviceHealthMonitor:
    def __init__(
        self,
        *,
        ap3: Any | None = None,
        raspi: Any | None = None,
        clock: Callable[[], float] = time.time,
        timeout: float = 5.0,
    ) -> None:
        self.clock = clock
        self.timeout = timeout
        self.adapters = {
            "ap3": ap3 or Ap3Health(clock=clock),
            "raspi": raspi or RaspiHealth(clock=clock),
        }
        self._results: dict[str, HealthResult] = {}
        self._next: dict[str, float] = {}
        self._failures: dict[str, int] = {name: 0 for name in self.adapters}
        self._mode: str | None = None

    def _check(self, name: str, adapter: Any, now: float) -> HealthResult:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(adapter.check)
        try:
            value = future.result(timeout=self.timeout)
            result = _coerce_result(value, name, now)
        except FutureTimeout:
            future.cancel()
            result = HealthResult(name, "unknown", now, f"{name} health probe timeout", stale=True)
        except Exception as exc:
            result = HealthResult(name, "offline", now, f"{name} health probe failed: {exc}")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return result

    def poll(self, *, force: bool = False, mode: str | None = None) -> dict[str, HealthResult]:
        if mode is not None and mode != self._mode:
            self._mode = mode
            self._results.pop("raspi", None)
            self._next.pop("raspi", None)
            self._failures["raspi"] = 0
        now = self.clock()
        for name, adapter in self.adapters.items():
            if not force and name in self._next and now < self._next[name]:
                continue
            result = self._check(name, adapter, now)
            if result.state == "ready" and not result.stale:
                self._failures[name] = 0
                delay = READY_DELAY
            else:
                delay = OFFLINE_DELAYS[min(self._failures[name], len(OFFLINE_DELAYS) - 1)]
                self._failures[name] = min(self._failures[name] + 1, len(OFFLINE_DELAYS) - 1)
            result = replace(result, next_check_at=now + delay, retry_delay=delay)
            self._results[name] = result
            self._next[name] = now + delay
        return self.snapshot()

    def snapshot(self) -> dict[str, HealthResult]:
        now = self.clock()
        snapshot: dict[str, HealthResult] = {}
        for name, result in self._results.items():
            if result.state == "ready" and self._next.get(name, now + READY_DELAY) <= now:
                snapshot[name] = replace(
                    result,
                    state="unknown",
                    stale=True,
                    error=f"{name} health result is stale",
                )
            else:
                snapshot[name] = result
        return snapshot

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {name: result.as_dict() for name, result in self.snapshot().items()}
