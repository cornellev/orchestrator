import asyncio
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.client import ClientConnectionError, ClientStoppedError, OrchestratorClient


class ClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_fails_fast_when_server_unreachable(self):
        client = OrchestratorClient(uri="ws://127.0.0.1:1", reconnect=False)
        with self.assertRaises(ClientConnectionError):
            await asyncio.wait_for(client.start(), timeout=2.0)
        await client.stop()

    async def test_stop_unblocks_start_wait(self):
        client = OrchestratorClient(uri="ws://127.0.0.1:1", reconnect=True)
        start_task = asyncio.create_task(client.start())
        await asyncio.sleep(0.2)
        await client.stop()
        with self.assertRaises((ClientStoppedError, ClientConnectionError, asyncio.CancelledError)):
            await asyncio.wait_for(start_task, timeout=2.0)

    async def test_publish_after_stop_raises(self):
        client = OrchestratorClient(uri="ws://127.0.0.1:1", reconnect=False)
        await client.stop()
        with self.assertRaises((ClientStoppedError, ClientConnectionError)):
            await asyncio.wait_for(client.publish("/x", "std_msgs/Int32", 1), timeout=1.0)


if __name__ == "__main__":
    unittest.main()
