import asyncio
import os
import ws
from types_api import TypesAPIServer


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"Environment variable {name}={raw!r} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"Environment variable {name}={value} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"Environment variable {name}={value} must be <= {maximum}")
    return value


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"Environment variable {name}={raw!r} must be a number") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"Environment variable {name}={value} must be >= {minimum}")
    return value


async def main() -> None:
    ws_host = os.getenv("WS_HOST", "localhost")
    ws_port = _env_int("WS_PORT", 8080, minimum=1, maximum=65535)
    api_host = os.getenv("API_HOST", "localhost")
    api_port = _env_int("API_PORT", 8090, minimum=1, maximum=65535)
    store_dir = os.getenv("CUSTOM_TYPES_DIR", "custom_types")
    api_write_token = os.getenv("API_WRITE_TOKEN") or None

    ros_enabled = _env_bool("ROS_ENABLED", False)
    ros_node_name = os.getenv("ROS_NODE_NAME", "orchestrator_bridge")
    ros_discovery_sec = _env_float("ROS_DISCOVERY_PERIOD_SEC", 1.0, minimum=0.05)

    loop = asyncio.get_running_loop()

    types_api = TypesAPIServer(
        host=api_host,
        port=api_port,
        store_dir=store_dir,
        write_token=api_write_token,
    )
    types_api.start()
    print(f"Types API started on http://{api_host}:{api_port}")
    if api_write_token:
        print("Types API write protection enabled (API_WRITE_TOKEN)")

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
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(f"Startup error: {exc}") from exc
