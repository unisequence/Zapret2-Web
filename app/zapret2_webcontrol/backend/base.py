from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ..strategies import CompilationResult, Strategy


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """Stable platform capability contract exposed to the frontend."""

    platform: str
    backend: str
    display_name: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    service: str
    running: bool
    pid: int | None
    executable: str | None
    checked_at: str
    control_mode: str

    @classmethod
    def checked_now(
        cls,
        *,
        service: str,
        running: bool,
        pid: int | None,
        executable: str | None,
        control_mode: str,
    ) -> "RuntimeStatus":
        return cls(
            service=service,
            running=running,
            pid=pid,
            executable=executable,
            checked_at=datetime.now(timezone.utc).isoformat(),
            control_mode=control_mode,
        )


class Backend(Protocol):
    def info(self) -> BackendInfo:
        """Return platform identity and supported operations."""

    def status(self) -> RuntimeStatus:
        """Return the current runtime status without changing system state."""

    def strategies(self) -> tuple[Strategy, ...]:
        """Return the normalized strategy catalog for this platform."""

    def strategy_preview(self) -> CompilationResult:
        """Compile the catalog without starting a process or changing the OS."""

    def create_strategy(self, payload: object) -> Strategy:
        """Create and persist a user strategy."""

    def delete_strategy(self, strategy_id: str) -> Strategy:
        """Delete a user strategy while preserving the reference catalog."""

    def start(self) -> RuntimeStatus:
        """Start the platform process after an explicit API-level confirmation."""

    def stop(self) -> RuntimeStatus:
        """Stop only a process managed by this backend instance."""
