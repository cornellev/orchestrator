from __future__ import annotations

import hashlib
import importlib
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import serialization as s


_DEFAULT_EXCLUDE_TOPICS = {
	"/rosout",
	"/parameter_events",
	"/tf",
	"/tf_static",
}


def _ros_msg_to_orch_type(ros_type: str) -> str:
	# ROS2 topic types come like: "std_msgs/msg/String".
	# Orchestrator dynamic types expect: "std_msgs/String".
	if ros_type == "builtin_interfaces/msg/Time":
		return "time"
	if ros_type == "builtin_interfaces/msg/Duration":
		return "duration"
	return ros_type.replace("/msg/", "/")


def _orch_to_ros_msg_type(orch_type: str) -> str:
	if orch_type in {"time", "duration"}:
		return "builtin_interfaces/msg/Time" if orch_type == "time" else "builtin_interfaces/msg/Duration"
	if "/" not in orch_type:
		raise ValueError(f"Expected orchestrator type 'pkg/Msg', got '{orch_type}'")
	pkg, msg = orch_type.split("/", 1)
	return f"{pkg}/msg/{msg}"


_FIXED_ARRAY_RE = re.compile(r"^(?P<base>.+)\[(?P<n>\d+)\]$")
_SEQ_RE = re.compile(r"^sequence<(?P<inner>.+?)(?:,\s*\d+)?>$")


def _ros_field_to_orch(field_type: str) -> tuple[str, bool, Optional[int]]:
	"""Return (orch_type_name, is_array, fixed_len)."""
	t = field_type.strip()

	m = _FIXED_ARRAY_RE.match(t)
	if m:
		base = m.group("base")
		n = int(m.group("n"))
		base_orch, _, _ = _ros_field_to_orch(base)
		return base_orch, True, n

	m = _SEQ_RE.match(t)
	if m:
		inner = m.group("inner").strip()
		inner_orch, _, _ = _ros_field_to_orch(inner)
		return inner_orch, True, None

	# Bounded strings may appear like string<=10; treat as string.
	if t.startswith("string"):
		return "string", False, None

	# Scalars
	scalar_map = {
		"boolean": "bool",
		"bool": "bool",
		"float": "float32",
		"float32": "float32",
		"double": "float64",
		"float64": "float64",
		"int8": "int8",
		"uint8": "uint8",
		"octet": "uint8",
		"byte": "uint8",
		"int16": "int16",
		"uint16": "uint16",
		"int32": "int32",
		"uint32": "uint32",
		"int64": "int64",
		"uint64": "uint64",
		"char": "char",
		"wstring": "string",
		"wchar": "char",
	}

	if t in scalar_map:
		return scalar_map[t], False, None

	# Nested message
	if "/msg/" in t:
		return _ros_msg_to_orch_type(t), False, None

	# Fallback: if it looks like pkg/Msg already, keep it.
	if "/" in t:
		return t, False, None

	raise ValueError(f"Unsupported ROS field type '{field_type}'")


def _ensure_orch_schema_for_ros_msg(ros_msg_type: str, *, _visiting: Optional[set[str]] = None) -> str:
	"""Ensure a dynamic schema exists in serialization.message_registry for ros_msg_type."""
	orch_type = _ros_msg_to_orch_type(ros_msg_type)
	if orch_type in {"time", "duration"}:
		return orch_type

	# Built-in orchestrator types (std_msgs/String, etc.) are already supported as scalars.
	if orch_type in s.type_encoders:
		return orch_type

	if orch_type in s.message_registry:
		return orch_type

	visiting = _visiting or set()
	if ros_msg_type in visiting:
		return orch_type
	visiting.add(ros_msg_type)

	try:
		utilities = importlib.import_module("rosidl_runtime_py.utilities")
		get_message = getattr(utilities, "get_message")
	except Exception as exc:
		raise ImportError("ROS2 python libs not available (missing rosidl_runtime_py)") from exc

	msg_cls = get_message(ros_msg_type)
	fields = []
	for field_name, field_type in msg_cls.get_fields_and_field_types().items():
		base_orch, is_array, fixed_len = _ros_field_to_orch(field_type)
		# Recursively register nested types.
		if "/" in base_orch and base_orch not in {"time", "duration"} and base_orch.lower() not in s.BUILTIN_SCALARS:
			_ensure_orch_schema_for_ros_msg(_orch_to_ros_msg_type(base_orch), _visiting=visiting)
		fields.append(s.FieldDef(name=field_name, type_name=base_orch, is_array=is_array, array_len=fixed_len))

	s.register_message_type(orch_type, fields)
	return orch_type


def _orch_value_hash(type_str: str, value: Any) -> bytes:
	# Stable hash for loopback prevention
	payload = s.encode(type_str, value)
	return hashlib.blake2b(payload, digest_size=16).digest()


def _ros_instance_type(ros_msg: Any) -> Optional[str]:
	"""Best-effort conversion of a ROS2 message instance into a rosidl type string pkg/msg/Msg."""
	if ros_msg is None:
		return None
	cls = ros_msg.__class__
	mod = getattr(cls, "__module__", "")
	if not mod or ".msg" not in mod:
		return None
	pkg = mod.split(".", 1)[0]
	return f"{pkg}/msg/{cls.__name__}"


def _ros_std_msg_to_scalar(orch_type: str, ros_msg: Any) -> Any:
	# ROS std_msgs wrappers have different shapes; normalize to orchestrator built-in scalar expectations.
	if orch_type == "std_msgs/String":
		return getattr(ros_msg, "data", "")
	if orch_type in {
		"std_msgs/Int32",
		"std_msgs/Int64",
		"std_msgs/UInt32",
		"std_msgs/UInt64",
	}:
		return int(getattr(ros_msg, "data", 0))
	if orch_type in {"std_msgs/Float32", "std_msgs/Float64"}:
		return float(getattr(ros_msg, "data", 0.0))
	if orch_type == "std_msgs/Bool":
		return bool(getattr(ros_msg, "data", False))
	if orch_type == "std_msgs/Byte":
		b = int(getattr(ros_msg, "data", 0)) & 0xFF
		return bytes([b])
	if orch_type == "std_msgs/Char":
		c = int(getattr(ros_msg, "data", 0))
		try:
			return chr(c & 0xFF)
		except Exception:
			return "\x00"
	if orch_type == "std_msgs/ColorRGBA":
		return (
			float(getattr(ros_msg, "r", 0.0)),
			float(getattr(ros_msg, "g", 0.0)),
			float(getattr(ros_msg, "b", 0.0)),
			float(getattr(ros_msg, "a", 0.0)),
		)
	if orch_type == "std_msgs/Duration":
		data = getattr(ros_msg, "data", None)
		if data is not None and hasattr(data, "sec") and hasattr(data, "nanosec"):
			return int(data.sec) + int(data.nanosec) / 1e9
		return float(getattr(ros_msg, "data", 0.0))
	return getattr(ros_msg, "data", None)


def _ros_msg_to_value(ros_msg: Any) -> Any:
	"""Convert ROS2 message instance into orchestrator-compatible value (scalar or nested dict)."""
	if ros_msg is None:
		return None

	if hasattr(ros_msg, "sec") and hasattr(ros_msg, "nanosec") and not hasattr(ros_msg, "get_fields_and_field_types"):
		return {"sec": int(ros_msg.sec), "nsec": int(ros_msg.nanosec)}

	ros_type = _ros_instance_type(ros_msg)
	if ros_type is not None:
		orch_type = _ros_msg_to_orch_type(ros_type)
		if orch_type in s.type_encoders:
			return _ros_std_msg_to_scalar(orch_type, ros_msg)
		if orch_type == "time":
			return {"sec": int(getattr(ros_msg, "sec", 0)), "nsec": int(getattr(ros_msg, "nanosec", 0))}
		if orch_type == "duration":
			return int(getattr(ros_msg, "sec", 0)) + int(getattr(ros_msg, "nanosec", 0)) / 1e9

	# Non-message or primitive
	if not hasattr(ros_msg, "get_fields_and_field_types"):
		return ros_msg

	out: dict[str, Any] = {}
	for field_name in ros_msg.get_fields_and_field_types().keys():
		val = getattr(ros_msg, field_name)
		if isinstance(val, (bytes, bytearray)):
			out[field_name] = bytes(val)
		elif isinstance(val, (list, tuple)):
			out[field_name] = [_ros_msg_to_value(v) for v in val]
		else:
			out[field_name] = _ros_msg_to_value(val)
	return out


def _scalar_to_ros_std_msg(orch_type: str, value: Any, msg_cls: Any) -> Any:
	msg = msg_cls()
	if orch_type == "std_msgs/String":
		msg.data = "" if value is None else str(value)
		return msg
	if orch_type in {
		"std_msgs/Int32",
		"std_msgs/Int64",
		"std_msgs/UInt32",
		"std_msgs/UInt64",
	}:
		msg.data = int(value or 0)
		return msg
	if orch_type in {"std_msgs/Float32", "std_msgs/Float64"}:
		msg.data = float(value or 0.0)
		return msg
	if orch_type == "std_msgs/Bool":
		msg.data = bool(value)
		return msg
	if orch_type == "std_msgs/Byte":
		if isinstance(value, (bytes, bytearray)) and len(value) > 0:
			msg.data = int(value[0])
		else:
			msg.data = int(value or 0) & 0xFF
		return msg
	if orch_type == "std_msgs/Char":
		if isinstance(value, str) and value:
			msg.data = ord(value[0])
		else:
			msg.data = int(value or 0)
		return msg
	if orch_type == "std_msgs/ColorRGBA":
		if not isinstance(value, (tuple, list)) or len(value) != 4:
			raise ValueError("std_msgs/ColorRGBA expects 4-tuple (r,g,b,a)")
		msg.r = float(value[0])
		msg.g = float(value[1])
		msg.b = float(value[2])
		msg.a = float(value[3])
		return msg
	if orch_type == "std_msgs/Duration":
		data = getattr(msg, "data", None)
		seconds = float(value or 0.0)
		sec = int(seconds)
		nsec = int((seconds - sec) * 1e9)
		if data is not None and hasattr(data, "sec") and hasattr(data, "nanosec"):
			data.sec = sec
			data.nanosec = nsec
		else:
			msg.data = seconds
		return msg

	# Fallback: try data field
	if hasattr(msg, "data"):
		msg.data = value
	return msg


def _dict_to_ros_msg(msg_cls: Any, value: Any) -> Any:
	"""Convert nested dict payload into a ROS2 message instance."""
	msg = msg_cls()
	if value is None:
		return msg
	if not isinstance(value, dict):
		raise ValueError("ROS message publish expects dict payload")

	fields_and_types = msg_cls.get_fields_and_field_types()
	for field_name, field_type in fields_and_types.items():
		if field_name not in value:
			continue
		field_val = value[field_name]

		# Sequences and fixed arrays
		if _FIXED_ARRAY_RE.match(field_type) or _SEQ_RE.match(field_type):
			base_orch, is_array, fixed_len = _ros_field_to_orch(field_type)
			if base_orch in {"uint8", "byte"} and isinstance(field_val, (bytes, bytearray)):
				setattr(msg, field_name, list(field_val))
				continue

			if field_val is None:
				setattr(msg, field_name, [])
				continue
			if not isinstance(field_val, (list, tuple)):
				raise ValueError(f"Field '{field_name}' expects list")

			# If the ROS field type is a message sequence/array, build message objects.
			inner_ros_type = None
			m_fixed = _FIXED_ARRAY_RE.match(field_type)
			if m_fixed:
				inner_ros_type = m_fixed.group("base").strip()
			m_seq = _SEQ_RE.match(field_type)
			if m_seq:
				inner_ros_type = m_seq.group("inner").strip()

			if inner_ros_type and "/msg/" in inner_ros_type:
				try:
					utilities = importlib.import_module("rosidl_runtime_py.utilities")
					get_message = getattr(utilities, "get_message")
				except Exception as exc:
					raise ImportError("ROS2 python libs not available (missing rosidl_runtime_py)") from exc

				inner_cls = get_message(inner_ros_type)
				inner_orch = _ros_msg_to_orch_type(inner_ros_type)
				if inner_orch in s.type_encoders:
					setattr(
						msg,
						field_name,
						[_scalar_to_ros_std_msg(inner_orch, v, inner_cls) for v in field_val],
					)
				else:
					setattr(msg, field_name, [_dict_to_ros_msg(inner_cls, v) for v in field_val])
			else:
				setattr(msg, field_name, list(field_val))
			continue

		# Time/Duration fields
		if field_type == "builtin_interfaces/msg/Time":
			try:
				utilities = importlib.import_module("rosidl_runtime_py.utilities")
				get_message = getattr(utilities, "get_message")
			except Exception as exc:
				raise ImportError("ROS2 python libs not available (missing rosidl_runtime_py)") from exc

			tcls = get_message(field_type)
			tmsg = tcls()
			if isinstance(field_val, dict):
				tmsg.sec = int(field_val.get("sec", 0))
				tmsg.nanosec = int(field_val.get("nsec", 0))
			setattr(msg, field_name, tmsg)
			continue

		if field_type == "builtin_interfaces/msg/Duration":
			try:
				utilities = importlib.import_module("rosidl_runtime_py.utilities")
				get_message = getattr(utilities, "get_message")
			except Exception as exc:
				raise ImportError("ROS2 python libs not available (missing rosidl_runtime_py)") from exc

			dcls = get_message(field_type)
			dmsg = dcls()
			# Support dict with sec/nsec or float seconds
			if isinstance(field_val, dict):
				dmsg.sec = int(field_val.get("sec", 0))
				dmsg.nanosec = int(field_val.get("nsec", 0))
			else:
				sec = int(field_val)
				nsec = int((float(field_val) - sec) * 1e9)
				dmsg.sec = sec
				dmsg.nanosec = nsec
			setattr(msg, field_name, dmsg)
			continue

		# Nested message
		if "/msg/" in field_type:
			try:
				utilities = importlib.import_module("rosidl_runtime_py.utilities")
				get_message = getattr(utilities, "get_message")
			except Exception as exc:
				raise ImportError("ROS2 python libs not available (missing rosidl_runtime_py)") from exc

			inner_cls = get_message(field_type)
			orch_inner = _ros_msg_to_orch_type(field_type)
			if orch_inner in s.type_encoders:
				setattr(msg, field_name, _scalar_to_ros_std_msg(orch_inner, field_val, inner_cls))
			else:
				setattr(msg, field_name, _dict_to_ros_msg(inner_cls, field_val))
			continue

		# Scalar
		setattr(msg, field_name, field_val)

	return msg


@dataclass(frozen=True)
class ROS2BridgeConfig:
	node_name: str = "orchestrator_bridge"
	discovery_period_sec: float = 1.0
	exclude_topics: tuple[str, ...] = tuple(sorted(_DEFAULT_EXCLUDE_TOPICS))
	loopback_ttl_sec: float = 0.35


class ROS2Bridge:
	"""ROS2 <-> orchestrator topic bridge (topics only).

	- Auto-discovers ROS topics/types.
	- Mirrors ROS->WebSocket by writing into ROSSim.
	- Forwards WebSocket publishes -> ROS publishers.
	"""

	def __init__(self, *, sim, config: Optional[ROS2BridgeConfig] = None):
		self.sim = sim
		self.config = config or ROS2BridgeConfig()

		self._thread: Optional[threading.Thread] = None
		self._stop = threading.Event()
		self._ready = threading.Event()

		self._publish_queue: "queue.Queue[tuple[str, str, Any]]" = queue.Queue()
		self._recent: dict[str, tuple[float, bytes]] = {}
		self._recent_lock = threading.Lock()

		self._subscriptions: dict[str, Any] = {}
		self._publishers: dict[str, Any] = {}
		self._topic_types: dict[str, str] = {}  # topic -> ros_type

		self._node = None
		self._executor = None

	def start(self) -> None:
		if self._thread and self._thread.is_alive():
			return
		self._thread = threading.Thread(target=self._run, name="ROS2Bridge", daemon=True)
		self._thread.start()
		if not self._ready.wait(timeout=10.0):
			raise RuntimeError("ROS2 bridge failed to start (timeout waiting for node)")

	def stop(self) -> None:
		self._stop.set()
		if self._thread and self._thread.is_alive():
			self._thread.join(timeout=5.0)
		self._thread = None

	def enqueue_ws_publish(self, topic: str, orch_type: str, value: Any) -> None:
		# Loopback prevention: remember recent WS->ROS publish per topic.
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
			rclpy = importlib.import_module("rclpy")
			executors = importlib.import_module("rclpy.executors")
			node_mod = importlib.import_module("rclpy.node")
			SingleThreadedExecutor = getattr(executors, "SingleThreadedExecutor")
			Node = getattr(node_mod, "Node")
		except Exception as exc:
			raise ImportError(
				"ROS2 bridge enabled but rclpy is not available. "
				"Run inside a ROS2 environment/container (or install ROS2 Python)."
			) from exc

		rclpy.init(args=None)
		try:
			self._node = Node(self.config.node_name)
			self._executor = SingleThreadedExecutor()
			self._executor.add_node(self._node)

			# Timers run in ROS thread.
			self._node.create_timer(self.config.discovery_period_sec, self._discover_topics)
			self._node.create_timer(0.02, self._drain_publish_queue)

			self._ready.set()
			while not self._stop.is_set():
				self._executor.spin_once(timeout_sec=0.1)
		finally:
			try:
				if self._executor and self._node:
					self._executor.remove_node(self._node)
			except Exception:
				pass
			try:
				if self._node is not None:
					self._node.destroy_node()
			except Exception:
				pass
			try:
				rclpy.shutdown()
			except Exception:
				pass

	def _discover_topics(self) -> None:
		# Runs on ROS thread.
		if self._node is None:
			return

		discovered = self._node.get_topic_names_and_types()
		for topic_name, ros_types in discovered:
			if topic_name in self.config.exclude_topics:
				continue
			if not ros_types:
				continue
			ros_type = ros_types[0]
			if topic_name in self._subscriptions:
				continue

			try:
				orch_type = _ensure_orch_schema_for_ros_msg(ros_type)
			except Exception as exc:
				# Can't bridge types that aren't available in the environment.
				self._node.get_logger().debug(f"Skipping {topic_name} ({ros_type}): {exc}")
				continue

			try:
				utilities = importlib.import_module("rosidl_runtime_py.utilities")
				get_message = getattr(utilities, "get_message")
				qos_mod = importlib.import_module("rclpy.qos")
				QoSProfile = getattr(qos_mod, "QoSProfile")

				msg_cls = get_message(ros_type)
				qos = QoSProfile(depth=10)

				def _cb(msg, _topic=topic_name, _orch_type=orch_type):
					self._on_ros_message(_topic, _orch_type, msg)

				sub = self._node.create_subscription(msg_cls, topic_name, _cb, qos)
				self._subscriptions[topic_name] = sub
				self._topic_types[topic_name] = ros_type

				# Advertise the topic immediately on WS side (data None).
				self.sim.add_topic(topic_name, orch_type)
			except Exception as exc:
				self._node.get_logger().debug(f"Failed subscribing {topic_name} ({ros_type}): {exc}")

	def _on_ros_message(self, topic: str, orch_type: str, ros_msg: Any) -> None:
		# Runs on ROS thread.
		try:
			value = _ros_msg_to_value(ros_msg)
		except Exception:
			return

		# Loopback prevention: drop if it matches a recent WS->ROS publish.
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

		self.sim.add_topic(topic, orch_type)
		self.sim.update_topic(topic, value)

	def _drain_publish_queue(self) -> None:
		# Runs on ROS thread.
		if self._node is None:
			return

		try:
			utilities = importlib.import_module("rosidl_runtime_py.utilities")
			get_message = getattr(utilities, "get_message")
			qos_mod = importlib.import_module("rclpy.qos")
			QoSProfile = getattr(qos_mod, "QoSProfile")
		except Exception:
			return

		qos = QoSProfile(depth=10)
		drained = 0
		while drained < 200:
			try:
				topic, orch_type, value = self._publish_queue.get_nowait()
			except queue.Empty:
				break

			drained += 1
			try:
				ros_type = _orch_to_ros_msg_type(orch_type)
				msg_cls = get_message(ros_type)

				pub = self._publishers.get(topic)
				if pub is None:
					pub = self._node.create_publisher(msg_cls, topic, qos)
					self._publishers[topic] = pub

				if orch_type in s.type_encoders:
					msg = _scalar_to_ros_std_msg(orch_type, value, msg_cls)
				elif orch_type == "time":
					msg = msg_cls()
					if isinstance(value, dict):
						msg.sec = int(value.get("sec", 0))
						msg.nanosec = int(value.get("nsec", 0))
					else:
						msg.sec = int(value or 0)
						msg.nanosec = 0
				elif orch_type == "duration":
					msg = msg_cls()
					if isinstance(value, dict):
						msg.sec = int(value.get("sec", 0))
						msg.nanosec = int(value.get("nsec", 0))
					else:
						seconds = float(value or 0.0)
						sec = int(seconds)
						msg.sec = sec
						msg.nanosec = int((seconds - sec) * 1e9)
				else:
					msg = _dict_to_ros_msg(msg_cls, value)
				pub.publish(msg)
			except Exception as exc:
				try:
					self._node.get_logger().debug(f"WS->ROS publish failed for {topic} ({orch_type}): {exc}")
				except Exception:
					pass

