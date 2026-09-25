from __future__ import annotations

import csv
import ctypes
import io
import os
import re
import signal
import shutil
import subprocess
import winreg
from datetime import datetime, timezone
from pathlib import Path

from .base import BackendInfo, RuntimeStatus
from ..strategies import CompilationResult, Strategy, WindowsStrategyCompiler, default_strategies
from ..strategy_store import StrategyStore
from ..list_store import ListDocument, ListInfo, ListStore


class WindowsBackend:
    """Windows adapter for winws2, WinDivert and strategy compilation."""

    PROCESS_NAME = "winws2.exe"
    SERVICE_NAME = "zapret2-webcontrol"
    SERVICE_DISPLAY_NAME = "Zapret2 WebControl"
    PANEL_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    PANEL_RUN_NAME = "Zapret2 WebControl Panel"

    @property
    def project_dir(self) -> Path:
        return Path(__file__).resolve().parents[3]

    @property
    def project_bundle_dir(self) -> Path:
        return self.project_dir / "vendor" / "zapret-win-bundle" / "zapret-winws"

    @property
    def project_bundle_executable(self) -> Path:
        return self.project_bundle_dir / self.PROCESS_NAME

    @property
    def project_bundle_lua_dir(self) -> Path:
        return self.project_bundle_dir / "lua"

    @property
    def project_bundle_files_dir(self) -> Path:
        return self.project_bundle_dir / "files"

    @property
    def project_bundle_raw_filter_dir(self) -> Path:
        return self.project_bundle_dir / "windivert.filter"

    @property
    def project_bundle_legacy_blob_dir(self) -> Path:
        return (
            self.project_dir
            / "vendor"
            / "zapret-win-bundle"
            / "blockcheck"
            / "zapret"
            / "files"
            / "fake"
        )

    @property
    def runtime_blobs_dir(self) -> Path:
        return self.project_dir / "runtime" / "blobs"

    @property
    def lists_dir(self) -> Path:
        return self.project_dir / "runtime" / "lists"

    @property
    def runtime_log_path(self) -> Path:
        return self.project_dir / "runtime" / "logs" / "winws2.log"

    @property
    def blockcheck_root(self) -> Path:
        return self.project_dir / "vendor" / "zapret-win-bundle" / "blockcheck"

    @property
    def blockcheck_script(self) -> Path:
        return self.blockcheck_root / "zapret2" / "blockcheck2.sh"

    @property
    def blockcheck_bash(self) -> Path:
        return self.blockcheck_root / ".." / "cygwin" / "bin" / "bash.exe"

    @property
    def blockcheck_cygpath(self) -> Path:
        return self.blockcheck_root / ".." / "cygwin" / "bin" / "cygpath.exe"

    @property
    def blockcheck_log_path(self) -> Path:
        return self.project_dir / "runtime" / "logs" / "blockcheck2.log"

    @property
    def legacy_blockcheck_executable(self) -> Path:
        project_dir = Path(__file__).resolve().parents[3]
        return (
            project_dir
            / "vendor"
            / "zapret-win-bundle"
            / "blockcheck"
            / "zapret2"
            / "nfq2"
            / self.PROCESS_NAME
        )

    def __init__(
        self,
        install_dir: str | os.PathLike[str] | None = None,
        strategy_store_path: str | os.PathLike[str] | None = None,
    ) -> None:
        configured_dir = install_dir or os.environ.get("ZAPRET2_DIR")
        self.install_dir = Path(configured_dir) if configured_dir else None
        self._managed_process: subprocess.Popen | None = None
        self._log_handle = None
        self._blockcheck_process: subprocess.Popen | None = None
        self._blockcheck_log_handle = None
        self._blockcheck_started_at: str | None = None
        self._blockcheck_exit_code: int | None = None
        store_path = (
            Path(strategy_store_path)
            if strategy_store_path
            else self.project_dir / "runtime" / "config" / "strategies.json"
        )
        self._strategy_store = StrategyStore(store_path)
        self._list_store = ListStore(
            self.lists_dir,
            bundled_youtube=self.project_bundle_files_dir / "list-youtube.txt",
        )

    def info(self) -> BackendInfo:
        return BackendInfo(
            platform="windows",
            backend="windows",
            display_name="Windows / winws2",
            capabilities=(
                "executable_discovery",
                "process_status",
                "strategy_catalog",
                "strategy_preview",
                "strategy_editing",
                "strategy_persistence",
                "list_editing",
                "runtime_logs",
                "blockcheck2",
                "windows_service",
                "panel_autostart",
                "windivert_capture",
                "process_control",
            ),
        )

    def find_executable(self) -> Path | None:
        if self.install_dir:
            candidate = self.install_dir / self.PROCESS_NAME
            if candidate.is_file():
                return candidate

        bundled = self.project_bundle_executable
        if bundled.is_file():
            return bundled

        legacy_bundle = self.legacy_blockcheck_executable
        if legacy_bundle.is_file():
            return legacy_bundle

        on_path = shutil.which(self.PROCESS_NAME)
        return Path(on_path) if on_path else None

    def status(self) -> RuntimeStatus:
        executable = self.find_executable()
        running, pid = self._find_process()
        service = self.autostart_status()
        managed = self._managed_process
        if managed is not None and managed.poll() is not None:
            self._managed_process = None
            self._close_log()
            managed = None
        if service["running"]:
            control_mode = "service"
            running = True
        else:
            control_mode = "managed" if managed is not None and running else "read_only"
        return RuntimeStatus.checked_now(
            service="winws2",
            running=running,
            pid=pid,
            executable=str(executable) if executable else None,
            control_mode=control_mode,
        )

    def _find_process(self) -> tuple[bool, int | None]:
        """Use tasklist instead of PowerShell so the adapter stays self-contained."""
        try:
            result = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    f"IMAGENAME eq {self.PROCESS_NAME}",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            return False, None

        if result.returncode != 0:
            return False, None

        rows = list(csv.reader(io.StringIO(result.stdout)))
        for row in rows:
            if len(row) >= 2 and row[0].lower() == self.PROCESS_NAME.lower():
                try:
                    return True, int(row[1])
                except ValueError:
                    return True, None
        return False, None

    def strategies(self) -> tuple[Strategy, ...]:
        return self._strategy_store.apply(default_strategies())

    def update_strategy(self, strategy_id: str, patch: dict) -> Strategy:
        if self.status().running:
            raise RuntimeError("Нельзя менять стратегии во время работы winws2")
        return self._strategy_store.update(default_strategies(), strategy_id, patch)

    def create_strategy(self, payload: object) -> Strategy:
        if self.status().running:
            raise RuntimeError("Нельзя добавлять стратегии во время работы winws2")
        return self._strategy_store.create(default_strategies(), payload)

    def delete_strategy(self, strategy_id: str) -> Strategy:
        if self.status().running:
            raise RuntimeError("Нельзя удалять стратегии во время работы winws2")
        return self._strategy_store.delete(default_strategies(), strategy_id)

    def reset_strategies(self) -> tuple[Strategy, ...]:
        if self.status().running:
            raise RuntimeError("Нельзя сбрасывать стратегии во время работы winws2")
        self._strategy_store.reset()
        return self.strategies()

    def lists(self) -> tuple[ListInfo, ...]:
        return self._list_store.infos()

    def read_list(self, list_id: str) -> ListDocument:
        return self._list_store.read(list_id)

    def update_list(self, list_id: str, content: object) -> ListDocument:
        if self.status().running:
            raise RuntimeError("Нельзя менять списки во время работы winws2")
        return self._list_store.update(list_id, content)

    def runtime_log(self, *, max_bytes: int = 200_000) -> dict:
        return self._tail_log(self.runtime_log_path, max_bytes=max_bytes)

    @staticmethod
    def _tail_log(path: Path, *, max_bytes: int = 200_000) -> dict:
        if not path.is_file():
            return {"path": str(path), "content": "", "truncated": False}
        size = path.stat().st_size
        with path.open("rb") as stream:
            if size > max_bytes:
                stream.seek(-max_bytes, os.SEEK_END)
            data = stream.read()
        return {
            "path": str(path),
            "content": data.decode("utf-8", errors="replace"),
            "truncated": size > max_bytes,
        }

    def blockcheck_status(self) -> dict:
        process = self._blockcheck_process
        if process is not None:
            exit_code = process.poll()
            if exit_code is not None:
                self._blockcheck_exit_code = exit_code
                self._blockcheck_process = None
                self._close_blockcheck_log()
                process = None
        return {
            "available": (
                self.blockcheck_bash.is_file()
                and self.blockcheck_cygpath.is_file()
                and self.blockcheck_script.is_file()
            ),
            "running": process is not None,
            "pid": process.pid if process is not None else None,
            "started_at": self._blockcheck_started_at,
            "exit_code": self._blockcheck_exit_code,
            "tests": self._blockcheck_tests(),
        }

    def blockcheck_log(self, *, max_bytes: int = 500_000) -> dict:
        return self._tail_log(self.blockcheck_log_path, max_bytes=max_bytes)

    def start_blockcheck(self, options: object) -> dict:
        if self.blockcheck_status()["running"]:
            raise RuntimeError("Blockcheck2 уже запущен")
        if self.status().running:
            raise RuntimeError("Перед Blockcheck2 остановите winws2 и другие DPI bypass-процессы")
        if (
            not self.blockcheck_bash.is_file()
            or not self.blockcheck_cygpath.is_file()
            or not self.blockcheck_script.is_file()
        ):
            raise RuntimeError("Windows-бандл Blockcheck2 не найден")

        try:
            cygwin_script = subprocess.run(
                [
                    str(self.blockcheck_cygpath),
                    "-C",
                    "UTF8",
                    "-u",
                    "-a",
                    str(self.blockcheck_script),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                f"Не удалось преобразовать путь Blockcheck2 для Cygwin: {error}"
            ) from error
        if not cygwin_script.startswith("/"):
            raise RuntimeError("Cygwin вернул некорректный путь к Blockcheck2")

        settings = self._validate_blockcheck_options(options)
        environment = os.environ.copy()
        environment.update(
            {
                "BATCH": "1",
                "CHERE_INVOKING": "1",
                "DOMAINS": settings["domain"],
                "IPVS": settings["ip_version"],
                "TEST": settings["test"],
                "SCANLEVEL": settings["scan_level"],
                "REPEATS": str(settings["repeats"]),
                "PARALLEL": "1" if settings["parallel"] else "0",
                "ENABLE_HTTP": "1" if "http" in settings["protocols"] else "0",
                "ENABLE_HTTPS_TLS12": "1" if "https_tls12" in settings["protocols"] else "0",
                "ENABLE_HTTPS_TLS13": "1" if "https_tls13" in settings["protocols"] else "0",
                "ENABLE_HTTP3": "1" if "http3" in settings["protocols"] else "0",
                "SKIP_DNSCHECK": "1" if settings["skip_dns"] else "0",
                "SKIP_IPBLOCK": "1" if settings["skip_ip_block"] else "0",
                "CURL_MAX_TIME": str(settings["timeout"]),
                "CURL_MAX_TIME_QUIC": str(settings["timeout"]),
            }
        )
        self.blockcheck_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._blockcheck_log_handle = self.blockcheck_log_path.open("wb", buffering=0)
        self._blockcheck_started_at = datetime.now(timezone.utc).isoformat()
        self._blockcheck_exit_code = None
        self._blockcheck_log_handle.write(
            (
                f"[{self._blockcheck_started_at}] Starting Blockcheck2\n"
                f"Options: {settings}\n\n"
            ).encode("utf-8")
        )
        try:
            self._blockcheck_process = subprocess.Popen(
                [str(self.blockcheck_bash), "-l", cygwin_script],
                cwd=self.blockcheck_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self._blockcheck_log_handle,
                stderr=subprocess.STDOUT,
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                ),
            )
        except OSError as error:
            self._blockcheck_process = None
            self._close_blockcheck_log()
            raise RuntimeError(f"Не удалось запустить Blockcheck2: {error}") from error
        return self.blockcheck_status()

    def stop_blockcheck(self) -> dict:
        process = self._blockcheck_process
        if process is None or process.poll() is not None:
            self.blockcheck_status()
            raise RuntimeError("Blockcheck2 не запущен")
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._blockcheck_exit_code = process.returncode
        self._blockcheck_process = None
        self._close_blockcheck_log()
        return self.blockcheck_status()

    def _blockcheck_tests(self) -> tuple[str, ...]:
        directory = self.blockcheck_root / "zapret2" / "blockcheck2.d"
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.name for path in directory.iterdir() if path.is_dir()))

    def _validate_blockcheck_options(self, options: object) -> dict:
        if not isinstance(options, dict):
            raise ValueError("Параметры Blockcheck2 должны быть JSON-объектом")
        domain = options.get("domain", "rutracker.org")
        if not isinstance(domain, str) or len(domain) > 512 or not re.fullmatch(
            r"[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*)?", domain
        ):
            raise ValueError("Некорректный домен или URI для Blockcheck2")
        protocols = options.get("protocols", ["https_tls12"])
        allowed_protocols = {"http", "https_tls12", "https_tls13", "http3"}
        if (
            not isinstance(protocols, list)
            or not protocols
            or any(item not in allowed_protocols for item in protocols)
        ):
            raise ValueError("Выберите хотя бы один поддерживаемый протокол")
        repeats = options.get("repeats", 1)
        timeout = options.get("timeout", 2)
        if not isinstance(repeats, int) or isinstance(repeats, bool) or not 1 <= repeats <= 10:
            raise ValueError("Повторы должны быть целым числом от 1 до 10")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 30:
            raise ValueError("Тайм-аут должен быть целым числом от 1 до 30 секунд")
        ip_version = str(options.get("ip_version", "4"))
        if ip_version not in {"4", "6", "46"}:
            raise ValueError("IP version должна быть 4, 6 или 46")
        scan_level = options.get("scan_level", "standard")
        if scan_level not in {"quick", "standard", "force"}:
            raise ValueError("Некорректный уровень сканирования")
        test = options.get("test", "standard")
        if test not in self._blockcheck_tests():
            raise ValueError("Неизвестный набор тестов Blockcheck2")
        for name in ("parallel", "skip_dns", "skip_ip_block"):
            if name in options and not isinstance(options[name], bool):
                raise ValueError(f"{name} должен быть boolean")
        return {
            "domain": domain,
            "protocols": tuple(dict.fromkeys(protocols)),
            "repeats": repeats,
            "timeout": timeout,
            "ip_version": ip_version,
            "scan_level": scan_level,
            "test": test,
            "parallel": options.get("parallel", False),
            "skip_dns": options.get("skip_dns", False),
            "skip_ip_block": options.get("skip_ip_block", False),
        }

    def clear_runtime_log(self) -> dict:
        if self.status().running:
            raise RuntimeError("Нельзя очищать журнал во время работы winws2")
        path = self.runtime_log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return self.runtime_log()

    def autostart_status(self) -> dict:
        service_state = self._query_service_state()
        installed = service_state is not None
        image_path = None
        start_type = None
        if installed:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    rf"SYSTEM\CurrentControlSet\Services\{self.SERVICE_NAME}",
                ) as key:
                    image_path = str(winreg.QueryValueEx(key, "ImagePath")[0])
                    start_type = int(winreg.QueryValueEx(key, "Start")[0])
            except OSError:
                pass
        preview = self.strategy_preview()
        expected = preview.command_line if not preview.warnings else None
        return {
            "service": self.SERVICE_NAME,
            "installed": installed,
            "running": service_state == 4,
            "state": service_state,
            "automatic": start_type == 2,
            "image_path": image_path,
            "expected_image_path": expected,
            "in_sync": bool(installed and expected and image_path == expected),
            "can_manage": self._is_admin(),
            "warnings": preview.warnings,
        }

    def panel_autostart_status(self) -> dict:
        expected = subprocess.list2cmdline([
            str(self.project_dir / ".venv" / "Scripts" / "pythonw.exe"),
            str(self.project_dir / "scripts" / "panel_background.pyw"),
        ])
        command = None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.PANEL_RUN_KEY) as key:
                command = str(winreg.QueryValueEx(key, self.PANEL_RUN_NAME)[0])
        except FileNotFoundError:
            pass
        return {
            "installed": command is not None,
            "in_sync": command == expected,
            "command": command,
            "expected_command": expected,
            "can_manage": (self.project_dir / ".venv" / "Scripts" / "pythonw.exe").is_file(),
        }

    def install_panel_autostart(self) -> dict:
        status = self.panel_autostart_status()
        if not status["can_manage"]:
            raise RuntimeError("Сначала запустите setup.bat: pythonw.exe не найден в .venv")
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, self.PANEL_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, self.PANEL_RUN_NAME, 0, winreg.REG_SZ, status["expected_command"])
        return self.panel_autostart_status()

    def remove_panel_autostart(self) -> dict:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.PANEL_RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, self.PANEL_RUN_NAME)
        except FileNotFoundError:
            pass
        return self.panel_autostart_status()

    def install_autostart(self) -> dict:
        if not self._is_admin():
            raise RuntimeError("Для настройки автозапуска запустите панель от администратора")
        service = self.autostart_status()
        if service["running"]:
            raise RuntimeError("Сначала остановите службу перед обновлением её команды")
        preview = self.strategy_preview()
        self._validate_preview(preview)
        if service["installed"]:
            self._run_sc(
                "config",
                self.SERVICE_NAME,
                "binPath=",
                preview.command_line,
                "start=",
                "auto",
                "DisplayName=",
                self.SERVICE_DISPLAY_NAME,
            )
        else:
            self._run_sc(
                "create",
                self.SERVICE_NAME,
                "binPath=",
                preview.command_line,
                "start=",
                "auto",
                "DisplayName=",
                self.SERVICE_DISPLAY_NAME,
            )
        self._run_sc(
            "description",
            self.SERVICE_NAME,
            "Zapret2 DPI bypass managed by Zapret2 WebControl",
        )
        return self.autostart_status()

    def remove_autostart(self) -> dict:
        if not self._is_admin():
            raise RuntimeError("Для удаления автозапуска запустите панель от администратора")
        service = self.autostart_status()
        if not service["installed"]:
            return service
        if service["running"]:
            self._run_sc("stop", self.SERVICE_NAME)
        self._run_sc("delete", self.SERVICE_NAME)
        return self.autostart_status()

    def start_service(self) -> dict:
        service = self.autostart_status()
        if not service["installed"]:
            raise RuntimeError("Служба автозапуска не установлена")
        if not service["in_sync"]:
            raise RuntimeError("Конфигурация службы устарела; сначала примените изменения")
        if service["running"]:
            return service
        self._run_sc("start", self.SERVICE_NAME)
        return self.autostart_status()

    def stop_service(self) -> dict:
        service = self.autostart_status()
        if not service["installed"]:
            raise RuntimeError("Служба автозапуска не установлена")
        if not service["running"]:
            return service
        self._run_sc("stop", self.SERVICE_NAME)
        return self.autostart_status()

    def _validate_preview(self, preview: CompilationResult) -> None:
        executable = self.find_executable()
        if executable is None:
            raise RuntimeError("winws2.exe не найден")
        if preview.warnings:
            raise RuntimeError(
                "Команда не готова к запуску. Проверьте предпросмотр: "
                + "; ".join(preview.warnings)
            )
        try:
            validation = subprocess.run(
                [preview.command[0], "--dry-run", *preview.command[1:]],
                cwd=executable.parent,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"Проверка winws2 --dry-run не выполнена: {error}") from error
        if validation.returncode != 0:
            details = (validation.stderr or validation.stdout).strip()[-1000:]
            raise RuntimeError(f"winws2 --dry-run отклонил команду: {details}")

    @staticmethod
    def _is_admin() -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def _query_service_state(self) -> int | None:
        sc_manager_connect = 0x0001
        service_query_status = 0x0004
        sc_status_process_info = 0

        class ServiceStatusProcess(ctypes.Structure):
            _fields_ = [
                ("service_type", ctypes.c_ulong),
                ("current_state", ctypes.c_ulong),
                ("controls_accepted", ctypes.c_ulong),
                ("win32_exit_code", ctypes.c_ulong),
                ("service_specific_exit_code", ctypes.c_ulong),
                ("check_point", ctypes.c_ulong),
                ("wait_hint", ctypes.c_ulong),
                ("process_id", ctypes.c_ulong),
                ("service_flags", ctypes.c_ulong),
            ]

        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.OpenSCManagerW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
        advapi.OpenSCManagerW.restype = ctypes.c_void_p
        advapi.OpenServiceW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
        advapi.OpenServiceW.restype = ctypes.c_void_p
        advapi.QueryServiceStatusEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        advapi.QueryServiceStatusEx.restype = ctypes.c_int
        advapi.CloseServiceHandle.argtypes = [ctypes.c_void_p]
        advapi.CloseServiceHandle.restype = ctypes.c_int
        manager = advapi.OpenSCManagerW(None, None, sc_manager_connect)
        if not manager:
            return None
        service = None
        try:
            service = advapi.OpenServiceW(manager, self.SERVICE_NAME, service_query_status)
            if not service:
                return None
            status = ServiceStatusProcess()
            needed = ctypes.c_ulong()
            ok = advapi.QueryServiceStatusEx(
                service,
                sc_status_process_info,
                ctypes.byref(status),
                ctypes.sizeof(status),
                ctypes.byref(needed),
            )
            return int(status.current_state) if ok else None
        finally:
            if service:
                advapi.CloseServiceHandle(service)
            advapi.CloseServiceHandle(manager)

    @staticmethod
    def _run_sc(*arguments: str) -> None:
        result = subprocess.run(
            ["sc.exe", *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()[-1200:]
            raise RuntimeError(f"Service Control Manager отклонил операцию: {details}")

    def strategy_preview(self) -> CompilationResult:
        compiler = WindowsStrategyCompiler(
            executable=self.find_executable(),
            lua_dir=self.project_bundle_lua_dir,
            files_dir=self.project_bundle_files_dir,
            lists_dir=self.lists_dir,
            raw_filter_dir=self.project_bundle_raw_filter_dir,
            blob_dirs=(
                self.runtime_blobs_dir,
                self.project_bundle_files_dir,
                self.project_bundle_legacy_blob_dir,
            ),
        )
        return compiler.compile(self.strategies())

    def start(self) -> RuntimeStatus:
        if self.blockcheck_status()["running"]:
            raise RuntimeError("Сначала остановите Blockcheck2")
        current = self.status()
        if current.running:
            raise RuntimeError("winws2 уже запущен; сначала остановите управляемый процесс")
        service = self.autostart_status()
        if service["installed"]:
            self.start_service()
            return self.status()

        preview = self.strategy_preview()
        executable = self.find_executable()
        self._validate_preview(preview)

        try:
            self.runtime_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = self.runtime_log_path.open("ab", buffering=0)
            started_at = datetime.now(timezone.utc).isoformat()
            self._log_handle.write(
                f"\n[{started_at}] Starting managed winws2\n".encode("utf-8")
            )
            self._managed_process = subprocess.Popen(
                list(preview.command),
                cwd=executable.parent,
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                ),
            )
        except OSError as error:
            self._managed_process = None
            self._close_log()
            raise RuntimeError(f"Не удалось запустить winws2: {error}") from error
        return self.status()

    def stop(self) -> RuntimeStatus:
        process = self._managed_process
        if process is None:
            service = self.autostart_status()
            if service["running"]:
                self.stop_service()
                return self.status()
            raise RuntimeError(
                "Остановить можно только процесс или службу winws2, запущенные этой панелью"
            )
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._managed_process = None
        self._close_log()
        return self.status()

    def _close_log(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _close_blockcheck_log(self) -> None:
        if self._blockcheck_log_handle is not None:
            self._blockcheck_log_handle.close()
            self._blockcheck_log_handle = None
