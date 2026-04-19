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
        fusion_msg = root / "sensor_fusion_msgs" / "msg"
        geometry_msg.mkdir(parents=True)
        sensor_msg.mkdir(parents=True)
        fusion_msg.mkdir(parents=True)

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

        (fusion_msg / "StopSigns.msg").write_text(
            """
geometry_msgs/Point32[] positions
geometry_msgs/Point32[] directions
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

    def test_multiple_arrays_message_round_trip(self):
        value = {
            "positions": [
                {"x": 1.0, "y": 2.0, "z": 3.0},
                {"x": 11.0, "y": 12.0, "z": 13.0},
            ],
            "directions": [
                {"x": -1.0, "y": -2.0, "z": -3.0},
                {"x": -11.0, "y": -12.0, "z": -13.0},
            ],
        }

        encoded = s.encode("sensor_fusion_msgs/StopSigns", value)
        decoded_type, decoded_value = s.decode(encoded)

        self.assertEqual(decoded_type, "sensor_fusion_msgs/StopSigns")
        self.assertEqual(len(decoded_value["positions"]), 2)
        self.assertEqual(len(decoded_value["directions"]), 2)
        self.assertAlmostEqual(decoded_value["positions"][1]["x"], 11.0, places=5)
        self.assertAlmostEqual(decoded_value["positions"][1]["y"], 12.0, places=5)
        self.assertAlmostEqual(decoded_value["positions"][1]["z"], 13.0, places=5)
        self.assertAlmostEqual(decoded_value["directions"][1]["x"], -11.0, places=5)
        self.assertAlmostEqual(decoded_value["directions"][1]["y"], -12.0, places=5)
        self.assertAlmostEqual(decoded_value["directions"][1]["z"], -13.0, places=5)

    def test_std_msgs_byte_top_level_round_trip(self):
        payload = bytes([0, 1, 2, 3, 255])

        encoded = s.encode("std_msgs/Byte", payload)
        decoded_type, decoded_value = s.decode(encoded)

        self.assertEqual(decoded_type, "std_msgs/Byte")
        self.assertEqual(decoded_value, payload)


if __name__ == "__main__":
    unittest.main()
