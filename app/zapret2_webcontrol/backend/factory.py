from __future__ import annotations

import platform

from .base import Backend


def create_backend(platform_name: str | None = None) -> Backend:
    """Create a backend without importing OS-specific modules prematurely."""
    detected = platform_name or platform.system()
    if detected == "Windows":
        from .windows import WindowsBackend

        return WindowsBackend()
    if detected == "Linux":
        from .linux import LinuxBackend

        return LinuxBackend()
    raise RuntimeError(f"Неподдерживаемая платформа: {detected}")
