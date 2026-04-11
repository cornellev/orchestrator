Orchestrator WebSocket Server
=============================

This project provides a small WebSocket server and matching clients (JavaScript and Python) for publishing and subscribing to typed topics, inspired by simple ROS-style messaging. The binary protocol is shared between:

- The server started by running `main.py`.
- The browser/Node client in `clientjs/Client.js`.
- The Python client in `client/client.py`.

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

Both the JavaScript `Client` and Python `OrchestratorClient` support the same high-level operations:

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