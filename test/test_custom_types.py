import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import serialization as s


class CustomTypeSerializationTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        root = Path(self._tempdir.name)

        geometry_msg = root / "geometry_msgs" / "msg"
        sensor_msg = root / "sensor_msgs" / "msg"
        geometry_msg.mkdir(parents=True)
        sensor_msg.mkdir(parents=True)

        (geometry_msg / "Point32.msg").write_text(
            """
float32 x
float32 y
float32 z
""".strip()
            + "\n",
            encoding="utf-8",
        )

        (sensor_msg / "PointCloud.msg").write_text(
            """
geometry_msgs/Point32[] points
""".strip()
            + "\n",
            encoding="utf-8",
        )

        (sensor_msg / "PointCloud2Lite.msg").write_text(
            """
uint32 width
uint8[] data
bool is_dense
""".strip()
            + "\n",
            encoding="utf-8",
        )

        s.load_message_root(root)

    def tearDown(self):
        self._tempdir.cleanup()

    def test_nested_array_message_round_trip(self):
        value = {
            "points": [
                {"x": 1.25, "y": -2.5, "z": 3.75},
                {"x": 10.0, "y": 11.0, "z": 12.0},
            ]
        }

        encoded = s.encode("sensor_msgs/PointCloud", value)
        decoded_type, decoded_value = s.decode(encoded)

        self.assertEqual(decoded_type, "sensor_msgs/PointCloud")
        self.assertEqual(len(decoded_value["points"]), 2)
        self.assertAlmostEqual(decoded_value["points"][0]["x"], 1.25, places=5)
        self.assertAlmostEqual(decoded_value["points"][0]["y"], -2.5, places=5)
        self.assertAlmostEqual(decoded_value["points"][1]["z"], 12.0, places=5)

    def test_uint8_array_round_trip(self):
        value = {
            "width": 4,
            "data": bytes([1, 2, 3, 255]),
            "is_dense": True,
        }

        encoded = s.encode("sensor_msgs/PointCloud2Lite", value)
        decoded_type, decoded_value = s.decode(encoded)

        self.assertEqual(decoded_type, "sensor_msgs/PointCloud2Lite")
        self.assertEqual(decoded_value["width"], 4)
        self.assertEqual(decoded_value["data"], bytes([1, 2, 3, 255]))
        self.assertTrue(decoded_value["is_dense"])


if __name__ == "__main__":
    unittest.main()
