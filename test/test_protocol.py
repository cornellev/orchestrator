import json
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import serialization as s
import ws


VECTORS_PATH = ROOT / "clientrs" / "orchestrator-protocol" / "tests" / "fixtures" / "protocol_vectors.json"
if not VECTORS_PATH.exists():
    VECTORS_PATH = Path(__file__).parent / "protocol_vectors.json"
VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _normalize_value(type_name, value):
    if isinstance(value, dict) and "__bytes__" in value:
        return bytes(value["__bytes__"])
    if type_name == "std_msgs/ColorRGBA":
        return tuple(value)
    if type_name in {"std_msgs/Int64", "std_msgs/UInt64", "std_msgs/UInt32", "std_msgs/Int32"} and isinstance(value, str):
        return int(value)
    if isinstance(value, dict):
        return {k: _normalize_value("", v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_value("", item) for item in value]
    return value


def _register_vector_schemas(vector):
    if "definition" in vector:
        s.load_message_definition(vector["type"], vector["definition"])
    for type_name, definition in (vector.get("definitions") or {}).items():
        s.load_message_definition(type_name, definition)


class ProtocolContractTests(unittest.TestCase):
    def test_golden_vectors_round_trip(self):
        for name, vector in VECTORS.items():
            with self.subTest(name=name):
                _register_vector_schemas(vector)
                encoded = bytes.fromhex(vector["hex"])
                value = _normalize_value(vector["type"], vector["value"])
                self.assertEqual(s.encode(vector["type"], value), encoded)
                decoded_type, decoded_value = s.decode(encoded)
                self.assertEqual(decoded_type, vector["type"])
                if isinstance(value, float):
                    self.assertAlmostEqual(decoded_value, value, places=5)
                elif isinstance(value, tuple):
                    self.assertEqual(len(decoded_value), len(value))
                    for left, right in zip(decoded_value, value):
                        self.assertAlmostEqual(left, right, places=5)
                elif isinstance(value, dict):
                    self.assertEqual(decoded_type, vector["type"])
                    self._assert_nested_almost_equal(decoded_value, value)
                else:
                    self.assertEqual(decoded_value, value)

    def _assert_nested_almost_equal(self, actual, expected):
        if isinstance(expected, dict):
            self.assertIsInstance(actual, dict)
            self.assertEqual(set(actual), set(expected))
            for key in expected:
                self._assert_nested_almost_equal(actual[key], expected[key])
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(actual, expected):
                self._assert_nested_almost_equal(left, right)
        elif isinstance(expected, float):
            self.assertAlmostEqual(actual, expected, places=5)
        else:
            self.assertEqual(actual, expected)

    def test_char_rejects_non_ascii(self):
        with self.assertRaises(ValueError):
            s.encode("std_msgs/Char", "é")

    def test_truncated_payload_rejected(self):
        with self.assertRaises(ValueError):
            s.decode(bytes([0x02, 4, 0, 0, 0, 0x01]))

    def test_topic_name_limit(self):
        s.encode_topic_name("x" * 255)
        with self.assertRaises(ValueError):
            s.encode_topic_name("x" * 256)
        with self.assertRaises(ValueError):
            ws.construct_topicData("x" * 256, "std_msgs/Int32", 1)

    def test_empty_and_truncated_publish_payloads(self):
        with self.assertRaises(ws.ProtocolError):
            ws.decode_topicData(b"")
        with self.assertRaises(ws.ProtocolError):
            ws.decode_topicData(b"\x02/t\x02\x04\x00\x00\x00\x01")

    def test_error_frame_round_trip(self):
        frame = ws.encode_error("bad frame", code=42)
        self.assertEqual(frame[0], ws.responses["error"])
        code, message = ws.decode_error(frame[1:])
        self.assertEqual(code, 42)
        self.assertEqual(message, "bad frame")


if __name__ == "__main__":
    unittest.main()
