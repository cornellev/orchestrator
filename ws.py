import asyncio
import struct
import threading
from websockets.asyncio.server import serve
from typing import Optional
import serialization as s
import names

methods = {
    0x00: "echo",
    0x01: "subscribe",
    0x02: "publish",
    0x03: "request_all"
}

responses = {
    "echo": 0x80,
    "echo_new": 0x81,  # new topic added since last echo
    "update": 0x82,  # topic data update
    "big_update": 0x83,  # lots of topic updates (e.g. after request_all)
    "error": 0x84,  # protocol / application error
}

PROTOCOL_CLOSE_CODE = 1002


class ProtocolError(ValueError):
    """Raised for malformed or rejected client frames."""


def encode_error(message: str, code: int = 1) -> bytes:
    text = (message or "protocol error").encode("utf-8")
    if len(text) > 1024:
        text = text[:1024]
    payload = bytearray()
    payload.append(responses["error"])
    payload.extend(int(code).to_bytes(2, byteorder="little", signed=False))
    payload.extend(len(text).to_bytes(2, byteorder="little"))
    payload.extend(text)
    return bytes(payload)


def decode_error(payload: bytes | memoryview) -> tuple[int, str]:
    view = memoryview(payload)
    if len(view) < 4:
        raise ProtocolError("Truncated error response")
    code = int.from_bytes(view[0:2], byteorder="little")
    length = int.from_bytes(view[2:4], byteorder="little")
    if 4 + length > len(view):
        raise ProtocolError("Truncated error message")
    message = bytes(view[4 : 4 + length]).decode("utf-8", errors="replace")
    return code, message


class WebSocketServer:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        on_client_publish=None,
    ) -> None:
        self.host = host
        self.port = port

        self.loop: Optional[asyncio.AbstractEventLoop] = loop
        self._on_client_publish = on_client_publish

        self.clients = {}  # maps connected clients with last interaction time
        self.sim: Optional[ROSSim] = None

        self.nicknames = {}  # maps client websockets to random nicknames for easier debugging

    def _ensure_sim(self) -> None:
        if self.sim is not None:
            return
        if self.loop is None:
            # Must be called while an event loop is running.
            self.loop = asyncio.get_running_loop()
        self.sim = ROSSim(self.broadcast, loop=self.loop, on_client_publish=self._on_client_publish)

    async def broadcast(self, data: bytes, targets=None):
        # use a copy to avoid RuntimeError if clients disconnect during iteration
        if targets is None:
            targets = list(self.clients.keys())
        for client in list(targets):
            try:
                await client.send(data)
            except Exception as e:
                print(f"Error sending to client: {e}")
                self.clients.pop(client, None)  # remove disconnected client

    async def handler(self, websocket):
        self._ensure_sim()
        self.clients[websocket] = asyncio.get_event_loop().time()  # store the time of connection
        nickname = names.generate_name()
        self.nicknames[websocket] = nickname
        print(f"Client connected: {nickname} ({websocket.remote_address})")
        try:
            try:
                async for message in websocket:
                    if not message:
                        await websocket.send(encode_error("Empty WebSocket frame", code=100))
                        await websocket.close(code=PROTOCOL_CLOSE_CODE, reason="empty frame")
                        break

                    # first byte is operation code (echo=0x00, subscribe=0x01, publish=0x02, request_all=0x03)
                    op_code = message[0]
                    op = methods.get(op_code, None)
                    if op is None:
                        await websocket.send(encode_error(f"Unknown operation code: {op_code}", code=101))
                        continue

                    try:
                        await self.sim.handleMethod(op, message[1:], websocket)
                    except ProtocolError as exc:
                        await websocket.send(encode_error(str(exc), code=102))
                        await websocket.close(code=PROTOCOL_CLOSE_CODE, reason=str(exc)[:120])
                        break
                    except (ValueError, struct.error) as exc:
                        await websocket.send(encode_error(f"Malformed publish payload: {exc}", code=103))
                        await websocket.close(code=PROTOCOL_CLOSE_CODE, reason="malformed payload")
                        break
            except Exception as exc:
                from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
                if not isinstance(exc, (ConnectionClosedOK, ConnectionClosedError)):
                    raise
        finally:
            self.clients.pop(websocket, None)
            if self.sim is not None:
                self.sim.unsubscribe(websocket)
            print(f"Client disconnected: {nickname} ({websocket.remote_address})")
            # remove nickname mapping
            self.nicknames.pop(websocket, None)

    async def run(self) -> None:
        self._ensure_sim()
        async with serve(self.handler, self.host, self.port):
            # Run forever until cancelled (e.g. Ctrl+C in main)
            await asyncio.Future()


def construct_topicData(topic_name: str, type_str: str, data):
    # returns [name_len][name...][type byte][count (4 bytes)][data...]
    if data is None:
        data = bytes([s.type_encoder(type_str)]) + (0).to_bytes(4, byteorder='little')
    else:
        data = s.encode(type_str, data)
    pre_topic = s.encode_topic_name(topic_name)
    topic_len = len(pre_topic)

    return bytes([topic_len]) + pre_topic + data


def decode_topicData(topic_data: bytes):
    if not topic_data:
        raise ProtocolError("Empty publish payload")
    topic_len = topic_data[0]
    if topic_len > s.MAX_TOPIC_NAME_LEN:
        raise ProtocolError(f"Topic name length {topic_len} exceeds {s.MAX_TOPIC_NAME_LEN}")
    if 1 + topic_len > len(topic_data):
        raise ProtocolError("Truncated topic name")
    try:
        topic_name = topic_data[1:1 + topic_len].decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"Invalid UTF-8 topic name: {exc}") from exc
    try:
        type_str, data = s.decode(topic_data[1 + topic_len:])
    except Exception as exc:
        raise ProtocolError(str(exc)) from exc
    return topic_name, type_str, data


def encode_topic_value(type_str: str, data):
    if data is None:
        return bytes([s.type_encoder(type_str)]) + (0).to_bytes(4, byteorder='little')
    return s.encode(type_str, data)


class ROSSim:
    def __init__(self, broadcaster, *, loop: asyncio.AbstractEventLoop, on_client_publish=None):
        self.broadcast = broadcaster
        self.loop = loop
        self._loop_thread_id = threading.get_ident()
        self._on_client_publish = on_client_publish

        self.topics = {}  # topic_name -> type_str
        self.topic_order = []  # preserve insertion order
        self.data = {}

        self.topicMap = {}  # maps topic names to 4 bytes identifiers for efficient transmission over WebSocket
        self.counter = 0

        self.subscribers = set()  # websockets that have subscribed to topics

    def add_topic(self, topic_name: str, type_str: str):
        # Thread-safe: ROS callbacks may call this off the asyncio loop thread.
        if threading.get_ident() != self._loop_thread_id:
            self.loop.call_soon_threadsafe(self._add_topic, topic_name, type_str)
            return
        self._add_topic(topic_name, type_str)

    def _add_topic(self, topic_name: str, type_str: str):
        if topic_name in self.topics:
            return

        self.topics[topic_name] = type_str
        self.topic_order.append(topic_name)
        self.data[topic_name] = None

        self.counter += 1
        self.topicMap[topic_name] = self.counter.to_bytes(4, byteorder='big')

        asyncio.create_task(self.notifyNewTopic(topic_name))

    def update_topic(self, topic_name: str, data):
        # Thread-safe: ROS callbacks may call this off the asyncio loop thread.
        if threading.get_ident() != self._loop_thread_id:
            self.loop.call_soon_threadsafe(self._update_topic, topic_name, data)
            return
        self._update_topic(topic_name, data)

    def _update_topic(self, topic_name: str, data):
        if topic_name in self.topics:
            self.data[topic_name] = data
            asyncio.create_task(self.notifyTopicUpdate(topic_name))
        else:
            raise ValueError(f"Topic '{topic_name}' not found in ROSSim.")

    def get_topic_data(self, topic_name: str):
        if topic_name in self.topics:
            return self.data[topic_name]
        else:
            raise ValueError(f"Topic '{topic_name}' not found in ROSSim.")

    def get_topic_type(self, topic_name: str):
        if topic_name in self.topics:
            return self.topics[topic_name]
        raise ValueError(f"Topic '{topic_name}' not found in ROSSim.")

    def serializeTopic(self, topic_name: str):
        type_str = self.get_topic_type(topic_name)
        data = self.get_topic_data(topic_name)
        return construct_topicData(topic_name, type_str, data)

    async def handleMethod(self, method, data, websocket):
        if method == "echo":
            await self.handleEchoTopics(websocket)

        if method == "subscribe":
            self.subscribers.add(websocket)

        if method == "publish":
            topic_name, type_str, decoded = decode_topicData(data)
            if topic_name not in self.topics:
                self.add_topic(topic_name, type_str)
            else:
                existing_type = self.topics.get(topic_name)
                if existing_type != type_str:
                    await websocket.send(
                        encode_error(
                            f"Type mismatch for topic '{topic_name}': existing={existing_type}, published={type_str}",
                            code=104,
                        )
                    )
                    return

            if self._on_client_publish is not None:
                try:
                    self._on_client_publish(topic_name, type_str, decoded)
                except Exception as exc:
                    print(f"on_client_publish hook error for topic '{topic_name}': {exc}")

            self.update_topic(topic_name, decoded)

        if method == "request_all":
            # send all topic data to client
            payload = bytearray()
            payload.append(responses["big_update"])
            payload.extend(len(self.topic_order).to_bytes(4, byteorder='little'))

            for topic_name in self.topic_order:
                payload.extend(self.serializeTopic(topic_name))
            await websocket.send(bytes(payload))

    def smallTopicInfoMsg(self, topic_name: str):
        type_str = self.get_topic_type(topic_name)
        data = self.get_topic_data(topic_name)
        type_byte = s.type_encoder(type_str)
        dynamic_type_name = b""
        if type_byte == s.DYNAMIC_TYPE_BYTE:
            dynamic_type_name = type_str.encode('utf-8')
        count = 0
        if data is not None:
            encoded = s.encode(type_str, data)
            count = int.from_bytes(encoded[1:5], byteorder='little')

        topic = s.encode_topic_name(topic_name)
        d = bytearray()
        d.extend(self.topicMap[topic_name])  # topic identifier (4 bytes)
        d.append(type_byte)  # type byte
        d.extend(len(dynamic_type_name).to_bytes(2, byteorder='little'))  # optional dynamic type name length
        d.extend(dynamic_type_name)  # optional dynamic type name bytes
        d.extend(count.to_bytes(4, byteorder='little'))  # count
        d.extend(len(topic).to_bytes(1, byteorder='little'))  # topic name length
        d.extend(topic)  # topic name data
        return bytes(d)

    """
    Echo method sends all current topics and their types + assignments to the client.
    NO DATA IS SENT.
    """
    async def handleEchoTopics(self, websocket):
        payload = bytearray()
        payload.append(responses["echo"])
        payload.extend(len(self.topic_order).to_bytes(4, byteorder='little'))  # number of topics

        for topic_name in self.topic_order:
            payload.extend(self.smallTopicInfoMsg(topic_name))

        await websocket.send(bytes(payload))

    async def notifyNewTopic(self, topic_name: str):
        # send new topic info to all subscribers
        payload = bytearray()
        payload.append(responses["echo_new"])
        payload.extend(self.smallTopicInfoMsg(topic_name))

        await self.broadcast(bytes(payload), targets=self.subscribers)

    async def notifyTopicUpdate(self, topic_name: str):
        # send topic update to all subscribers
        payload = bytearray()
        payload.append(responses["update"])
        payload.extend(self.smallTopicInfoMsg(topic_name))
        payload.extend(encode_topic_value(self.get_topic_type(topic_name), self.get_topic_data(topic_name)))

        await self.broadcast(bytes(payload), targets=self.subscribers)

    def unsubscribe(self, websocket):
        self.subscribers.discard(websocket)
