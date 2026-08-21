import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
	0x84: "error",
}


class ClientStoppedError(RuntimeError):
	"""Raised when an operation is aborted because the client was stopped."""


class ClientConnectionError(RuntimeError):
	"""Raised when the client cannot establish or maintain a connection."""


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


@dataclass
class ProtocolErrorInfo:
	code: int
	message: str


def _build_topic_data(topic: str, type_str: str, data) -> bytes:
	payload = s.encode(type_str, data)
	encoded_name = s.encode_topic_name(topic)
	return bytes([len(encoded_name)]) + encoded_name + payload


def _parse_topic_info(buf: memoryview, offset: int) -> Tuple[TopicInfo, int]:
	if offset + 7 > len(buf):
		raise ValueError("Truncated topic info header")
	topic_id = int.from_bytes(buf[offset : offset + 4], byteorder="big")
	type_byte = buf[offset + 4]
	dynamic_len = int.from_bytes(buf[offset + 5 : offset + 7], byteorder="little")
	dynamic_start = offset + 7
	dynamic_end = dynamic_start + dynamic_len
	if dynamic_end + 5 > len(buf):
		raise ValueError("Truncated topic info payload")

	if type_byte == s.DYNAMIC_TYPE_BYTE:
		type_str = bytes(buf[dynamic_start:dynamic_end]).decode("utf-8")
	else:
		type_str = s.typeFromByte(type_byte)

	count = int.from_bytes(buf[dynamic_end : dynamic_end + 4], byteorder="little")
	name_len = buf[dynamic_end + 4]
	start = dynamic_end + 5
	end = start + name_len
	if end > len(buf):
		raise ValueError("Truncated topic name")
	name = bytes(buf[start:end]).decode("utf-8")
	return TopicInfo(topic_id=topic_id, type_str=type_str, count=count, name=name), end


def _parse_big_update(buf: memoryview) -> Dict[str, Tuple[str, object]]:
	if len(buf) < 4:
		raise ValueError("Truncated big_update")
	total_topics = int.from_bytes(buf[0:4], byteorder="little")
	offset = 4
	results: Dict[str, Tuple[str, object]] = {}
	for _ in range(total_topics):
		if offset >= len(buf):
			raise ValueError("Truncated big_update topic entry")
		name_len = buf[offset]
		if offset + 1 + name_len > len(buf):
			raise ValueError("Truncated big_update topic name")
		name = bytes(buf[offset + 1 : offset + 1 + name_len]).decode("utf-8")
		data_offset = offset + 1 + name_len
		if data_offset + 5 > len(buf):
			raise ValueError("Truncated big_update typed payload")
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


def _parse_error(buf: memoryview) -> ProtocolErrorInfo:
	if len(buf) < 4:
		raise ValueError("Truncated error response")
	code = int.from_bytes(buf[0:2], byteorder="little")
	length = int.from_bytes(buf[2:4], byteorder="little")
	if 4 + length > len(buf):
		raise ValueError("Truncated error message")
	message = bytes(buf[4 : 4 + length]).decode("utf-8", errors="replace")
	return ProtocolErrorInfo(code=code, message=message)


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
		on_error: Optional[Callable[[ProtocolErrorInfo], Awaitable[None] | None]] = None,
	) -> None:
		self.uri = uri
		self.reconnect = reconnect
		self.backoff = backoff
		self.backoff_max = backoff_max

		self._ws = None
		self._task: Optional[asyncio.Task] = None
		self._connected = asyncio.Event()
		self._stop = asyncio.Event()
		self._runner_done = asyncio.Event()
		self._runner_done.set()
		self._last_error: Optional[BaseException] = None

		self._on_echo = on_echo
		self._on_new_topic = on_new_topic
		self._on_update = on_update
		self._on_big_update = on_big_update
		self._on_error = on_error

		self._want_subscribe = False

	def load_custom_topics(self, folder: str | Path) -> list[str]:
		"""Load ROS-style `.msg` schemas from a `messages/`-like folder.

		Expected layout:
		- <folder>/<package>/msg/*.msg

		This registers message schemas with the shared `serialization` module so
		`publish()` can encode dynamic message types.
		"""
		return s.load_message_root(Path(folder))

	# Alias: some callers think in terms of "types" rather than "topics".
	def load_custom_types(self, folder: str | Path) -> list[str]:
		return self.load_custom_topics(folder)

	async def start(self, auto_subscribe: bool = True) -> None:
		self._stop.clear()
		self._last_error = None
		self._want_subscribe = auto_subscribe
		if self._task is None or self._task.done():
			self._runner_done.clear()
			self._task = asyncio.create_task(self._runner())
		await self._wait_connected()

	async def stop(self) -> None:
		self._stop.set()
		self._connected.clear()
		ws = self._ws
		self._ws = None
		if ws is not None:
			try:
				await ws.close()
			except Exception:
				pass
		if self._task is not None:
			try:
				await self._task
			except Exception:
				pass
			self._task = None
		self._runner_done.set()

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

	async def _wait_connected(self) -> None:
		while True:
			if self._connected.is_set() and self._ws is not None:
				return
			if self._stop.is_set():
				raise ClientStoppedError("Client stopped before connecting")
			if self._runner_done.is_set():
				if self._last_error is not None:
					raise ClientConnectionError(f"Failed to connect: {self._last_error}") from self._last_error
				raise ClientConnectionError("Failed to connect")
			waiters = [
				asyncio.create_task(self._connected.wait()),
				asyncio.create_task(self._stop.wait()),
				asyncio.create_task(self._runner_done.wait()),
			]
			done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
			for task in pending:
				task.cancel()
			for task in done:
				task.result()

	async def _runner(self) -> None:
		delay = self.backoff
		try:
			while not self._stop.is_set():
				try:
					async with connect(self.uri) as ws:
						self._ws = ws
						self._last_error = None
						self._connected.set()
						delay = self.backoff
						if self._want_subscribe:
							await self.subscribe()
						await self._receive_loop(ws)
				except Exception as exc:  # pragma: no cover - network failures
					self._last_error = exc
					self._connected.clear()
					self._ws = None
					if not self.reconnect or self._stop.is_set():
						break
					try:
						await asyncio.wait_for(self._stop.wait(), timeout=delay)
						break
					except asyncio.TimeoutError:
						pass
					delay = min(self.backoff_max, delay * 2)
		finally:
			self._connected.clear()
			self._ws = None
			self._runner_done.set()

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
			elif kind == "error":
				info = _parse_error(payload)
				if self._on_error:
					await maybe_await(self._on_error(info))
			else:
				raise ValueError(f"Unknown response opcode: {code}")
		self._connected.clear()
		self._ws = None

	async def _send(self, data: bytes) -> None:
		await self._wait_connected()
		if self._stop.is_set():
			raise ClientStoppedError("Client stopped")
		if not self._ws:
			raise ClientConnectionError("WebSocket not connected")
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


def _http_json(method: str, url: str, body: Optional[dict] = None, token: Optional[str] = None) -> dict:
	data = None
	headers = {}
	if body is not None:
		data = json.dumps(body).encode("utf-8")
		headers["Content-Type"] = "application/json"
	if token:
		headers["Authorization"] = f"Bearer {token}"

	req = Request(url, data=data, headers=headers, method=method)
	with urlopen(req, timeout=10) as response:
		raw = response.read().decode("utf-8")
		return json.loads(raw)


def _collect_msg_definitions(folder: Path) -> Dict[str, str]:
	if not folder.exists() or not folder.is_dir():
		raise FileNotFoundError(folder)

	result: Dict[str, str] = {}
	for package_dir in sorted(folder.iterdir()):
		if not package_dir.is_dir():
			continue
		msg_dir = package_dir / "msg"
		if not msg_dir.is_dir():
			continue
		for msg_file in sorted(msg_dir.glob("*.msg")):
			type_name = f"{package_dir.name}/{msg_file.stem}"
			result[type_name] = msg_file.read_text(encoding="utf-8")
	return result


async def sync_types_from_server(
	api_base: str = "http://localhost:8090",
	since: Optional[str] = None,
	token: Optional[str] = None,
) -> Dict[str, str]:
	def _work() -> Dict[str, str]:
		query = ""
		if since:
			query = "?" + urlencode({"since": since})
		payload = _http_json("GET", f"{api_base.rstrip('/')}/api/types{query}", token=token)
		loaded: Dict[str, str] = {}
		for item in payload.get("types", []):
			type_name = item.get("type")
			definition = item.get("definition")
			if not isinstance(type_name, str) or not isinstance(definition, str):
				continue
			s.load_message_definition(type_name, definition)
			loaded[type_name] = definition
		return loaded

	return await asyncio.to_thread(_work)


async def sync_types_to_server(
	type_definitions: Dict[str, str],
	api_base: str = "http://localhost:8090",
	token: Optional[str] = None,
) -> dict:
	def _work() -> dict:
		payload = {
			"types": [
				{"type": type_name, "definition": definition}
				for type_name, definition in type_definitions.items()
			]
		}
		return _http_json("POST", f"{api_base.rstrip('/')}/api/types/sync", payload, token=token)

	return await asyncio.to_thread(_work)


async def sync_types_folder_to_server(
	folder: str | Path,
	api_base: str = "http://localhost:8090",
	token: Optional[str] = None,
) -> dict:
	definitions = await asyncio.to_thread(_collect_msg_definitions, Path(folder))
	return await sync_types_to_server(definitions, api_base=api_base, token=token)
