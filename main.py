import asyncio
import ws
from types_api import TypesAPIServer


async def main() -> None:
    types_api = TypesAPIServer(host="localhost", port=8090, store_dir="custom_types")
    types_api.start()
    print("Types API started on http://localhost:8090")

    server = ws.WebSocketServer(host="localhost", port=8080)
    print("WebSocket server started on ws://localhost:8080")
    try:
        await server.run()
    finally:
        types_api.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("WebSocket server stopped.")