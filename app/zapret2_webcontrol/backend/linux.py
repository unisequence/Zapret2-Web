from __future__ import annotations

import os
import shutil
from pathlib import Path

from .base import BackendInfo, RuntimeStatus
from ..list_store import ListDocument, ListInfo, ListStore
from ..strategies import CompilationResult, LinuxStrategyCompiler, Strategy, default_strategies
from ..strategy_store import StrategyStore


class LinuxBackend:
    """Safe Linux adapter for catalog editing and nfqws2 command previews.

    Process control remains disabled until this backend can apply and roll back
    the matching nftables/iptables NFQUEUE rules.  Starting nfqws2 without that
    layer would report success while doing no useful work.
    """

    PROCESS_NAME = "nfqws2"

    def __init__(
        self,
        install_dir: str | os.PathLike[str] | None = None,
        strategy_store_path: str | os.PathLike[str] | None = None,
    ) -> None:
        configured = install_dir or os.environ.get("ZAPRET2_DIR") or "/opt/zapret2"
        self.install_dir = Path(configured)
        store_path = (
            Path(strategy_store_path)
            if strategy_store_path
            else self.project_dir / "runtime" / "config" / "strategies.json"
        )
        self._strategy_store = StrategyStore(store_path)
        self._list_store = ListStore(
            self.lists_dir,
            bundled_youtube=self.install_dir / "ipset" / "zapret_hosts_youtube.txt",
        )

    @property
    def project_dir(self) -> Path:
        return Path(__file__).resolve().parents[3]

    @property
    def lists_dir(self) -> Path:
        return self.project_dir / "runtime" / "lists"

    @property
    def runtime_blobs_dir(self) -> Path:
        return self.project_dir / "runtime" / "blobs"

    @property
    def runtime_log_path(self) -> Path:
        return self.project_dir / "runtime" / "logs" / "nfqws2.log"

    def info(self) -> BackendInfo:
        return BackendInfo(
            platform="linux",
            backend="linux-preview",
            display_name="Linux / nfqws2 (предпросмотр)",
            capabilities=(
                "executable_discovery",
                "process_status",
                "strategy_catalog",
                "strategy_preview",
                "strategy_editing",
                "strategy_persistence",
                "list_editing",
                "runtime_logs",
            ),
        )

    def find_executable(self) -> Path | None:
        candidate = self.install_dir / "nfq2" / self.PROCESS_NAME
        if candidate.is_file():
            return candidate
        on_path = shutil.which(self.PROCESS_NAME)
        return Path(on_path) if on_path else None

    def status(self) -> RuntimeStatus:
        running, pid = self._find_process()
        executable = self.find_executable()
        return RuntimeStatus.checked_now(
            service=self.PROCESS_NAME,
            running=running,
            pid=pid,
            executable=str(executable) if executable else None,
            control_mode="read_only",
        )

    @staticmethod
    def _find_process() -> tuple[bool, int | None]:
        proc = Path("/proc")
        if not proc.is_dir():
            return False, None
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                name = (entry / "comm").read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                continue
            if name == LinuxBackend.PROCESS_NAME:
                return True, int(entry.name)
        return False, None

    def strategies(self) -> tuple[Strategy, ...]:
        return self._strategy_store.apply(default_strategies())

    def update_strategy(self, strategy_id: str, patch: dict) -> Strategy:
        if self.status().running:
            raise RuntimeError("Нельзя менять стратегии, пока nfqws2 запущен")
        return self._strategy_store.update(default_strategies(), strategy_id, patch)

    def create_strategy(self, payload: object) -> Strategy:
        if self.status().running:
            raise RuntimeError("Нельзя добавлять стратегии, пока nfqws2 запущен")
        return self._strategy_store.create(default_strategies(), payload)

    def delete_strategy(self, strategy_id: str) -> Strategy:
        if self.status().running:
            raise RuntimeError("Нельзя удалять стратегии, пока nfqws2 запущен")
        return self._strategy_store.delete(default_strategies(), strategy_id)

    def reset_strategies(self) -> tuple[Strategy, ...]:
        if self.status().running:
            raise RuntimeError("Нельзя сбросить стратегии, пока nfqws2 запущен")
        self._strategy_store.reset()
        return self.strategies()

    def strategy_preview(self) -> CompilationResult:
        compiler = LinuxStrategyCompiler(
            executable=self.find_executable(),
            lua_dir=self.install_dir / "lua",
            files_dir=self.install_dir / "files" / "fake",
            lists_dir=self.lists_dir,
            blob_dirs=(self.runtime_blobs_dir, self.install_dir / "files" / "fake"),
        )
        return compiler.compile(self.strategies())

    def lists(self) -> tuple[ListInfo, ...]:
        return self._list_store.list()

    def read_list(self, list_id: str) -> ListDocument:
        return self._list_store.read(list_id)

    def update_list(self, list_id: str, content: object) -> ListDocument:
        if self.status().running:
            raise RuntimeError("Нельзя менять списки, пока nfqws2 запущен")
        return self._list_store.update(list_id, content)

    def runtime_log(self, *, max_bytes: int = 200_000) -> dict:
        path = self.runtime_log_path
        if not path.is_file():
            return {"path": str(path), "content": "", "truncated": False}
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, 2)
            content = handle.read().decode("utf-8", errors="replace")
        return {"path": str(path), "content": content, "truncated": size > max_bytes}

    def clear_runtime_log(self) -> dict:
        self.runtime_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_log_path.write_bytes(b"")
        return self.runtime_log()

    def blockcheck_status(self) -> dict:
        return {
            "available": False,
            "running": False,
            "pid": None,
            "started_at": None,
            "exit_code": None,
            "tests": [],
        }

    def blockcheck_log(self, *, max_bytes: int = 500_000) -> dict:
        return {"path": "", "content": "Linux Blockcheck2 ещё не подключён.", "truncated": False}

    def start_blockcheck(self, options: object) -> dict:
        raise RuntimeError("Linux Blockcheck2 ещё не подключён")

    def stop_blockcheck(self) -> dict:
        raise RuntimeError("Linux Blockcheck2 не запущен панелью")

    def autostart_status(self) -> dict:
        return {
            "service": "zapret2",
            "installed": False,
            "running": False,
            "state": None,
            "automatic": False,
            "image_path": None,
            "expected_image_path": None,
            "in_sync": False,
            "can_manage": False,
            "warnings": ["Linux service/firewall adapter ещё не подключён."],
        }

    def install_autostart(self) -> dict:
        raise RuntimeError("Linux service/firewall adapter ещё не подключён")

    def remove_autostart(self) -> dict:
        raise RuntimeError("Linux service/firewall adapter ещё не подключён")

    def start(self) -> RuntimeStatus:
        raise RuntimeError(
            "Linux-запуск отключён до реализации атомарной настройки NFQUEUE и firewall"
        )

    def stop(self) -> RuntimeStatus:
        raise RuntimeError("Linux-процесс не запускался этой панелью")
