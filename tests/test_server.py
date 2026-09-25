import json
import sys
import threading
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from zapret2_webcontrol.server import create_server
from zapret2_webcontrol.strategies import CompilationResult, LinuxStrategyCompiler, WindowsStrategyCompiler, default_strategies
from zapret2_webcontrol.strategy_store import StrategyStore, StrategyValidationError
from zapret2_webcontrol.list_store import ListDocument, ListInfo, ListStore, ListValidationError
from zapret2_webcontrol.reference_importer import parse_uci_strategies
from zapret2_webcontrol.backend.factory import create_backend
from zapret2_webcontrol.backend.linux import LinuxBackend

if sys.platform == "win32":
    from zapret2_webcontrol.backend.windows import WindowsBackend
else:
    WindowsBackend = None


@dataclass(frozen=True)
class FakeInfo:
    platform: str = "windows"
    backend: str = "fake"
    display_name: str = "Test backend"
    capabilities: tuple[str, ...] = ("process_status",)


@dataclass(frozen=True)
class FakeStatus:
    service: str = "winws2"
    running: bool = False
    pid: int | None = None
    executable: str | None = None
    checked_at: str = "2026-01-01T00:00:00+00:00"
    control_mode: str = "read_only"


class FakeBackend:
    def __init__(self):
        self._strategies = default_strategies()[:1]
        self._lists = {"discord": "discord.com\n"}
        self._log = "test log\n"
        self._blockcheck_running = False
        self._autostart_installed = False

    def info(self):
        return FakeInfo()

    def status(self):
        return FakeStatus()

    def strategies(self):
        return self._strategies

    def strategy_preview(self):
        return WindowsStrategyCompiler(
            executable=None,
            lua_dir=None,
            files_dir=None,
            lists_dir=Path(".") / "missing-lists",
        ).compile(self.strategies())

    def start(self):
        return FakeStatus(running=True, control_mode="managed", pid=1234)

    def stop(self):
        return FakeStatus(running=False, control_mode="managed")

    def update_strategy(self, strategy_id, patch):
        validated = StrategyStore._validate_patch(patch)
        for index, strategy in enumerate(self._strategies):
            if strategy.id == strategy_id:
                updated = replace(strategy, **validated)
                self._strategies = self._strategies[:index] + (updated,) + self._strategies[index + 1:]
                return updated
        raise KeyError(strategy_id)

    def reset_strategies(self):
        self._strategies = default_strategies()[:1]
        return self._strategies

    def create_strategy(self, payload):
        fields = StrategyStore._validate_create(payload)
        index = 1 + sum(item.source == "custom" for item in self._strategies)
        strategy = StrategyStore._custom_strategy(f"custom_test_{index}", fields)
        self._strategies = self._strategies + (strategy,)
        return strategy

    def delete_strategy(self, strategy_id):
        strategy = next(
            (item for item in self._strategies if item.id == strategy_id), None
        )
        if strategy is None:
            raise KeyError(strategy_id)
        if strategy.source != "custom":
            raise StrategyValidationError("Эталонную стратегию нельзя удалить")
        self._strategies = tuple(
            item for item in self._strategies if item.id != strategy_id
        )
        return strategy

    def lists(self):
        content = self._lists["discord"]
        entries = sum(1 for line in content.splitlines() if line.strip())
        return (
            ListInfo(
                id="discord",
                label="Discord",
                description="Test list",
                filename="zapret_hosts_discord.txt",
                source="runtime",
                path="test/zapret_hosts_discord.txt",
                exists=True,
                entries=entries,
                size=len(content),
            ),
        )

    def read_list(self, list_id):
        if list_id != "discord":
            raise KeyError(list_id)
        return ListDocument(self.lists()[0], self._lists[list_id])

    def update_list(self, list_id, content):
        if list_id != "discord":
            raise KeyError(list_id)
        self._lists[list_id] = ListStore._validate_content(content)
        return self.read_list(list_id)

    def runtime_log(self):
        return {"path": "test/winws2.log", "content": self._log, "truncated": False}

    def clear_runtime_log(self):
        self._log = ""
        return self.runtime_log()

    def blockcheck_status(self):
        return {
            "available": True,
            "running": self._blockcheck_running,
            "pid": 9001 if self._blockcheck_running else None,
            "started_at": "2026-01-01T00:00:00+00:00" if self._blockcheck_running else None,
            "exit_code": None,
            "tests": ["standard"],
        }

    def blockcheck_log(self):
        return {"path": "test/blockcheck2.log", "content": "blockcheck log\n", "truncated": False}

    def start_blockcheck(self, options):
        if options.get("domain") == "bad domain":
            raise ValueError("Некорректный домен")
        self._blockcheck_running = True
        return self.blockcheck_status()

    def stop_blockcheck(self):
        self._blockcheck_running = False
        return self.blockcheck_status()

    def autostart_status(self):
        return {
            "service": "zapret2-webcontrol",
            "installed": self._autostart_installed,
            "running": False,
            "state": 1 if self._autostart_installed else None,
            "automatic": self._autostart_installed,
            "image_path": "winws2.exe" if self._autostart_installed else None,
            "expected_image_path": "winws2.exe",
            "in_sync": self._autostart_installed,
            "can_manage": True,
            "warnings": [],
        }

    def install_autostart(self):
        self._autostart_installed = True
        return self.autostart_status()

    def remove_autostart(self):
        self._autostart_installed = False
        return self.autostart_status()


class StrategyCatalogTests(unittest.TestCase):
    def test_full_router_catalog_is_preserved(self):
        strategies = default_strategies()
        self.assertEqual(len(strategies), 34)
        self.assertEqual(
            [strategy.name for strategy in strategies if strategy.enabled],
            [
                "Discord_circular",
                "discord_media",
                "discord_udp",
                "Youtube_UDP",
                "Yv08",
                "V_circular",
                "games_tcp",
                "games_udp",
            ],
        )
        self.assertEqual(strategies[13].name, "v1")
        self.assertEqual(strategies[-1].name, "Yv11")

    def test_discord_udp_uses_native_windows_capture_filters_and_blob(self):
        strategy = next(
            item for item in default_strategies() if item.id == "discord_udp"
        )
        with TemporaryDirectory() as temp:
            root = Path(temp)
            raw_dir = root / "raw"
            blob_dir = root / "blobs"
            raw_dir.mkdir()
            blob_dir.mkdir()
            for filename in (
                "windivert_part.discord_media.txt",
                "windivert_part.stun.txt",
            ):
                (raw_dir / filename).write_text("outbound", encoding="utf-8")
            (blob_dir / "quic_initial_steamcommunity_com.bin").write_bytes(b"x")

            result = WindowsStrategyCompiler(
                executable=Path("winws2.exe"),
                lua_dir=None,
                files_dir=None,
                lists_dir=root / "lists",
                raw_filter_dir=raw_dir,
                blob_dirs=(blob_dir,),
            ).compile((strategy,))

        self.assertEqual(
            sum(item.startswith("--wf-raw-part=@") for item in result.command),
            2,
        )
        self.assertTrue(
            any(
                item.startswith(
                    "--blob=blob_quic_initial_steamcommunity_com:@"
                )
                for item in result.command
            )
        )
        self.assertFalse(any("Blob не найден" in item for item in result.warnings))

    def test_linux_compiler_uses_nfqws_queue_without_windows_capture_options(self):
        strategy = next(item for item in default_strategies() if item.id == "yv08")
        with TemporaryDirectory() as temp:
            root = Path(temp)
            lua_dir = root / "lua"
            lists_dir = root / "lists"
            lua_dir.mkdir()
            lists_dir.mkdir()
            for name in ("zapret-lib.lua", "zapret-antidpi.lua", "zapret-auto.lua"):
                (lua_dir / name).write_text("", encoding="utf-8")
            (lists_dir / "zapret_hosts_youtube.txt").write_text(
                "youtube.com\n", encoding="utf-8"
            )
            result = LinuxStrategyCompiler(
                executable=Path("/opt/zapret2/nfq2/nfqws2"),
                lua_dir=lua_dir,
                files_dir=None,
                lists_dir=lists_dir,
                blob_dirs=(),
            ).compile((strategy,))

        self.assertIn("--qnum=300", result.command)
        self.assertIn("--filter-tcp=443", result.command)
        self.assertFalse(any(item.startswith("--wf-") for item in result.command))


class BackendFactoryTests(unittest.TestCase):
    def test_linux_backend_is_selected_explicitly(self):
        backend = create_backend("Linux")
        self.assertIsInstance(backend, LinuxBackend)
        self.assertNotIn("process_control", backend.info().capabilities)

    def test_unknown_platform_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Неподдерживаемая платформа"):
            create_backend("Plan9")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = FakeBackend()
        cls.server = create_server(cls.backend, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.backend.reset_strategies()
        self.backend._lists = {"discord": "discord.com\n"}
        self.backend._log = "test log\n"
        self.backend._blockcheck_running = False
        self.backend._autostart_installed = False

    def get_json(self, route):
        with urlopen(self.base_url + route) as response:
            return response.status, json.load(response)

    def post_json(self, route, payload):
        request = Request(
            self.base_url + route,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def patch_json(self, route, payload):
        request = Request(
            self.base_url + route,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def put_json(self, route, payload):
        request = Request(
            self.base_url + route,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def delete_json(self, route, payload):
        request = Request(
            self.base_url + route,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_health_and_system_endpoints(self):
        status, health = self.get_json("/api/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])

        status, system = self.get_json("/api/v1/system")
        self.assertEqual(status, 200)
        self.assertEqual(system["platform"], "windows")

    def test_status_endpoint_is_read_only_contract(self):
        status, payload = self.get_json("/api/v1/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "winws2")
        self.assertFalse(payload["running"])
        self.assertEqual(payload["control_mode"], "read_only")

    def test_strategy_catalog_and_preview(self):
        status, catalog = self.get_json("/api/v1/strategies")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["items"][0]["id"], "discord_circular")

        status, preview = self.get_json("/api/v1/strategies/preview")
        self.assertEqual(status, 200)
        self.assertIn("--wf-tcp-out=443", preview["command"])
        self.assertIn("discord_circular", preview["active_strategy_ids"])

    def test_runtime_actions_require_confirmation(self):
        status, payload = self.post_json("/api/v1/runtime/start", {})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "confirmation_required")

        status, payload = self.post_json("/api/v1/runtime/start", {"confirm": True})
        self.assertEqual(status, 200)
        self.assertTrue(payload["status"]["running"])

        status, payload = self.post_json("/api/v1/runtime/stop", {"confirm": True})
        self.assertEqual(status, 200)
        self.assertFalse(payload["status"]["running"])

    def test_strategy_update_endpoint(self):
        status, payload = self.patch_json(
            "/api/v1/strategies/discord_circular",
            {"enabled": False, "ports": ["8443"]},
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["item"]["enabled"])
        self.assertEqual(payload["item"]["ports"], ["8443"])

        status, payload = self.patch_json(
            "/api/v1/strategies/discord_circular",
            {"protocol": "icmp"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_strategy")

    def test_custom_strategy_create_and_delete(self):
        status, payload = self.post_json(
            "/api/v1/strategies",
            {
                "name": "My TLS",
                "enabled": False,
                "protocol": "tcp",
                "ports": ["443"],
                "filter_l7": ["tls"],
                "hostlist": None,
                "ordered_options": [
                    "--payload=tls_client_hello",
                    "--lua-desync=multisplit:pos=1",
                ],
            },
        )
        self.assertEqual(status, 201)
        strategy_id = payload["item"]["id"]
        self.assertEqual(payload["item"]["source"], "custom")

        status, payload = self.delete_json(
            f"/api/v1/strategies/{strategy_id}", {}
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "confirmation_required")

        status, payload = self.delete_json(
            f"/api/v1/strategies/{strategy_id}", {"confirm": True}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["item"]["id"], strategy_id)

        status, payload = self.delete_json(
            "/api/v1/strategies/discord_circular", {"confirm": True}
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "strategy_delete_denied")

    def test_strategy_reset_requires_confirmation(self):
        status, payload = self.post_json("/api/v1/strategies/reset", {})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "confirmation_required")

        status, payload = self.post_json(
            "/api/v1/strategies/reset", {"confirm": True}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"][0]["id"], "discord_circular")

    def test_list_read_and_update_endpoints(self):
        status, payload = self.get_json("/api/v1/lists")
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"][0]["id"], "discord")

        status, payload = self.get_json("/api/v1/lists/discord")
        self.assertEqual(status, 200)
        self.assertEqual(payload["content"], "discord.com\n")

        status, payload = self.put_json(
            "/api/v1/lists/discord", {"content": "discord.com\ncdn.discordapp.com"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["info"]["entries"], 2)
        self.assertTrue(payload["content"].endswith("\n"))

    def test_runtime_log_and_confirmed_clear(self):
        status, payload = self.get_json("/api/v1/logs/runtime")
        self.assertEqual(status, 200)
        self.assertIn("test log", payload["content"])

        status, payload = self.post_json("/api/v1/logs/runtime/clear", {})
        self.assertEqual(status, 400)
        status, payload = self.post_json(
            "/api/v1/logs/runtime/clear", {"confirm": True}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["content"], "")

    def test_blockcheck_lifecycle_requires_confirmation(self):
        status, payload = self.get_json("/api/v1/blockcheck/status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])

        status, payload = self.post_json(
            "/api/v1/blockcheck/start", {"options": {"domain": "rutracker.org"}}
        )
        self.assertEqual(status, 400)

        status, payload = self.post_json(
            "/api/v1/blockcheck/start",
            {"confirm": True, "options": {"domain": "bad domain"}},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_options")

        status, payload = self.post_json(
            "/api/v1/blockcheck/start",
            {"confirm": True, "options": {"domain": "rutracker.org"}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["status"]["running"])

        status, payload = self.post_json(
            "/api/v1/blockcheck/stop", {"confirm": True}
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["status"]["running"])

    def test_autostart_install_and_remove_require_confirmation(self):
        status, payload = self.get_json("/api/v1/autostart")
        self.assertEqual(status, 200)
        self.assertFalse(payload["installed"])

        status, payload = self.post_json("/api/v1/autostart/install", {})
        self.assertEqual(status, 400)

        status, payload = self.post_json(
            "/api/v1/autostart/install", {"confirm": True}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["status"]["installed"])

        status, payload = self.post_json(
            "/api/v1/autostart/remove", {"confirm": True}
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["status"]["installed"])


class StrategyStoreTests(unittest.TestCase):
    def test_overrides_are_persisted_without_changing_reference_catalog(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "strategies.json"
            store = StrategyStore(path)
            base = default_strategies()
            updated = store.update(
                base,
                "discord_circular",
                {
                    "enabled": False,
                    "ports": ["8443"],
                    "ordered_options": [
                        "--payload=tls_client_hello",
                        "--lua-desync=fake:blob=fake_default_tls",
                    ],
                },
            )
            self.assertFalse(updated.enabled)
            self.assertEqual(updated.ports, ("8443",))
            self.assertEqual(updated.payload, "tls_client_hello")

            restored = StrategyStore(path).apply(base)
            self.assertFalse(restored[0].enabled)
            self.assertTrue(base[0].enabled)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 1)

            store.reset()
            self.assertFalse(path.exists())

    def test_backend_owned_options_are_rejected(self):
        with TemporaryDirectory() as temp:
            store = StrategyStore(Path(temp) / "strategies.json")
            with self.assertRaisesRegex(StrategyValidationError, "управляется бэкендом"):
                store.update(
                    default_strategies(),
                    "discord_circular",
                    {"ordered_options": ["--wf-tcp-out=443"]},
                )

    def test_custom_strategy_round_trip_update_and_delete(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "strategies.json"
            store = StrategyStore(path)
            base = default_strategies()
            created = store.create(
                base,
                {
                    "name": "Моя TLS стратегия",
                    "enabled": False,
                    "protocol": "tcp",
                    "ports": ["443"],
                    "filter_l7": ["tls"],
                    "hostlist": "youtube",
                    "ordered_options": [
                        "--payload=tls_client_hello",
                        "--lua-desync=multisplit:pos=1",
                    ],
                },
            )
            self.assertEqual(created.source, "custom")
            self.assertTrue(created.id.startswith("custom_"))
            self.assertEqual(len(store.apply(base)), 35)

            updated = store.update(
                base, created.id, {"name": "Новая версия", "enabled": True}
            )
            self.assertEqual(updated.name, "Новая версия")
            self.assertTrue(updated.enabled)
            reloaded = StrategyStore(path).apply(base)[-1]
            self.assertEqual(reloaded.name, "Новая версия")
            self.assertEqual(reloaded.payload, "tls_client_hello")

            removed = store.delete(base, created.id)
            self.assertEqual(removed.id, created.id)
            self.assertEqual(len(store.apply(base)), 34)
            with self.assertRaisesRegex(StrategyValidationError, "нельзя удалить"):
                store.delete(base, "discord_circular")


class ListStoreTests(unittest.TestCase):
    def test_bundled_list_can_be_read_and_overridden(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            bundled = root / "list-youtube.txt"
            bundled.write_text("youtube.com\n", encoding="utf-8")
            store = ListStore(root / "runtime", bundled_youtube=bundled)

            document = store.read("youtube")
            self.assertEqual(document.info.source, "bundled")
            self.assertEqual(document.content, "youtube.com\n")

            updated = store.update("youtube", "googlevideo.com")
            self.assertEqual(updated.info.source, "runtime")
            self.assertEqual(updated.content, "googlevideo.com\n")

    def test_invalid_list_content_is_rejected(self):
        with TemporaryDirectory() as temp:
            store = ListStore(Path(temp))
            with self.assertRaises(ListValidationError):
                store.update("discord", "discord.com\0example.com")


class ReferenceImporterTests(unittest.TestCase):
    def test_multiline_uci_strategy_is_converted(self):
        source = """
config strategy 'Discord_circular'
    option enabled '1'
    option port '443'
    list filter_l3 'ipv4'
    list protocol 'tcp'
    list filter_l7 'tls'
    list filter_l7 'discord'
    list hostlist 'list_hosts_discord'
    option script '--payload=tls_client_hello
--in-range=-s5556
--lua-desync=circular:fails=3:maxtime=20
--in-range=x --lua-desync=multisplit:pos=2
--lua-desync=fake:blob=fake_default_tls'

config strategy 'Disabled'
    option enabled '0'
    option port '443'
    list protocol 'udp'
"""
        strategies = parse_uci_strategies(source)
        self.assertEqual(len(strategies), 2)
        strategy = strategies[0]
        self.assertEqual(strategy.id, "discord_circular")
        self.assertEqual(strategy.hostlist, "discord")
        self.assertEqual(strategy.payload, "tls_client_hello")
        self.assertEqual(strategy.range_filters, ("--in-range=-s5556", "--in-range=x"))
        self.assertEqual(len(strategy.lua_desync), 3)
        self.assertEqual(
            strategy.ordered_options[1:5],
            (
                "--in-range=-s5556",
                "--lua-desync=circular:fails=3:maxtime=20",
                "--in-range=x",
                "--lua-desync=multisplit:pos=2",
            ),
        )
        compiled = WindowsStrategyCompiler(
            executable=None,
            lua_dir=None,
            files_dir=None,
            lists_dir=Path(".") / "missing-lists",
        ).compile(strategies)
        command = compiled.command
        self.assertIn("--wf-tcp-in=443", command)
        self.assertLess(command.index("--in-range=-s5556"), command.index("--lua-desync=circular:fails=3:maxtime=20"))
        self.assertLess(command.index("--lua-desync=circular:fails=3:maxtime=20"), command.index("--in-range=x"))
        self.assertFalse(strategies[1].enabled)


@unittest.skipUnless(sys.platform == "win32", "Требуется Windows")
class WindowsRuntimeTests(unittest.TestCase):
    def test_missing_resources_block_process_launch(self):
        backend = WindowsBackend()
        preview = CompilationResult(
            command=("winws2.exe",),
            command_line="winws2.exe",
            active_strategy_ids=("sample",),
            warnings=("Список не найден",),
        )
        with patch.object(backend, "status", return_value=FakeStatus()), \
             patch.object(backend, "strategy_preview", return_value=preview), \
             patch.object(backend, "find_executable", return_value=Path("winws2.exe")), \
             patch("zapret2_webcontrol.backend.windows.subprocess.Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "Команда не готова"):
                backend.start()
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
