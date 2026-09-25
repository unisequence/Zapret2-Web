from __future__ import annotations

import json
import mimetypes
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .backend.factory import create_backend


WEB_DIR = Path(__file__).with_name("web")


def create_server(backend=None, host: str = "127.0.0.1", port: int = 8787):
    runtime_backend = backend or create_backend()

    class Handler(BaseHTTPRequestHandler):
        server_version = "Zapret2WebControl/0.1"

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            route = urlparse(self.path).path
            if route == "/":
                self._send_file(WEB_DIR / "index.html")
            elif route == "/favicon.ico":
                self._send_file(WEB_DIR / "favicon.svg")
            elif route.startswith("/assets/"):
                self._send_asset(route.removeprefix("/assets/"))
            elif route == "/api/v1/health":
                self._send_json({"ok": True, "service": "zapret2-webcontrol"})
            elif route == "/api/v1/system":
                self._send_json(_to_jsonable(runtime_backend.info()))
            elif route == "/api/v1/status":
                self._send_json(_to_jsonable(runtime_backend.status()))
            elif route == "/api/v1/strategies":
                self._send_json(
                    {
                        "items": [
                            _to_jsonable(strategy)
                            for strategy in runtime_backend.strategies()
                        ]
                    }
                )
            elif route == "/api/v1/strategies/preview":
                self._send_json(_to_jsonable(runtime_backend.strategy_preview()))
            elif route == "/api/v1/lists":
                self._send_json(
                    {"items": [_to_jsonable(item) for item in runtime_backend.lists()]}
                )
            elif route.startswith("/api/v1/lists/"):
                list_id = unquote(route.removeprefix("/api/v1/lists/"))
                if not list_id or "/" in list_id:
                    self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                    return
                try:
                    document = runtime_backend.read_list(list_id)
                except KeyError:
                    self._send_json({"error": "list_not_found"}, HTTPStatus.NOT_FOUND)
                    return
                except RuntimeError as error:
                    self._send_json(
                        {"error": "list_read_failed", "message": str(error)},
                        HTTPStatus.CONFLICT,
                    )
                    return
                self._send_json(_to_jsonable(document))
            elif route == "/api/v1/logs/runtime":
                self._send_json(runtime_backend.runtime_log())
            elif route == "/api/v1/blockcheck/status":
                self._send_json(runtime_backend.blockcheck_status())
            elif route == "/api/v1/blockcheck/log":
                self._send_json(runtime_backend.blockcheck_log())
            elif route == "/api/v1/autostart":
                self._send_json(runtime_backend.autostart_status())
            else:
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            route = urlparse(self.path).path
            allowed = {
                "/api/v1/strategies",
                "/api/v1/runtime/start",
                "/api/v1/runtime/stop",
                "/api/v1/strategies/reset",
                "/api/v1/logs/runtime/clear",
                "/api/v1/blockcheck/start",
                "/api/v1/blockcheck/stop",
                "/api/v1/autostart/install",
                "/api/v1/autostart/remove",
            }
            if route not in allowed:
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            if not self._accept_json_mutation():
                return
            payload = self._read_json()
            if payload is None:
                self._send_json({"error": "invalid_json"}, HTTPStatus.BAD_REQUEST)
                return
            if route == "/api/v1/strategies":
                try:
                    strategy = runtime_backend.create_strategy(payload)
                    preview = runtime_backend.strategy_preview()
                except ValueError as error:
                    self._send_json(
                        {"error": "invalid_strategy", "message": str(error)},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                except RuntimeError as error:
                    self._send_json(
                        {"error": "strategy_create_failed", "message": str(error)},
                        HTTPStatus.CONFLICT,
                    )
                    return
                self._send_json(
                    {
                        "item": _to_jsonable(strategy),
                        "preview": _to_jsonable(preview),
                    },
                    HTTPStatus.CREATED,
                )
                return
            if not payload.get("confirm"):
                self._send_json(
                    {"error": "confirmation_required"}, HTTPStatus.BAD_REQUEST
                )
                return
            try:
                if route == "/api/v1/strategies/reset":
                    strategies = runtime_backend.reset_strategies()
                    self._send_json(
                        {
                            "items": [_to_jsonable(item) for item in strategies],
                            "preview": _to_jsonable(runtime_backend.strategy_preview()),
                        }
                    )
                    return
                if route == "/api/v1/logs/runtime/clear":
                    self._send_json(runtime_backend.clear_runtime_log())
                    return
                if route == "/api/v1/blockcheck/start":
                    self._send_json(
                        {"status": runtime_backend.start_blockcheck(payload.get("options", {}))}
                    )
                    return
                if route == "/api/v1/blockcheck/stop":
                    self._send_json({"status": runtime_backend.stop_blockcheck()})
                    return
                if route == "/api/v1/autostart/install":
                    self._send_json({"status": runtime_backend.install_autostart()})
                    return
                if route == "/api/v1/autostart/remove":
                    self._send_json({"status": runtime_backend.remove_autostart()})
                    return
                status = runtime_backend.start() if route.endswith("/start") else runtime_backend.stop()
            except ValueError as error:
                self._send_json(
                    {"error": "invalid_options", "message": str(error)},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            except RuntimeError as error:
                self._send_json(
                    {"error": "runtime_action_failed", "message": str(error)},
                    HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": _to_jsonable(status)})

        def do_PUT(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            route = urlparse(self.path).path
            prefix = "/api/v1/lists/"
            if not route.startswith(prefix):
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            list_id = unquote(route.removeprefix(prefix))
            if not list_id or "/" in list_id:
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            if not self._accept_json_mutation():
                return
            payload = self._read_json(max_length=2_200_000)
            if payload is None:
                self._send_json({"error": "invalid_json"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                document = runtime_backend.update_list(list_id, payload.get("content"))
            except KeyError:
                self._send_json({"error": "list_not_found"}, HTTPStatus.NOT_FOUND)
                return
            except ValueError as error:
                self._send_json(
                    {"error": "invalid_list", "message": str(error)},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            except RuntimeError as error:
                self._send_json(
                    {"error": "list_update_failed", "message": str(error)},
                    HTTPStatus.CONFLICT,
                )
                return
            self._send_json(_to_jsonable(document))

        def do_PATCH(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            route = urlparse(self.path).path
            prefix = "/api/v1/strategies/"
            if not route.startswith(prefix):
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            strategy_id = unquote(route.removeprefix(prefix))
            if not strategy_id or "/" in strategy_id:
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            if not self._accept_json_mutation():
                return
            payload = self._read_json(max_length=65536)
            if payload is None:
                self._send_json({"error": "invalid_json"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                strategy = runtime_backend.update_strategy(strategy_id, payload)
                preview = runtime_backend.strategy_preview()
            except KeyError:
                self._send_json({"error": "strategy_not_found"}, HTTPStatus.NOT_FOUND)
                return
            except ValueError as error:
                self._send_json(
                    {"error": "invalid_strategy", "message": str(error)},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            except RuntimeError as error:
                self._send_json(
                    {"error": "strategy_update_failed", "message": str(error)},
                    HTTPStatus.CONFLICT,
                )
                return
            self._send_json(
                {
                    "item": _to_jsonable(strategy),
                    "preview": _to_jsonable(preview),
                }
            )

        def do_DELETE(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            route = urlparse(self.path).path
            prefix = "/api/v1/strategies/"
            if not route.startswith(prefix):
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            strategy_id = unquote(route.removeprefix(prefix))
            if not strategy_id or "/" in strategy_id:
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            if not self._accept_json_mutation():
                return
            payload = self._read_json(max_length=1024)
            if payload is None:
                self._send_json({"error": "invalid_json"}, HTTPStatus.BAD_REQUEST)
                return
            if not payload.get("confirm"):
                self._send_json(
                    {"error": "confirmation_required"}, HTTPStatus.BAD_REQUEST
                )
                return
            try:
                removed = runtime_backend.delete_strategy(strategy_id)
                preview = runtime_backend.strategy_preview()
            except KeyError:
                self._send_json({"error": "strategy_not_found"}, HTTPStatus.NOT_FOUND)
                return
            except ValueError as error:
                self._send_json(
                    {"error": "strategy_delete_denied", "message": str(error)},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            except RuntimeError as error:
                self._send_json(
                    {"error": "strategy_delete_failed", "message": str(error)},
                    HTTPStatus.CONFLICT,
                )
                return
            self._send_json(
                {
                    "item": _to_jsonable(removed),
                    "preview": _to_jsonable(preview),
                }
            )

        def _accept_json_mutation(self) -> bool:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if content_type != "application/json":
                self._send_json(
                    {"error": "json_required"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE
                )
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host', '')}":
                self._send_json({"error": "invalid_origin"}, HTTPStatus.FORBIDDEN)
                return False
            return True

        def _read_json(self, *, max_length: int = 1024) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > max_length:
                    return None
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                return payload if isinstance(payload, dict) else None
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                return None

        def _send_asset(self, filename: str) -> None:
            relative = Path(unquote(filename))
            if relative.is_absolute() or ".." in relative.parts:
                self._send_json({"error": "invalid_path"}, HTTPStatus.BAD_REQUEST)
                return
            self._send_file(WEB_DIR / relative)

        def _send_file(self, path: Path) -> None:
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args) -> None:
            print(f"[http] {self.address_string()} - {format % args}")

    return ThreadingHTTPServer((host, port), Handler)


def _to_jsonable(value):
    if is_dataclass(value):
        return asdict(value)
    return value


def run() -> None:
    server = create_server()
    print("Zapret2 WebControl: http://127.0.0.1:8787")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()
