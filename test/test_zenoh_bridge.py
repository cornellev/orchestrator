import queue
import threading
import time
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import serialization as s
from zenoh_bridge import (
    ZenohBridge,
    ZenohBridgeConfig,
    decode_json_value,
    decode_sample_payload,
    encode_json_value,
    encode_sample_payload,
    encoding_string,
    key_to_topic,
    parse_encoding,
    payload_mode_from_mime,
    sample_payload_bytes,
    topic_to_key,
)

try:
    import zenoh  # noqa: F401

    _ZENOH_AVAILABLE = True
except Exception:
    _ZENOH_AVAILABLE = False


class FakeSim:
    def __init__(self):
        self.topics = {}
        self.data = {}

    def add_topic(self, topic_name, type_str):
        self.topics.setdefault(topic_name, type_str)

    def update_topic(self, topic_name, data):
        self.data[topic_name] = data


class ZenohBridgeHelperTests(unittest.TestCase):
    def test_topic_to_key_strips_leading_slash(self):
        self.assertEqual(topic_to_key("/chatter", "orch"), "orch/chatter")
        self.assertEqual(topic_to_key("foo/bar", "orch"), "orch/foo/bar")
        self.assertEqual(topic_to_key("/nested/path", "/orch/"), "orch/nested/path")

    def test_key_to_topic_round_trip(self):
        topic = "/sensors/imu"
        key = topic_to_key(topic, "orch")
        self.assertEqual(key_to_topic(key, "orch"), topic)

    def test_key_to_topic_skips_metadata_and_foreign_prefix(self):
        self.assertIsNone(key_to_topic("orch/@meta/advert", "orch"))
        self.assertIsNone(key_to_topic("other/chatter", "orch"))
        self.assertIsNone(key_to_topic("orch", "orch"))

    def test_topic_to_key_rejects_wildcards(self):
        with self.assertRaises(ValueError):
            topic_to_key("/foo/*/bar", "orch")
        with self.assertRaises(ValueError):
            topic_to_key("/foo", "or*ch")
        with self.assertRaises(ValueError):
            topic_to_key("/", "orch")

    def test_encoding_schema_round_trip(self):
        orch_enc = encoding_string("orch", "std_msgs/String")
        json_enc = encoding_string("json", "std_msgs/Int32")
        self.assertEqual(orch_enc, "application/octet-stream;std_msgs/String")
        self.assertEqual(json_enc, "application/json;std_msgs/Int32")

        mime, schema = parse_encoding(orch_enc)
        self.assertEqual(mime, "application/octet-stream")
        self.assertEqual(schema, "std_msgs/String")
        self.assertEqual(payload_mode_from_mime(mime), "orch")
        self.assertEqual(payload_mode_from_mime("application/json"), "json")

    def test_orch_payload_round_trip(self):
        payload, enc = encode_sample_payload("std_msgs/String", "hello", "orch")
        type_name, value = decode_sample_payload(payload, enc)
        self.assertEqual(type_name, "std_msgs/String")
        self.assertEqual(value, "hello")
        self.assertEqual(s.decode(payload), ("std_msgs/String", "hello"))

    def test_json_payload_round_trip(self):
        payload, enc = encode_sample_payload("std_msgs/Int32", 42, "json")
        type_name, value = decode_sample_payload(payload, enc)
        self.assertEqual(type_name, "std_msgs/Int32")
        self.assertEqual(value, 42)
        self.assertEqual(decode_json_value(payload, "std_msgs/Int32"), 42)

    def test_json_byte_and_color_coercion(self):
        encoded = encode_json_value(b"\x01\x02")
        self.assertEqual(decode_json_value(encoded, "std_msgs/Byte"), b"\x01\x02")
        color = encode_json_value((0.1, 0.2, 0.3, 1.0))
        self.assertEqual(
            decode_json_value(color, "std_msgs/ColorRGBA"),
            (0.1, 0.2, 0.3, 1.0),
        )

    def test_sample_payload_bytes(self):
        self.assertEqual(sample_payload_bytes(None), b"")
        self.assertEqual(sample_payload_bytes(b"abc"), b"abc")

        class ZBytes:
            def to_bytes(self):
                return b"xyz"

        self.assertEqual(sample_payload_bytes(ZBytes()), b"xyz")

    def test_config_normalizes_and_rejects_invalid(self):
        cfg = ZenohBridgeConfig(key_prefix="/orch/", mode="PEER", payload="JSON")
        self.assertEqual(cfg.key_prefix, "orch")
        self.assertEqual(cfg.mode, "peer")
        self.assertEqual(cfg.payload, "json")
        with self.assertRaises(ValueError):
            ZenohBridgeConfig(mode="router")
        with self.assertRaises(ValueError):
            ZenohBridgeConfig(payload="cdr")

    def test_loopback_drops_matching_recent_publish(self):
        sim = FakeSim()
        bridge = ZenohBridge(sim=sim, config=ZenohBridgeConfig())
        bridge.enqueue_ws_publish("/chatter", "std_msgs/String", "hello")

        class Sample:
            kind = "PUT"
            key_expr = "orch/chatter"
            encoding = encoding_string("orch", "std_msgs/String")
            payload = s.encode("std_msgs/String", "hello")

        bridge._on_sample(Sample())
        self.assertNotIn("/chatter", sim.data)

    def test_inbound_sample_updates_sim(self):
        sim = FakeSim()
        bridge = ZenohBridge(sim=sim, config=ZenohBridgeConfig())

        class Sample:
            kind = "PUT"
            key_expr = "orch/chatter"
            encoding = encoding_string("orch", "std_msgs/String")
            payload = s.encode("std_msgs/String", "from zenoh")

        bridge._on_sample(Sample())
        self.assertEqual(sim.topics["/chatter"], "std_msgs/String")
        self.assertEqual(sim.data["/chatter"], "from zenoh")

    def test_inbound_type_mismatch_is_ignored(self):
        sim = FakeSim()
        sim.add_topic("/chatter", "std_msgs/String")
        bridge = ZenohBridge(sim=sim, config=ZenohBridgeConfig())

        class Sample:
            kind = "PUT"
            key_expr = "orch/chatter"
            encoding = encoding_string("orch", "std_msgs/Int32")
            payload = s.encode("std_msgs/Int32", 7)

        bridge._on_sample(Sample())
        self.assertNotIn("/chatter", sim.data)
        self.assertEqual(sim.topics["/chatter"], "std_msgs/String")

    def test_stop_drains_pending_publishes(self):
        bridge = ZenohBridge(sim=FakeSim(), config=ZenohBridgeConfig())
        bridge._session = object()
        bridge._publish_queue.put(("/t", "std_msgs/Int32", 1))
        bridge._publish_queue.put(("/t", "std_msgs/Int32", 2))

        drained = {"count": 0}

        def fake_drain(*, max_items=200):
            count = 0
            while count < max_items:
                try:
                    bridge._publish_queue.get_nowait()
                except queue.Empty:
                    break
                count += 1
            drained["count"] += count
            return count

        bridge._drain_publish_queue = fake_drain
        bridge._thread = threading.Thread(target=lambda: None)
        bridge._thread.start = lambda: None
        bridge._thread.is_alive = lambda: False
        bridge._thread.join = lambda timeout=None: None

        bridge.stop(drain_timeout_sec=0.2)
        self.assertEqual(drained["count"], 2)
        self.assertTrue(bridge._publish_queue.empty())


@unittest.skipUnless(_ZENOH_AVAILABLE, "eclipse-zenoh not installed")
class ZenohBridgeLiveTests(unittest.TestCase):
    def test_inbound_put_from_peer_session(self):
        prefix = f"orch_test_{int(time.time() * 1000)}"
        sim = FakeSim()
        bridge = ZenohBridge(sim=sim, config=ZenohBridgeConfig(key_prefix=prefix, mode="peer"))
        bridge.start()
        try:
            payload, enc = encode_sample_payload("std_msgs/String", "live hello", "orch")
            with zenoh.open(zenoh.Config()) as session:
                session.put(f"{prefix}/example", payload, encoding=zenoh.Encoding(enc))

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and "/example" not in sim.data:
                time.sleep(0.05)

            self.assertEqual(sim.topics.get("/example"), "std_msgs/String")
            self.assertEqual(sim.data.get("/example"), "live hello")
        finally:
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
