from __future__ import annotations

import hashlib
import importlib
import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import serialization as s

# Named zenoh_bridge.py so `import zenoh` resolves to eclipse-zenoh, not this module.

_FORBIDDEN_KEY_CHARS = frozenset("*?$#")
_ORCH_MIME = "application/octet-stream"
_JSON_MIME = "application/json"
_VALID_MODES = frozenset({"peer", "client"})
_VALID_PAYLOADS = frozenset({"orch", "json"})


def normalize_key_prefix(prefix: str) -> str:
	cleaned = (prefix or "").strip().strip("/")
	if not cleaned:
		raise ValueError("Zenoh key prefix must be non-empty")
	if any(ch in _FORBIDDEN_KEY_CHARS for ch in cleaned):
		raise ValueError(f"Zenoh key prefix contains wildcard characters: {prefix!r}")
	return cleaned


def topic_to_key(topic: str, prefix: str = "orch") -> str:
	if not topic or not str(topic).strip():
		raise ValueError("Topic name must be non-empty")
	stripped = str(topic).lstrip("/")
	if not stripped:
		raise ValueError(f"Topic name is empty after stripping slashes: {topic!r}")
	if any(ch in _FORBIDDEN_KEY_CHARS for ch in stripped):
		raise ValueError(f"Topic name contains Zenoh wildcard characters: {topic!r}")
	return f"{normalize_key_prefix(prefix)}/{stripped}"


def key_to_topic(key: str, prefix: str = "orch") -> Optional[str]:
	cleaned_prefix = normalize_key_prefix(prefix)
	key_str = str(key).strip().lstrip("/")
	expected = cleaned_prefix + "/"
	if not key_str.startswith(expected):
		return None
	rest = key_str[len(expected) :]
	if not rest or rest.startswith("@") or any(ch in _FORBIDDEN_KEY_CHARS for ch in rest):
		return None
	return "/" + rest


def encoding_string(payload_mode: str, orch_type: str) -> str:
	if payload_mode not in _VALID_PAYLOADS:
		raise ValueError(f"Unsupported Zenoh payload mode {payload_mode!r}")
	if not orch_type:
		raise ValueError("Orchestrator type is required for Zenoh encoding schema")
	mime = _JSON_MIME if payload_mode == "json" else _ORCH_MIME
	return f"{mime};{orch_type}"


def parse_encoding(encoding: str) -> tuple[str, Optional[str]]:
	text = str(encoding or "").strip()
	if not text:
		return "", None
	if ";" in text:
		mime, schema = text.split(";", 1)
		schema = schema.strip()
		return mime.strip(), schema or None
	return text, None


def payload_mode_from_mime(mime: str) -> str:
	normalized = (mime or "").strip().lower()
	if normalized == _JSON_MIME or normalized.endswith("/json"):
		return "json"
	return "orch"


def _json_default(obj: Any) -> Any:
	if isinstance(obj, (bytes, bytearray)):
		return list(obj)
	raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def encode_json_value(value: Any) -> bytes:
	return json.dumps(value, default=_json_default, separators=(",", ":")).encode("utf-8")


def decode_json_value(payload: bytes, orch_type: str) -> Any:
	value = json.loads(payload.decode("utf-8"))
	return _coerce_json_value(orch_type, value)


def _coerce_json_value(orch_type: str, value: Any) -> Any:
	if orch_type == "std_msgs/Byte":
		if isinstance(value, list):
			return bytes(value)
		if isinstance(value, int):
			return bytes([value & 0xFF])
	if orch_type == "std_msgs/ColorRGBA" and isinstance(value, list) and len(value) == 4:
		return tuple(float(x) for x in value)
	return value


def encode_sample_payload(orch_type: str, value: Any, mode: str) -> tuple[bytes, str]:
	enc = encoding_string(mode, orch_type)
	if mode == "json":
		return encode_json_value(value), enc
	return s.encode(orch_type, value), enc


def decode_sample_payload(
	payload: bytes,
	encoding: str,
	*,
	fallback_mode: str = "orch",
) -> tuple[str, Any]:
	mime, schema = parse_encoding(encoding)
	mode = payload_mode_from_mime(mime) if mime else fallback_mode
	data = payload if payload is not None else b""

	if mode == "json":
		if not schema:
			raise ValueError("JSON Zenoh sample is missing a type schema")
		return schema, decode_json_value(data, schema)

	if data:
		try:
			type_name, value = s.decode(data)
			return schema or type_name, value
		except Exception:
			if schema:
				return schema, s.decode_typed(schema, data)
			raise
	if schema:
		return schema, None
	raise ValueError("Empty orchestrator Zenoh sample with no type schema")


def sample_payload_bytes(payload: Any) -> bytes:
	if payload is None:
		return b""
	if isinstance(payload, (bytes, bytearray)):
		return bytes(payload)
	to_bytes = getattr(payload, "to_bytes", None)
	if callable(to_bytes):
		return bytes(to_bytes())
	return bytes(payload)


def _orch_value_hash(type_str: str, value: Any) -> bytes:
	payload = s.encode(type_str, value)
	return hashlib.blake2b(payload, digest_size=16).digest()


def _is_delete_kind(kind: Any) -> bool:
	if kind is None:
		return False
	name = getattr(kind, "name", None)
	if name == "DELETE":
		return True
	return str(kind).endswith("DELETE")


@dataclass(frozen=True)
class ZenohBridgeConfig:
	key_prefix: str = "orch"
	mode: str = "peer"
	connect: tuple[str, ...] = ()
	listen: tuple[str, ...] = ()
	config_file: Optional[str] = None
	payload: str = "orch"
	loopback_ttl_sec: float = 0.35

	def __post_init__(self) -> None:
		object.__setattr__(self, "key_prefix", normalize_key_prefix(self.key_prefix))
		mode = (self.mode or "peer").strip().lower()
		if mode not in _VALID_MODES:
			raise ValueError(f"ZENOH_MODE must be one of {sorted(_VALID_MODES)}, got {self.mode!r}")
		object.__setattr__(self, "mode", mode)
		payload = (self.payload or "orch").strip().lower()
		if payload not in _VALID_PAYLOADS:
			raise ValueError(f"ZENOH_PAYLOAD must be one of {sorted(_VALID_PAYLOADS)}, got {self.payload!r}")
		object.__setattr__(self, "payload", payload)
		if self.config_file is not None:
			path = str(self.config_file).strip()
			object.__setattr__(self, "config_file", path or None)


def build_session_config(zenoh_mod: Any, config: ZenohBridgeConfig) -> Any:
	if config.config_file:
		return zenoh_mod.Config.from_file(config.config_file)

	conf = zenoh_mod.Config()
	conf.insert_json5("mode", json.dumps(config.mode))
	if config.connect:
		conf.insert_json5("connect/endpoints", json.dumps(list(config.connect)))
	if config.listen:
		conf.insert_json5("listen/endpoints", json.dumps(list(config.listen)))
	return conf


class ZenohBridge:
	"""Native Zenoh <-> orchestrator topic bridge (topics only).

	- Subscribes to ``{prefix}/**`` and mirrors inbound puts into ROSSim.
	- Forwards WebSocket publishes as Zenoh puts using orchestrator encoding.
	"""

	def __init__(self, *, sim, config: Optional[ZenohBridgeConfig] = None):
		self.sim = sim
		self.config = config or ZenohBridgeConfig()

		self._thread: Optional[threading.Thread] = None
		self._stop = threading.Event()
		self._ready = threading.Event()
		self._start_error: Optional[BaseException] = None

		self._publish_queue: "queue.Queue[tuple[str, str, Any]]" = queue.Queue()
		self._recent: dict[str, tuple[float, bytes]] = {}
		self._recent_lock = threading.Lock()

		self._publishers: dict[str, Any] = {}
		self._session = None
		self._subscriber = None
		self._zenoh = None

	def start(self) -> None:
		if self._thread and self._thread.is_alive():
			return
		try:
			importlib.import_module("zenoh")
		except Exception as exc:
			raise ImportError(
				"Zenoh bridge enabled but eclipse-zenoh is not available. "
				"Install it with: pip install -r requirements-zenoh.txt"
			) from exc

		self._stop.clear()
		self._ready.clear()
		self._start_error = None
		self._thread = threading.Thread(target=self._run, name="ZenohBridge", daemon=True)
		self._thread.start()
		if not self._ready.wait(timeout=10.0):
			if self._start_error is not None:
				raise RuntimeError(f"Zenoh bridge failed to start: {self._start_error}") from self._start_error
			raise RuntimeError("Zenoh bridge failed to start (timeout waiting for session)")

	def stop(self, *, drain_timeout_sec: float = 0.5) -> None:
		deadline = time.monotonic() + max(0.0, drain_timeout_sec)
		while time.monotonic() < deadline and not self._publish_queue.empty():
			if self._session is not None:
				try:
					self._drain_publish_queue(max_items=50)
				except Exception:
					break
			else:
				break
			time.sleep(0.01)

		self._stop.set()
		if self._thread and self._thread.is_alive():
			self._thread.join(timeout=5.0)
		self._thread = None

	def enqueue_ws_publish(self, topic: str, orch_type: str, value: Any) -> None:
		try:
			h = _orch_value_hash(orch_type, value)
		except Exception:
			h = b""
		if h:
			with self._recent_lock:
				self._recent[topic] = (time.monotonic(), h)
		self._publish_queue.put((topic, orch_type, value))

	def _run(self) -> None:
		try:
			zenoh = importlib.import_module("zenoh")
			self._zenoh = zenoh
			try:
				init_log = getattr(zenoh, "init_log_from_env_or", None)
				if callable(init_log):
					init_log("error")
			except Exception:
				pass

			conf = build_session_config(zenoh, self.config)
			self._session = zenoh.open(conf)
			sub_key = f"{self.config.key_prefix}/**"
			self._subscriber = self._session.declare_subscriber(sub_key, self._on_sample)
			self._ready.set()
			while not self._stop.is_set():
				self._drain_publish_queue()
				self._stop.wait(0.02)
		except Exception as exc:
			self._start_error = exc
			self._ready.set()
			if self._stop.is_set():
				return
			raise
		finally:
			self._cleanup_session()

	def _cleanup_session(self) -> None:
		try:
			if self._subscriber is not None:
				undeclare = getattr(self._subscriber, "undeclare", None)
				if callable(undeclare):
					undeclare()
		except Exception:
			pass
		self._subscriber = None

		for pub in list(self._publishers.values()):
			try:
				undeclare = getattr(pub, "undeclare", None)
				if callable(undeclare):
					undeclare()
			except Exception:
				pass
		self._publishers.clear()

		try:
			if self._session is not None:
				close = getattr(self._session, "close", None)
				if callable(close):
					close()
		except Exception:
			pass
		self._session = None
		self._zenoh = None

	def _on_sample(self, sample: Any) -> None:
		if _is_delete_kind(getattr(sample, "kind", None)):
			return

		try:
			key = str(getattr(sample, "key_expr", ""))
			topic = key_to_topic(key, self.config.key_prefix)
			if topic is None:
				return

			encoding = str(getattr(sample, "encoding", "") or "")
			payload = sample_payload_bytes(getattr(sample, "payload", None))
			orch_type, value = decode_sample_payload(
				payload,
				encoding,
				fallback_mode=self.config.payload,
			)
		except Exception as exc:
			print(f"Zenoh->WS conversion failed for sample: {exc}")
			return

		try:
			h = _orch_value_hash(orch_type, value)
		except Exception:
			h = b""

		if h:
			with self._recent_lock:
				recent = self._recent.get(topic)
				if recent is not None:
					t0, h0 = recent
					if (time.monotonic() - t0) <= self.config.loopback_ttl_sec and h0 == h:
						return

		existing = None
		topics = getattr(self.sim, "topics", None)
		if isinstance(topics, dict):
			existing = topics.get(topic)
		if existing is not None and existing != orch_type:
			print(
				f"Zenoh->WS type mismatch for {topic}: existing={existing}, sample={orch_type}"
			)
			return

		self.sim.add_topic(topic, orch_type)
		self.sim.update_topic(topic, value)

	def _drain_publish_queue(self, *, max_items: int = 200) -> int:
		if self._session is None or self._zenoh is None:
			return 0

		zenoh = self._zenoh
		drained = 0
		while drained < max_items:
			try:
				topic, orch_type, value = self._publish_queue.get_nowait()
			except queue.Empty:
				break

			drained += 1
			try:
				key = topic_to_key(topic, self.config.key_prefix)
				payload, enc_str = encode_sample_payload(orch_type, value, self.config.payload)
				pub = self._publishers.get(topic)
				if pub is None:
					pub = self._session.declare_publisher(key)
					self._publishers[topic] = pub
				pub.put(payload, encoding=zenoh.Encoding(enc_str))
			except Exception as exc:
				print(f"WS->Zenoh publish failed for {topic} ({orch_type}): {exc}")
		return drained
