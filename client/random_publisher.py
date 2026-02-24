import asyncio
import random
import sys

import client


async def main() -> None:
    """Continuously publish random values to a few example topics.

    Topics:
    - chatter (std_msgs/String)
    - counter (std_msgs/Int32)
    - temperature (std_msgs/Float32)
    """

    time_per = 1.0

    if len(sys.argv) > 1:
        try:
            time_per = float(sys.argv[1])
        except ValueError:
            print(f"Invalid time interval '{sys.argv[1]}', using default of {time_per} seconds.")

    oc = client.OrchestratorClient()
    await oc.start(auto_subscribe=False)

    try:
        while True:
            # Random string message
            msg = f"hello {random.randint(0, 999)}"
            await oc.publish("chatter", "std_msgs/String", msg)

            # Random integer counter
            counter = random.randint(0, 100)
            await oc.publish("counter", "std_msgs/Int32", counter)

            # Random float temperature
            temperature = random.uniform(18.0, 25.0)
            await oc.publish("temperature", "std_msgs/Float32", temperature)

            await asyncio.sleep(time_per)
    except KeyboardInterrupt:
        pass
    finally:
        await oc.stop()


if __name__ == "__main__":
    asyncio.run(main())
