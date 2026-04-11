import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from websockets.asyncio.client import connect

import serialization as s


# Operation and response codes defined by the server
OP_CODES = {
	"echo": 0x00,
	"subscribe": 0x01,
	"publish": 0x02,
	"request_all": 0x03,
}

RESP_CODES = {
	0x80: "echo",
	0x81: "echo_new",
	0x82: "update",
	0x83: "big_update",
}


@dataclass
class TopicInfo:
	topic_id: int
	type_str: str
	count: int
	name: str


@dataclass
class TopicUpdate:
	topic_id: int
	type_str: str
	count: int
	name: str
	value: Any = None


def _build_topic_data(topic: str, type_str: str, data) -> bytes:
	payload = s.encode(type_str, data)
	encoded_name = topic.encode("utf-8")
	return bytes([len(encoded_name)]) + encoded_name + payload


def _parse_topic_info(buf: memoryview, offset: int) -> Tuple[TopicInfo, int]:
	topic_id = int.from_bytes(buf[offset : offset + 4], byteorder="big")
	type_byte = buf[offset + 4]
	dynamic_len = int.from_bytes(buf[offset + 5 : offset + 7], byteorder="little")
	dynamic_start = offset + 7
	dynamic_end = dynamic_start + dynamic_len

	if type_byte == s.DYNAMIC_TYPE_BYTE:
		type_str = bytes(buf[dynamic_start:dynamic_end]).decode("utf-8")
	else:
		type_str = s.typeFromByte(type_byte)

	count = int.from_bytes(buf[dynamic_end : dynamic_end + 4], byteorder="little")
	name_len = buf[dynamic_end + 4]
	start = dynamic_end + 5
	end = start + name_len
	name = bytes(buf[start:end]).decode("utf-8")
	return TopicInfo(topic_id=topic_id, type_str=type_str, count=count, name=name), end


def _parse_big_update(buf: memoryview) -> Dict[str, Tuple[str, object]]:
	total_topics = int.from_bytes(buf[0:4], byteorder="little")
	offset = 4
	results: Dict[str, Tuple[str, object]] = {}
	for _ in range(total_topics):
		name_len = buf[offset]
		name = bytes(buf[offset + 1 : offset + 1 + name_len]).decode("utf-8")
		data_offset = offset + 1 + name_len
		type_byte = buf[data_offset]
		count = int.from_bytes(buf[data_offset + 1 : data_offset + 5], byteorder="little")
		raw_value = bytes(buf[data_offset : data_offset + 5 + count])
		type_str, value = s.decode(raw_value)
		results[name] = (type_str, value)
		offset = data_offset + 5 + count
	return results


def _parse_update(buf: memoryview) -> TopicUpdate:
	info, offset = _parse_topic_info(buf, 0)
	value = None
	if offset < len(buf):
		type_str, value = s.decode(bytes(buf[offset:]))
		if type_str != info.type_str:
			raise ValueError(f"Mismatched update type for topic '{info.name}': {type_str} != {info.type_str}")
	return TopicUpdate(topic_id=info.topic_id, type_str=info.type_str, count=info.count, name=info.name, value=value)


class OrchestratorClient:
	"""
	Minimal reciprocal client that speaks the websocket protocol defined by the server
	without depending on the server implementation. Handles reconnection and
	exposes simple callbacks for server events.
	"""

	def __init__(
		self,
		uri: str = "ws://localhost:8080",
		reconnect: bool = True,
		backoff: float = 0.5,
		backoff_max: float = 10.0,
		on_echo: Optional[Callable[[Tuple[TopicInfo, ...]], Awaitable[None] | None]] = None,
		on_new_topic: Optional[Callable[[TopicInfo], Awaitable[None] | None]] = None,
		on_update: Optional[Callable[[TopicUpdate], Awaitable[None] | None]] = None,
		on_big_update: Optional[Callable[[Dict[str, Tuple[str, object]]], Awaitable[None] | None]] = None,
	) -> None:
		self.uri = uri
		self.reconnect = reconnect
		self.backoff = backoff
		self.backoff_max = backoff_max

		self._ws = None
		self._task: Optional[asyncio.Task] = None
		self._connected = asyncio.Event()
		self._stop = asyncio.Event()

		self._on_echo = on_echo
		self._on_new_topic = on_new_topic
		self._on_update = on_update
		self._on_big_update = on_big_update

		self._want_subscribe = False

	async def start(self, auto_subscribe: bool = True) -> None:
		self._stop.clear()
		self._want_subscribe = auto_subscribe
		if self._task is None or self._task.done():
			self._task = asyncio.create_task(self._runner())
		await self._connected.wait()

	async def stop(self) -> None:
		self._stop.set()
		if self._ws:
			await self._ws.close()
		if self._task:
			await self._task

	async def echo(self) -> None:
		await self._send(bytes([OP_CODES["echo"]]))

	async def subscribe(self) -> None:
		self._want_subscribe = True
		await self._send(bytes([OP_CODES["subscribe"]]))

	async def request_all(self) -> None:
		await self._send(bytes([OP_CODES["request_all"]]))

	async def publish(self, topic: str, type_str: str, data) -> None:
		payload = _build_topic_data(topic, type_str, data)
		await self._send(bytes([OP_CODES["publish"]]) + payload)

	async def _runner(self) -> None:
		delay = self.backoff
		while not self._stop.is_set():
			try:
				async with connect(self.uri) as ws:
					self._ws = ws
					self._connected.set()
					delay = self.backoff
					if self._want_subscribe:
						await self.subscribe()
					await self._receive_loop(ws)
			except Exception as exc:  # pragma: no cover - network failures
				self._connected.clear()
				self._ws = None
				if not self.reconnect or self._stop.is_set():
					break
				await asyncio.sleep(delay)
				delay = min(self.backoff_max, delay * 2)
		self._connected.clear()

	async def _receive_loop(self, ws) -> None:
		async for raw in ws:
			if not raw:
				continue
			code = raw[0]
			payload = memoryview(raw)[1:]
			kind = RESP_CODES.get(code)
			if kind == "echo":
				topics = await self._handle_echo(payload)
				if self._on_echo:
					await maybe_await(self._on_echo(topics))
			elif kind == "echo_new":
				info, _ = _parse_topic_info(payload, 0)
				if self._on_new_topic:
					await maybe_await(self._on_new_topic(info))
			elif kind == "update":
				info = _parse_update(payload)
				if self._on_update:
					await maybe_await(self._on_update(info))
			elif kind == "big_update":
				update = _parse_big_update(payload)
				if self._on_big_update:
					await maybe_await(self._on_big_update(update))
		self._connected.clear()
		self._ws = None

	async def _send(self, data: bytes) -> None:
		await self._connected.wait()
		if not self._ws:
			raise RuntimeError("WebSocket not connected")
		await self._ws.send(data)

	async def _handle_echo(self, payload: memoryview) -> Tuple[TopicInfo, ...]:
		total = int.from_bytes(payload[0:4], byteorder="little")
		offset = 4
		topics = []
		for _ in range(total):
			info, offset = _parse_topic_info(payload, offset)
			topics.append(info)
		return tuple(topics)


async def maybe_await(result) -> None:
	if asyncio.iscoroutine(result):
		await result