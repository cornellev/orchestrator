import asyncio
import ws


async def main() -> None:
    server = ws.WebSocketServer(host="localhost", port=8080)
    print("WebSocket server started on ws://localhost:8080")
    await server.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("WebSocket server stopped.")