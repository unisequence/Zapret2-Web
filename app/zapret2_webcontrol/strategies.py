from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .strategy_catalog import REFERENCE_STRATEGIES


@dataclass(frozen=True, slots=True)
class Strategy:
    """Platform-neutral strategy profile.

    The profile contains the matching and Lua action data shared by zapret2
    implementations. A backend is responsible for compiling interception and
    service-management details for its operating system.
    """

    id: str
    name: str
    enabled: bool
    protocol: str
    ports: tuple[str, ...]
    filter_l7: tuple[str, ...]
    hostlist: str | None
    payload: str | None
    lua_desync: tuple[str, ...]
    filter_l3: tuple[str, ...] = ("ipv4",)
    range_filters: tuple[str, ...] = ()
    ordered_options: tuple[str, ...] = ()
    unsupported_options: tuple[str, ...] = ()
    hostlist_exclude: tuple[str, ...] = ()
    notes: str = ""
    source: str = "windows-adapted"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CompilationResult:
    command: tuple[str, ...]
    command_line: str
    active_strategy_ids: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def default_strategies() -> tuple[Strategy, ...]:
    """All LuCI reference profiles normalized for a shared strategy model."""
    result: list[Strategy] = []
    for spec in REFERENCE_STRATEGIES:
        options = tuple(shlex.split(spec.script))
        payload_option = next(
            (item for item in options if item.startswith("--payload=")),
            None,
        )
        result.append(
            Strategy(
                id=_slugify(spec.name),
                name=spec.name,
                enabled=spec.enabled,
                protocol=spec.protocol,
                ports=spec.ports,
                filter_l7=spec.filter_l7,
                hostlist=spec.hostlist,
                payload=(
                    payload_option.removeprefix("--payload=")
                    if payload_option
                    else None
                ),
                lua_desync=tuple(
                    item.removeprefix("--lua-desync=")
                    for item in options
                    if item.startswith("--lua-desync=")
                ),
                range_filters=tuple(
                    item
                    for item in options
                    if item.startswith(("--in-range=", "--out-range="))
                ),
                ordered_options=options,
                notes=(
                    "Включена в эталонной LuCI-конфигурации."
                    if spec.enabled
                    else "Сохранённый выключенный вариант из LuCI."
                ),
                source="router-reference",
            )
        )
    return tuple(result)


class WindowsStrategyCompiler:
    """Compile normalized profiles into a safe winws2 command preview."""

    def __init__(
        self,
        *,
        executable: Path | None,
        lua_dir: Path | None,
        files_dir: Path | None,
        lists_dir: Path,
        raw_filter_dir: Path | None = None,
        blob_dirs: tuple[Path, ...] = (),
    ) -> None:
        self.executable = executable
        self.lua_dir = lua_dir
        self.files_dir = files_dir
        self.lists_dir = lists_dir
        self.raw_filter_dir = raw_filter_dir
        self.blob_dirs = blob_dirs or ((files_dir,) if files_dir else ())

    def compile(self, strategies: Iterable[Strategy]) -> CompilationResult:
        active = tuple(strategy for strategy in strategies if strategy.enabled)
        warnings: list[str] = []
        command: list[str] = [str(self.executable) if self.executable else "winws2.exe"]

        if self.executable is None:
            warnings.append("winws2.exe не найден; показана команда-шаблон.")

        command.append("--wf-l3=ipv4")
        tcp_ports = _merge_ports(active, "tcp")
        udp_ports = _merge_ports(active, "udp")
        if tcp_ports:
            command.append(f"--wf-tcp-out={','.join(tcp_ports)}")
        if udp_ports:
            command.append(f"--wf-udp-out={','.join(udp_ports)}")
        tcp_in = _merge_inbound_ports(active, "tcp")
        udp_in = _merge_inbound_ports(active, "udp")
        if tcp_in:
            command.append(f"--wf-tcp-in={','.join(tcp_in)}")
        if udp_in:
            command.append(f"--wf-udp-in={','.join(udp_in)}")
        self._append_capture_filters(active, command, warnings)

        for lua_name in ("zapret-lib.lua", "zapret-antidpi.lua", "zapret-auto.lua"):
            lua_path = self.lua_dir / lua_name if self.lua_dir else None
            if lua_path and lua_path.is_file():
                command.append(f"--lua-init=@{lua_path}")
            else:
                warnings.append(f"Lua-библиотека не найдена: {lua_name}")
        self._append_external_blobs(active, command, warnings)

        if not active:
            warnings.append("Нет включённых стратегий.")

        for index, strategy in enumerate(active):
            command.extend(self._compile_profile(strategy, warnings))
            if index < len(active) - 1:
                command.append("--new")

        return CompilationResult(
            command=tuple(command),
            command_line=subprocess.list2cmdline(command),
            active_strategy_ids=tuple(strategy.id for strategy in active),
            warnings=tuple(warnings),
        )

    def _compile_profile(self, strategy: Strategy, warnings: list[str]) -> list[str]:
        args: list[str] = []
        for option in strategy.unsupported_options:
            warnings.append(f"Не перенесён параметр {strategy.name}: {option}")
        filter_option = "--filter-tcp" if strategy.protocol == "tcp" else "--filter-udp"
        if strategy.ports:
            args.append(f"{filter_option}={','.join(strategy.ports)}")
        else:
            warnings.append(f"У стратегии нет портов: {strategy.name}")
        if strategy.filter_l3:
            args.append(f"--filter-l3={','.join(strategy.filter_l3)}")
        if strategy.filter_l7:
            args.append(f"--filter-l7={','.join(strategy.filter_l7)}")
        if strategy.hostlist:
            hostlist_path = self._hostlist_path(strategy.hostlist)
            args.append(f"--hostlist={hostlist_path}")
            if not hostlist_path.is_file():
                warnings.append(
                    f"Hostlist не найден для {strategy.name}: {hostlist_path}"
                )
        for excluded in strategy.hostlist_exclude:
            excluded_path = self._hostlist_path(excluded)
            args.append(f"--hostlist-exclude={excluded_path}")
            if not excluded_path.is_file():
                warnings.append(
                    f"Hostlist-исключение не найдено для {strategy.name}: {excluded_path}"
                )
        steps = strategy.ordered_options or (
            ((f"--payload={strategy.payload}",) if strategy.payload else ())
            + strategy.range_filters
            + tuple(f"--lua-desync={item}" for item in strategy.lua_desync)
        )
        args.extend(steps)
        return args

    def _append_capture_filters(
        self,
        active: tuple[Strategy, ...],
        command: list[str],
        warnings: list[str],
    ) -> None:
        if not any(strategy.id == "discord_udp" for strategy in active):
            return
        for filename in (
            "windivert_part.discord_media.txt",
            "windivert_part.stun.txt",
        ):
            path = self.raw_filter_dir / filename if self.raw_filter_dir else None
            if path and path.is_file():
                command.append(f"--wf-raw-part=@{path}")
            else:
                warnings.append(f"WinDivert-фильтр не найден: {filename}")

    def _append_external_blobs(
        self,
        active: tuple[Strategy, ...],
        command: list[str],
        warnings: list[str],
    ) -> None:
        names: list[str] = []
        for strategy in active:
            for step in _strategy_steps(strategy):
                for name in _external_blob_names(step):
                    if name not in names:
                        names.append(name)
        for name in names:
            path = self._blob_path(name)
            if path:
                command.append(f"--blob={name}:@{path}")
            else:
                warnings.append(
                    f"Blob не найден: {name}. Профили, которые его используют, "
                    "не готовы к запуску."
                )

    def _blob_path(self, name: str) -> Path | None:
        filename = f"{name.removeprefix('blob_')}.bin"
        for directory in self.blob_dirs:
            candidate = directory / filename
            if candidate.is_file():
                return candidate
        return None

    def _hostlist_path(self, name: str) -> Path:
        known_names = {
            "discord": "zapret_hosts_discord.txt",
            "youtube": "zapret_hosts_youtube.txt",
        }
        candidate = self.lists_dir / known_names.get(name, name)
        if candidate.is_file():
            return candidate

        # The official Windows bundle ships the YouTube list beside `files`.
        # Keep project-managed lists higher priority, then use that read-only
        # bundle asset as a safe fallback for the first-run preview.
        if name == "youtube" and self.files_dir:
            bundled = self.files_dir / "list-youtube.txt"
            if bundled.is_file():
                return bundled
        return candidate


class LinuxStrategyCompiler(WindowsStrategyCompiler):
    """Compile shared profiles into an nfqws2 preview.

    Firewall/NFQUEUE setup intentionally stays outside this compiler.  The
    preview is useful for validation and for a future Linux service adapter,
    but running the command alone would not intercept any packets.
    """

    def __init__(
        self,
        *,
        executable: Path | None,
        lua_dir: Path | None,
        files_dir: Path | None,
        lists_dir: Path,
        blob_dirs: tuple[Path, ...] = (),
        queue_num: int = 300,
    ) -> None:
        super().__init__(
            executable=executable,
            lua_dir=lua_dir,
            files_dir=files_dir,
            lists_dir=lists_dir,
            blob_dirs=blob_dirs,
        )
        if not 1 <= queue_num <= 65535:
            raise ValueError("Номер NFQUEUE должен быть в диапазоне 1–65535")
        self.queue_num = queue_num

    def compile(self, strategies: Iterable[Strategy]) -> CompilationResult:
        active = tuple(strategy for strategy in strategies if strategy.enabled)
        warnings: list[str] = []
        command: list[str] = [str(self.executable) if self.executable else "nfqws2"]

        if self.executable is None:
            warnings.append("nfqws2 не найден; показана команда-шаблон.")
        command.append(f"--qnum={self.queue_num}")

        for lua_name in ("zapret-lib.lua", "zapret-antidpi.lua", "zapret-auto.lua"):
            lua_path = self.lua_dir / lua_name if self.lua_dir else None
            if lua_path and lua_path.is_file():
                command.append(f"--lua-init=@{lua_path}")
            else:
                warnings.append(f"Lua-библиотека не найдена: {lua_name}")
        self._append_external_blobs(active, command, warnings)

        if not active:
            warnings.append("Нет включённых стратегий.")
        for index, strategy in enumerate(active):
            command.extend(self._compile_profile(strategy, warnings))
            if index < len(active) - 1:
                command.append("--new")

        return CompilationResult(
            command=tuple(command),
            command_line=shlex.join(command),
            active_strategy_ids=tuple(strategy.id for strategy in active),
            warnings=tuple(warnings),
        )


def _merge_ports(strategies: Iterable[Strategy], protocol: str) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for strategy in strategies:
        if strategy.protocol != protocol:
            continue
        for port in strategy.ports:
            if port not in seen:
                seen.add(port)
                result.append(port)
    return tuple(result)


def _merge_inbound_ports(strategies: Iterable[Strategy], protocol: str) -> tuple[str, ...]:
    return _merge_ports(
        (
            strategy for strategy in strategies
            if any(option.startswith("--in-range=") for option in strategy.ordered_options or strategy.range_filters)
        ),
        protocol,
    )


def _strategy_steps(strategy: Strategy) -> tuple[str, ...]:
    return strategy.ordered_options or (
        ((f"--payload={strategy.payload}",) if strategy.payload else ())
        + strategy.range_filters
        + tuple(f"--lua-desync={item}" for item in strategy.lua_desync)
    )


def _external_blob_names(step: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in re.findall(r"(?:^|:)(?:blob|pattern|seqovl_pattern)=([^:]+)", step):
        if value.startswith("blob_") or value == "quic_initial_www_google_com":
            if value not in result:
                result.append(value)
    return tuple(result)


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "strategy"
