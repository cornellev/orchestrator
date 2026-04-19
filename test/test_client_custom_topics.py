import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import serialization as s
from client.client import OrchestratorClient


class ClientCustomTopicsTests(unittest.TestCase):
    def test_load_custom_topics_from_folder(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            msg_dir = root / "demo_pkg" / "msg"
            msg_dir.mkdir(parents=True)

            (msg_dir / "Thing.msg").write_text(
                """
float32 x
""".strip()
                + "\n",
                encoding="utf-8",
            )

            # Not loaded yet -> dynamic encode should fail.
            with self.assertRaises(ValueError):
                s.encode("demo_pkg/Thing", {"x": 1.25})

            client = OrchestratorClient()
            loaded = client.load_custom_topics(root)
            self.assertIn("demo_pkg/Thing", loaded)

            encoded = s.encode("demo_pkg/Thing", {"x": 1.25})
            decoded_type, decoded_value = s.decode(encoded)

            self.assertEqual(decoded_type, "demo_pkg/Thing")
            self.assertAlmostEqual(decoded_value["x"], 1.25, places=5)


if __name__ == "__main__":
    unittest.main()
