import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import serialization as s


@dataclass
class StoredType:
    type_name: str
    definition: str
    updated_at: str


class CustomTypeStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _type_to_path(self, type_name: str) -> Path:
        if "/" not in type_name:
            raise ValueError("Type must be in the form 'package/MessageName'")
        package, msg_name = type_name.split("/", 1)
        return self.root / package / "msg" / f"{msg_name}.msg"

    def list_types(self) -> list[StoredType]:
        out: list[StoredType] = []
        for package_dir in sorted(self.root.iterdir()):
            if not package_dir.is_dir():
                continue
            msg_dir = package_dir / "msg"
            if not msg_dir.is_dir():
                continue
            for msg_file in sorted(msg_dir.glob("*.msg")):
                type_name = f"{package_dir.name}/{msg_file.stem}"
                stat = msg_file.stat()
                updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                out.append(
                    StoredType(
                        type_name=type_name,
                        definition=msg_file.read_text(encoding="utf-8"),
                        updated_at=updated_at,
                    )
                )
        return out

    def get_type(self, type_name: str) -> Optional[StoredType]:
        path = self._type_to_path(type_name)
        if not path.exists():
            return None
        stat = path.stat()
        return StoredType(
            type_name=type_name,
            definition=path.read_text(encoding="utf-8"),
            updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        )

    def save_type(self, type_name: str, definition: str) -> StoredType:
        path = self._type_to_path(type_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            path.write_text(definition.strip() + "\n", encoding="utf-8")
            package = type_name.split("/", 1)[0]
            s.load_message_file(path, package=package)
            stat = path.stat()
            return StoredType(
                type_name=type_name,
                definition=path.read_text(encoding="utf-8"),
                updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            )


class TypesAPIHandler(BaseHTTPRequestHandler):
    store: CustomTypeStore = None

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._set_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/types":
            self._handle_list_types(parsed)
            return

        if parsed.path.startswith("/api/types/"):
            type_name = self._type_name_from_path(parsed.path)
            if not type_name:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "Expected /api/types/<package>/<MessageName>"})
                return
            found = self.store.get_type(type_name)
            if not found:
                self._json_response(HTTPStatus.NOT_FOUND, {"error": f"Type '{type_name}' not found"})
                return
            self._json_response(
                HTTPStatus.OK,
                {
                    "type": found.type_name,
                    "definition": found.definition,
                    "updated_at": found.updated_at,
                },
            )
            return

        self._json_response(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/types/"):
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        type_name = self._type_name_from_path(parsed.path)
        if not type_name:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "Expected /api/types/<package>/<MessageName>"})
            return

        body = self._read_json_body()
        if body is None:
            return

        definition = body.get("definition")
        if not isinstance(definition, str) or not definition.strip():
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "Field 'definition' (string) is required"})
            return

        try:
            stored = self.store.save_type(type_name, definition)
        except Exception as exc:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        self._json_response(
            HTTPStatus.OK,
            {
                "type": stored.type_name,
                "definition": stored.definition,
                "updated_at": stored.updated_at,
            },
        )

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/types/sync":
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        body = self._read_json_body()
        if body is None:
            return

        incoming = body.get("types")
        if not isinstance(incoming, list):
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "Field 'types' must be an array"})
            return

        saved = []
        for item in incoming:
            if not isinstance(item, dict):
                continue
            type_name = item.get("type")
            definition = item.get("definition")
            if not isinstance(type_name, str) or not isinstance(definition, str):
                continue
            try:
                stored = self.store.save_type(type_name, definition)
            except Exception:
                continue
            saved.append(
                {
                    "type": stored.type_name,
                    "updated_at": stored.updated_at,
                }
            )

        self._json_response(HTTPStatus.OK, {"saved": saved, "count": len(saved)})

    def _handle_list_types(self, parsed):
        query = parse_qs(parsed.query)
        since = query.get("since", [None])[0]

        all_types = self.store.list_types()
        if since:
            filtered = [t for t in all_types if t.updated_at > since]
        else:
            filtered = all_types

        payload = {
            "types": [
                {
                    "type": t.type_name,
                    "definition": t.definition,
                    "updated_at": t.updated_at,
                }
                for t in filtered
            ],
            "count": len(filtered),
        }
        self._json_response(HTTPStatus.OK, payload)

    def _type_name_from_path(self, path: str) -> Optional[str]:
        parts = [p for p in path.split("/") if p]
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "types":
            return None
        return f"{parts[2]}/{parts[3]}"

    def _read_json_body(self):
        length_raw = self.headers.get("Content-Length", "0")
        try:
            length = int(length_raw)
        except ValueError:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "Invalid Content-Length"})
            return None

        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "Body must be valid JSON"})
            return None

    def _json_response(self, status: HTTPStatus, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        return


class TypesAPIServer:
    def __init__(self, host: str = "localhost", port: int = 8090, store_dir: str = "custom_types"):
        self.host = host
        self.port = port
        self.store = CustomTypeStore(Path(store_dir).resolve())
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        s.load_message_root(self.store.root)

        handler = type("BoundTypesAPIHandler", (TypesAPIHandler,), {})
        handler.store = self.store
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
