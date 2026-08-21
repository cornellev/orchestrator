import asyncio
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ws
from client.client import OrchestratorClient


class WebSocketIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.server = ws.WebSocketServer(host="127.0.0.1", port=0, loop=self.loop)
        self.server._ensure_sim()
        self._serve_cm = None
        self._serve_task = None

        from websockets.asyncio.server import serve

        started = asyncio.Event()

        async def _run():
            async with serve(self.server.handler, "127.0.0.1", 0) as server:
                self._serve_cm = server
                self.port = server.sockets[0].getsockname()[1]
                started.set()
                await asyncio.Future()

        self._serve_task = asyncio.create_task(_run())
        await started.wait()

    async def asyncTearDown(self):
        if self._serve_task:
            self._serve_task.cancel()
            try:
                await self._serve_task
            except asyncio.CancelledError:
                pass

    async def test_publish_subscribe_round_trip(self):
        updates = asyncio.Queue()

        async def on_update(info):
            await updates.put(info)

        client = OrchestratorClient(
            uri=f"ws://127.0.0.1:{self.port}",
            reconnect=False,
            on_update=on_update,
        )
        await client.start(auto_subscribe=True)
        await client.publish("/demo", "std_msgs/String", "hello")
        info = await asyncio.wait_for(updates.get(), timeout=2.0)
        self.assertEqual(info.name, "/demo")
        self.assertEqual(info.type_str, "std_msgs/String")
        self.assertEqual(info.value, "hello")
        await client.stop()

    async def test_type_mismatch_sends_error(self):
        errors = asyncio.Queue()

        async def on_error(info):
            await errors.put(info)

        client = OrchestratorClient(
            uri=f"ws://127.0.0.1:{self.port}",
            reconnect=False,
            on_error=on_error,
        )
        await client.start(auto_subscribe=True)
        await client.publish("/typed", "std_msgs/Int32", 1)
        await asyncio.sleep(0.1)
        await client.publish("/typed", "std_msgs/String", "nope")
        err = await asyncio.wait_for(errors.get(), timeout=2.0)
        self.assertIn("Type mismatch", err.message)
        await client.stop()

    async def test_malformed_publish_is_rejected(self):
        from websockets.asyncio.client import connect

        async with connect(f"ws://127.0.0.1:{self.port}") as sock:
            await sock.send(bytes([0x02]) + b"\x02/t\x02\x04\x00\x00\x00\x01")
            response = await asyncio.wait_for(sock.recv(), timeout=2.0)
            self.assertEqual(response[0], ws.responses["error"])


if __name__ == "__main__":
    unittest.main()
