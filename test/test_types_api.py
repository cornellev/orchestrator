import json
import tempfile
import unittest
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types_api import TypesAPIServer, _is_loopback_host


class TypesAPITests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.server = TypesAPIServer(
            host="127.0.0.1",
            port=0,
            store_dir=self._tempdir.name,
            write_token="secret-token",
        )
        self.server.start()
        self.port = self.server._httpd.server_port
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.stop()
        self._tempdir.cleanup()

    def test_options_preflight_types_sync(self):
        req = Request(f"{self.base}/api/types/sync", method="OPTIONS")
        with urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")
            methods = response.headers.get("Access-Control-Allow-Methods", "")
            self.assertIn("OPTIONS", methods)
            self.assertIn("POST", methods)
            headers = response.headers.get("Access-Control-Allow-Headers", "")
            self.assertIn("Content-Type", headers)
            self.assertIn("Authorization", headers)

    def test_sync_requires_bearer_token(self):
        body = json.dumps(
            {
                "types": [
                    {
                        "type": "demo_msgs/Thing",
                        "definition": "int32 value\n",
                    }
                ]
            }
        ).encode("utf-8")

        sync_req = Request(
            f"{self.base}/api/types/sync",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(sync_req, timeout=5)
        self.assertEqual(ctx.exception.code, 401)

        auth_req = Request(
            f"{self.base}/api/types/sync",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret-token",
            },
            method="POST",
        )
        with urlopen(auth_req, timeout=5) as response:
            self.assertEqual(response.status, 200)

        with urlopen(f"{self.base}/api/types", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        types = payload.get("types", [])
        self.assertTrue(any(t.get("type") == "demo_msgs/Thing" for t in types))

    def test_sync_reports_invalid_entries(self):
        body = json.dumps(
            {
                "types": [
                    {"type": "demo_msgs/Ok", "definition": "int32 value\n"},
                    {"type": "bad", "definition": "int32 value\n"},
                    "not-an-object",
                ]
            }
        ).encode("utf-8")
        req = Request(
            f"{self.base}/api/types/sync",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret-token",
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(payload["count"], 1)
        self.assertTrue(payload["errors"])

    def test_body_size_limit(self):
        oversized = TypesAPIServer(
            host="127.0.0.1",
            port=0,
            store_dir=self._tempdir.name,
            write_token="secret-token",
            max_body_bytes=32,
        )
        oversized.start()
        try:
            port = oversized._httpd.server_port
            body = json.dumps({"types": [{"type": "demo_msgs/Big", "definition": "int32 value\n" * 20}]}).encode("utf-8")
            req = Request(
                f"http://127.0.0.1:{port}/api/types/sync",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer secret-token",
                },
                method="POST",
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 413)
        finally:
            oversized.stop()

    def test_remote_bind_requires_token(self):
        with self.assertRaises(RuntimeError):
            TypesAPIServer(host="0.0.0.0", port=0, store_dir=self._tempdir.name, write_token=None).start()

    def test_loopback_helper(self):
        self.assertTrue(_is_loopback_host("127.0.0.1"))
        self.assertTrue(_is_loopback_host("localhost"))
        self.assertFalse(_is_loopback_host("0.0.0.0"))


if __name__ == "__main__":
    unittest.main()
