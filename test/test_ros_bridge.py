import queue
import threading
import time
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ros import ROS2Bridge, ROS2BridgeConfig, _select_unique_ros_type


class FakeSim:
    def __init__(self):
        self.topics = {}
        self.data = {}

    def add_topic(self, topic_name, type_str):
        self.topics.setdefault(topic_name, type_str)

    def update_topic(self, topic_name, data):
        self.data[topic_name] = data


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.debugs = []

    def warning(self, message):
        self.warnings.append(message)

    def debug(self, message):
        self.debugs.append(message)


class FakeNode:
    def __init__(self):
        self._logger = FakeLogger()

    def get_logger(self):
        return self._logger


class ROSBridgeHelperTests(unittest.TestCase):
    def test_select_unique_ros_type(self):
        self.assertEqual(_select_unique_ros_type(["std_msgs/msg/String"]), "std_msgs/msg/String")
        self.assertIsNone(_select_unique_ros_type([]))
        self.assertIsNone(_select_unique_ros_type(["a", "b"]))
        self.assertEqual(_select_unique_ros_type(["a", "a"]), "a")

    def test_conversion_failure_is_logged(self):
        bridge = ROS2Bridge(sim=FakeSim(), config=ROS2BridgeConfig())
        bridge._node = FakeNode()

        class BrokenMsg:
            def get_fields_and_field_types(self):
                raise RuntimeError("boom")

        bridge._on_ros_message("/broken", "std_msgs/String", BrokenMsg())
        self.assertTrue(any("conversion failed" in msg for msg in bridge._node.get_logger().warnings))

    def test_stop_drains_pending_publishes(self):
        bridge = ROS2Bridge(sim=FakeSim(), config=ROS2BridgeConfig())
        bridge._node = FakeNode()
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


if __name__ == "__main__":
    unittest.main()
