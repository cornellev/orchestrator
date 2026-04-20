import asyncio
import os
import ws
from types_api import TypesAPIServer


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


async def main() -> None:
    ws_host = os.getenv("WS_HOST", "localhost")
    ws_port = _env_int("WS_PORT", 8080)
    api_host = os.getenv("API_HOST", "localhost")
    api_port = _env_int("API_PORT", 8090)
    store_dir = os.getenv("CUSTOM_TYPES_DIR", "custom_types")

    ros_enabled = _env_bool("ROS_ENABLED", False)
    ros_node_name = os.getenv("ROS_NODE_NAME", "orchestrator_bridge")
    ros_discovery_sec = _env_float("ROS_DISCOVERY_PERIOD_SEC", 1.0)

    loop = asyncio.get_running_loop()

    types_api = TypesAPIServer(host=api_host, port=api_port, store_dir=store_dir)
    types_api.start()
    print(f"Types API started on http://{api_host}:{api_port}")

    bridge = None

    def _on_ws_publish(topic_name: str, type_str: str, value):
        if bridge is None:
            return
        bridge.enqueue_ws_publish(topic_name, type_str, value)

    server = ws.WebSocketServer(host=ws_host, port=ws_port, loop=loop, on_client_publish=_on_ws_publish)
    print(f"WebSocket server started on ws://{ws_host}:{ws_port}")

    # Ensure a single ROSSim instance exists (also required for ROS bridge wiring).
    server._ensure_sim()

    if ros_enabled:
        from ros import ROS2Bridge, ROS2BridgeConfig

        bridge = ROS2Bridge(
            sim=server.sim,
            config=ROS2BridgeConfig(node_name=ros_node_name, discovery_period_sec=ros_discovery_sec),
        )
        bridge.start()
        print("ROS2 bridge enabled")

    try:
        await server.run()
    finally:
        if bridge is not None:
            bridge.stop()
        types_api.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("WebSocket server stopped.")