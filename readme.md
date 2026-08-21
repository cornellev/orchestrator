Orchestrator WebSocket Server
=============================

This project provides a small WebSocket server and matching clients (JavaScript, Python, and Rust) for publishing and subscribing to typed topics, inspired by simple ROS-style messaging. The binary protocol is shared between:

- The server started by running `main.py`.
- The browser/Node client in `clientjs/Client.js`.
- The Python client in `client/client.py`.
- The Rust crates in `clientrs/` (`orchestrator-protocol` + `orchestrator-ws-client`).

Running the server
------------------

Requirements:

- Python 3.9+ (asyncio-based)
- `websockets` (installed via `requirements.txt`)

Install dependencies (lowk not needed, just install websockets and ur prob good to go):

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\\Scripts\\activate
pip install -r requirements.txt
```


and start the server:
```
python main.py
```

You should see:

```text
WebSocket server started on ws://localhost:8080
```

Stop the server with Ctrl+C.

Configuration (env vars)
------------------------

The server supports two runtime modes:

- **Standalone (default):** WebSocket + Types API only; no ROS required.
- **ROS2 bridge (opt-in):** Enables an auto-discovery ROS 2 (rclpy) topic bridge.

Common env vars:

- `WS_HOST` / `WS_PORT` (default `localhost:8080`)
- `API_HOST` / `API_PORT` (default `localhost:8090`)
- `CUSTOM_TYPES_DIR` (default `custom_types`)
- `API_WRITE_TOKEN` (optional on loopback; **required** when `API_HOST` is non-loopback such as `0.0.0.0`)

ROS2 bridge env vars (only used if `ROS_ENABLED=true`):

- `ROS_ENABLED` (default `false`)
- `ROS_NODE_NAME` (default `orchestrator_bridge`)
- `ROS_DISCOVERY_PERIOD_SEC` (default `1.0`)

Binary protocol notes
---------------------

Canonical typed payload layout (Python and JavaScript must match):

- Envelope: `[type_byte][count:u32le][payload...]`
- `std_msgs/String` payload: `[strlen:u32le][utf8 bytes...]` (ROS-style length-prefixed)
- `std_msgs/Char` payload: one signed `int8` ASCII codepoint; values round-trip as a one-character string
- Topic names are length-prefixed with one byte and limited to **255 UTF-8 bytes**
- Server responses: `echo=0x80`, `echo_new=0x81`, `update=0x82`, `big_update=0x83`, `error=0x84`

Malformed frames and type mismatches return an `error` response instead of silently failing.

Testing
-------

```bash
python -m unittest discover -v
node --test test/test_js_protocol.test.js
cd clientrs && cargo test --workspace --all-features
```

Shared golden vectors live in `clientrs/orchestrator-protocol/tests/fixtures/protocol_vectors.json`
(mirrored at `test/protocol_vectors.json`) and are checked by Python, Node, and Rust.

Live Rust ↔ Python integration tests (ignored by default):

```bash
cd clientrs
cargo test -p orchestrator-ws-client --test integration -- --ignored
```

Rust client
-----------

The Rust workspace under `clientrs/` publishes two crates:

| Crate | crates.io name | Role |
|-------|----------------|------|
| `orchestrator-protocol` | `orchestrator-protocol` | Codec, schemas, frames |
| `orchestrator-ws-client` | `orchestrator-ws-client` | Tokio WebSocket client + Types REST sync |

MSRV: Rust 1.75. Dual licensed MIT OR Apache-2.0.

```toml
[dependencies]
orchestrator-ws-client = "0.1"
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
```

Example:

```rust
use orchestrator_protocol::Value;
use orchestrator_ws_client::{Client, ClientEvent};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (client, mut events) = Client::builder()
        .uri("ws://127.0.0.1:8080")
        .connect()
        .await?;

    client.publish("/example", "std_msgs/String", Value::string("hello from Rust")).await?;

    while let Some(event) = events.recv().await {
        if let ClientEvent::Update(update) = event {
            println!("update on {}: {:?}", update.name, update.value);
            break;
        }
    }
    client.stop().await?;
    Ok(())
}
```

Dynamic schemas can be loaded locally or synced from the Types API:

```rust
use orchestrator_protocol::{load_message_definition, MessageRegistry};
use orchestrator_ws_client::sync_types_from_server;
use std::sync::Arc;

let registry = Arc::new(MessageRegistry::new());
load_message_definition(&registry, "geometry_msgs/Point32", "float32 x\nfloat32 y\nfloat32 z\n")?;
// or: sync_types_from_server(&registry, "http://127.0.0.1:8090", None, None).await?;
```

Also see `clientrs/orchestrator-ws-client/examples/demo_publish.rs`.

**Publishing note:** On the first crates.io release, publish `orchestrator-protocol` first, then `orchestrator-ws-client` (path+version dependency). Do not publish from CI without an intentional release.

JavaScript client (browser or Node)
-----------------------------------

The JavaScript client is implemented in `clientjs/Client.js`. It uses the same binary protocol as the Python client and server and works in both browser and Node.js environments.

Basic usage (browser):

```html
<script src="clientjs/Client.js"></script>
<script>
	const { Client } = window.ROSClient;

	const client = new Client({
		url: "ws://localhost:8080",
		onOpen: () => {
			console.log("connected");
			client.subscribe();        // start receiving topic updates
			client.echo();             // ask server for the current topic list
		},
		onEcho: (topics) => {
			console.log("topics:", topics);
		},
		onUpdate: (info) => {
			console.log("topic update:", info);
		},
		onBigUpdate: (updates) => {
			console.log("big update:", updates);
		},
	});

	client.start();
	// later: client.stop();
</script>
```

Publishing from JavaScript:

```js
// After the client is connected
client.publish("/example", "std_msgs/String", "hello from JS");
```

Decoding custom dynamic message types in JavaScript:

```js
const { Client, registerMsgDefinition } = window.ROSClient;

registerMsgDefinition("geometry_msgs/Point32", `
float32 x
float32 y
float32 z
`);

registerMsgDefinition("sensor_msgs/PointCloud", `
geometry_msgs/Point32[] points
`);

// now onUpdate/onBigUpdate values for sensor_msgs/PointCloud are JS objects
```

Available standard types include (see `TYPE_ENCODERS` in `Client.js`):

- `std_msgs/String`
- `std_msgs/Int32`
- `std_msgs/Float32`
- `std_msgs/Bool`
- `std_msgs/Float64`
- `std_msgs/Int64`
- `std_msgs/UInt32`
- `std_msgs/UInt64`
- `std_msgs/Byte`
- `std_msgs/Char`
- `std_msgs/ColorRGBA`
- `std_msgs/Duration`

Python client
-------------

The Python client lives in `client/client.py` and exposes the `OrchestratorClient` class. It is an asyncio-based reciprocal client for the server started by `main.py`.

Requirements:

- Same environment as the server (`websockets` installed)

Example usage:

```python
import asyncio

from client.client import OrchestratorClient, TopicInfo, TopicUpdate


async def main() -> None:
		async def on_echo(topics: tuple[TopicInfo, ...]) -> None:
				print("Topics from server:")
				for t in topics:
						print(f"- {t.name} ({t.type_str}), count={t.count}")

		async def on_update(info: TopicUpdate) -> None:
				print(f"Update on {info.name}: type={info.type_str}, count={info.count}, value={info.value}")

		client = OrchestratorClient(
				uri="ws://localhost:8080",
				on_echo=on_echo,
				on_update=on_update,
		)

		await client.start(auto_subscribe=True)

		# Ask the server for the current set of topics
		await client.echo()

		# Publish an example message (type name must match server expectations)
		await client.publish("/example", "std_msgs/String", "hello from Python")

		# Keep running for a bit to receive updates
		await asyncio.sleep(5)
		await client.stop()


if __name__ == "__main__":
		asyncio.run(main())
```

Custom point cloud demo
-----------------------

This repo includes sample dynamic message files:

- [messages/geometry_msgs/msg/Point32.msg](messages/geometry_msgs/msg/Point32.msg)
- [messages/sensor_msgs/msg/PointCloud.msg](messages/sensor_msgs/msg/PointCloud.msg)

To test custom decoding end-to-end:

1. Start server:

```bash
python main.py
```

2. In another terminal, start JS test subscriber (registers custom schemas and prints decoded objects):

```bash
node clientjs/test.js
```

3. In another terminal, publish sample point clouds:

```bash
python client/demo_custom_publish.py
```

You should see `sensor_msgs/PointCloud` updates rendered as readable nested objects (not raw bytes).

Client operations
-----------------

Both the JavaScript `Client`, Python `OrchestratorClient`, and Rust `Client` support the same high-level operations:

- `echo` – ask the server for a list of known topics (metadata only).
- `subscribe` – subscribe to topic updates.
- `request_all` – request a snapshot of all known topic values.
- `publish` – publish a single message to a named topic with a specific type.

Protocol notes (responses):

- `echo` (`0x80`) and `echo_new` (`0x81`) send topic metadata only.
- `update` (`0x82`) sends topic metadata plus the encoded topic value (`[type byte][count (4 LE)][value bytes]`) appended after the metadata block.
- `big_update` (`0x83`) sends a full snapshot of all topics and encoded values.

When you run `main.py` and then start either client, you should see:

- The client connect to `ws://localhost:8080`.
- An initial `echo` response listing currently known topics (if any).
- Subsequent `update` or `big_update` messages as topics change.

Development notes
-----------------

- The on-wire encoding/decoding for message types is implemented in:
	- JavaScript: `clientjs/Client.js` (functions like `encodeValue`, `decodeValue`, `buildTopicData`).
	- Python: `serialization.py` (functions `encode`, `decode`, `typeFromByte`).
	- Rust: `clientrs/orchestrator-protocol` (functions `encode`, `decode`, frame helpers).
- The WebSocket server entrypoint is `main.py`, which delegates to `ws.WebSocketServer`.

Dynamic `.msg` type support
---------------------------

`serialization.py` now supports dynamic ROS-style message schemas (nested messages, variable/fixed arrays, `uint8[]` payloads, etc.).

How to load message definitions:

- Auto-discovery on startup (if present):
	- `./messages/<package>/msg/*.msg`
	- `./msgs/<package>/msg/*.msg`
	- `./msg/*.msg` (single-package flat folder)
- Or set `ORCH_MSG_PATHS` (OS path-separated list) to one or more roots/folders.

Programmatic loading APIs in `serialization.py`:

- `load_message_file(path, package=None)`
- `load_message_folder(path, package=None)`
- `load_message_root(path)`

REST API for custom type sync
-----------------------------

Server now starts a REST API on `http://localhost:8090` for managing custom message definitions.

Writes (`PUT` / `POST`) require `Authorization: Bearer <API_WRITE_TOKEN>` whenever `API_WRITE_TOKEN` is set.
Binding the API to a non-loopback host without a token fails startup.

Endpoints:

- `GET /api/types`
	- Pull all known custom message types.
- `GET /api/types?since=<ISO_TIMESTAMP>`
	- Pull only types updated after `since`.
- `GET /api/types/<package>/<MessageName>`
	- Fetch one message definition.
- `PUT /api/types/<package>/<MessageName>`
	- Save/update one message definition.
	- JSON body: `{ "definition": "... .msg text ..." }`
- `POST /api/types/sync`
	- Push many definitions in one request.
	- JSON body: `{ "types": [{"type":"pkg/Msg", "definition":"..."}] }`
	- Invalid entries are reported in `errors` (HTTP 400) instead of being silently skipped.

ROS2 bridge mode
----------------

If you have a ROS 2 Python environment available (i.e., `import rclpy` works):

```bash
ROS_ENABLED=true python main.py
```

Behavior:

- The bridge auto-discovers ROS 2 topics and mirrors them into the WebSocket server.
- WebSocket `publish` calls forward into ROS 2 as publishers.

Notes:

- On macOS, ROS 2 discovery from Docker Desktop to a host ROS graph can be unreliable (DDS/networking). For best results, run the bridge in the same ROS environment as the nodes you want to bridge.

Docker
------

Standalone container:

```bash
docker build -t orchestrator .
docker run --rm -p 8080:8080 -p 8090:8090 -e API_WRITE_TOKEN=change-me orchestrator
```

ROS2 bridge container:

```bash
docker build -f Dockerfile.ros2 -t orchestrator-ros2 .
docker run --rm -p 8080:8080 -p 8090:8090 -e API_WRITE_TOKEN=change-me orchestrator-ros2
```

Because Docker defaults bind the Types API to `0.0.0.0`, `API_WRITE_TOKEN` is required.

Saved definitions are persisted under `./custom_types/<package>/msg/*.msg` and loaded into runtime parsing immediately.

Client sync helpers
-------------------

JavaScript (`clientjs/Client.js`):

- `syncTypesFromServer({ apiBase, since, token })`
- `syncTypesToServer(types, { apiBase, token })`
- `Client` instance methods with the same names are also available.

Python (`client/client.py`):

- `sync_types_from_server(api_base="http://localhost:8090", since=None, token=None)`
- `sync_types_to_server(type_definitions, api_base="http://localhost:8090", token=None)`
- `sync_types_folder_to_server(folder, api_base="http://localhost:8090", token=None)`

`clientjs/test.js` now pulls message definitions from the REST API before subscribing.

Browser UI overrides (optional):

```html
<script>
	window.ORCHESTRATOR_CONFIG = {
		wsPort: 8080,
		apiPort: 8090,
		writeToken: null,
	};
</script>
```

Publish payload shape for custom messages:

- Use Python dictionaries keyed by field name.
- For arrays, pass Python lists (`uint8[]`/`byte[]` can be `bytes`/`bytearray`).

Example:

```python
import serialization as s

s.load_message_root("./messages")
encoded = s.encode("sensor_msgs/PointCloud2", {
		"height": 1,
		"width": 100,
		"fields": [],
		"is_bigendian": False,
		"point_step": 16,
		"row_step": 1600,
		"data": b"...",
		"is_dense": True,
})
```

This README is based on the behavior of `Client.js`, `client/client.py`, and the server started by running `main.py`.


- TODO: Add optional JS custom-message codec generation from `.msg` files.