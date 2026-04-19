import json
import tempfile
import unittest
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types_api import TypesAPIServer


class TypesAPITests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.server = TypesAPIServer(host="127.0.0.1", port=0, store_dir=self._tempdir.name)
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
            self.assertEqual(response.headers.get("Access-Control-Allow-Headers"), "Content-Type")

    def test_sync_and_list_types(self):
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
        with urlopen(sync_req, timeout=5) as response:
            self.assertEqual(response.status, 200)

        with urlopen(f"{self.base}/api/types", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        types = payload.get("types", [])
        self.assertTrue(any(t.get("type") == "demo_msgs/Thing" for t in types))


if __name__ == "__main__":
    unittest.main()
