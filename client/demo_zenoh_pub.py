"""Publish a native Zenoh sample the orchestrator bridge will mirror.

Run the server with Zenoh enabled first:

    ZENOH_ENABLED=true python main.py

Then:

    python client/demo_zenoh_pub.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import serialization as s
from zenoh_bridge import encode_sample_payload, topic_to_key


def main() -> None:
    try:
        import zenoh
    except Exception as exc:
        raise SystemExit(
            "eclipse-zenoh is required for this demo. "
            "Install it with: pip install -r requirements-zenoh.txt"
        ) from exc

    prefix = "orch"
    topic = "/example"
    orch_type = "std_msgs/String"
    value = "hello from zenoh"

    if hasattr(zenoh, "init_log_from_env_or"):
        zenoh.init_log_from_env_or("error")

    key = topic_to_key(topic, prefix)
    payload, encoding = encode_sample_payload(orch_type, value, "orch")

    with zenoh.open(zenoh.Config()) as session:
        pub = session.declare_publisher(key)
        print(f"Putting {orch_type} on {key}: {value!r}")
        pub.put(payload, encoding=zenoh.Encoding(encoding))
        time.sleep(0.5)


if __name__ == "__main__":
    main()
