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


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"Environment variable {name}={raw!r} must be one of: {allowed}")
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

    zenoh_enabled = _env_bool("ZENOH_ENABLED", False)
    zenoh_config_file = (os.getenv("ZENOH_CONFIG_FILE") or "").strip() or None
    zenoh_mode = _env_choice("ZENOH_MODE", "peer", {"peer", "client"})
    zenoh_connect = _env_csv("ZENOH_CONNECT")
    zenoh_listen = _env_csv("ZENOH_LISTEN")
    zenoh_key_prefix = os.getenv("ZENOH_KEY_PREFIX", "orch")
    zenoh_payload = _env_choice("ZENOH_PAYLOAD", "orch", {"orch", "json"})
    zenoh_loopback_ttl = _env_float("ZENOH_LOOPBACK_TTL_SEC", 0.35, minimum=0.0)

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

    bridges: list = []

    def _on_ws_publish(topic_name: str, type_str: str, value):
        for bridge in bridges:
            try:
                bridge.enqueue_ws_publish(topic_name, type_str, value)
            except Exception as exc:
                print(f"on_client_publish hook error for topic '{topic_name}': {exc}")

    server = ws.WebSocketServer(host=ws_host, port=ws_port, loop=loop, on_client_publish=_on_ws_publish)
    print(f"WebSocket server started on ws://{ws_host}:{ws_port}")

    # Ensure a single ROSSim instance exists (also required for ROS/Zenoh bridge wiring).
    server._ensure_sim()

    if ros_enabled:
        from ros import ROS2Bridge, ROS2BridgeConfig

        ros_bridge = ROS2Bridge(
            sim=server.sim,
            config=ROS2BridgeConfig(node_name=ros_node_name, discovery_period_sec=ros_discovery_sec),
        )
        ros_bridge.start()
        bridges.append(ros_bridge)
        print("ROS2 bridge enabled")

    if zenoh_enabled:
        from zenoh_bridge import ZenohBridge, ZenohBridgeConfig

        zenoh_bridge = ZenohBridge(
            sim=server.sim,
            config=ZenohBridgeConfig(
                key_prefix=zenoh_key_prefix,
                mode=zenoh_mode,
                connect=zenoh_connect,
                listen=zenoh_listen,
                config_file=zenoh_config_file,
                payload=zenoh_payload,
                loopback_ttl_sec=zenoh_loopback_ttl,
            ),
        )
        zenoh_bridge.start()
        bridges.append(zenoh_bridge)
        print("Zenoh bridge enabled")

    try:
        await server.run()
    finally:
        for bridge in reversed(bridges):
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
