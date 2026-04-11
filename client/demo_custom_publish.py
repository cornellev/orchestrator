import asyncio
import random
from pathlib import Path

import client
import serialization as s


async def main() -> None:
    root = Path(__file__).resolve().parents[1] / "messages"
    s.load_message_root(root)

    oc = client.OrchestratorClient()
    await oc.start(auto_subscribe=False)

    try:
        while True:
            points = []
            for _ in range(8):
                points.append(
                    {
                        "x": random.uniform(-10.0, 10.0),
                        "y": random.uniform(-10.0, 10.0),
                        "z": random.uniform(-2.0, 2.0),
                    }
                )

            payload = {"points": points}
            await oc.publish("/demo/point_cloud", "sensor_msgs/PointCloud", payload)
            await asyncio.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        await oc.stop()


if __name__ == "__main__":
    asyncio.run(main())
