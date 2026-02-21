import asyncio
import client


async def main():
    oc = client.OrchestratorClient()
    await oc.start(auto_subscribe=False)
    await oc.publish("chatter", "std_msgs/String", "hello from python")
    await asyncio.sleep(0.2)
    await oc.stop()


if __name__ == "__main__":
    asyncio.run(main())
