import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

types = {
    "std_msgs/String": str,
    "std_msgs/Int32": int,
    "std_msgs/Float32": float,
    "std_msgs/Bool": bool,
    "std_msgs/Float64": float,
    "std_msgs/Int64": int,
    "std_msgs/UInt32": int,
    "std_msgs/UInt64": int,
    "std_msgs/Byte": bytes,
    "std_msgs/Char": str,
    "std_msgs/ColorRGBA": tuple,
    "std_msgs/Duration": float,
}

type_encoders = {
    "std_msgs/String": 0x01,
    "std_msgs/Int32": 0x02,
    "std_msgs/Float32": 0x03,
    "std_msgs/Bool": 0x04,
    "std_msgs/Float64": 0x05,
    "std_msgs/Int64": 0x06,
    "std_msgs/UInt32": 0x07,
    "std_msgs/UInt64": 0x08,
    "std_msgs/Byte": 0x09,
    "std_msgs/Char": 0x0A,
    "std_msgs/ColorRGBA": 0x0B,
    "std_msgs/Duration": 0x0C,
}

DYNAMIC_TYPE_BYTE = 0xFF

BUILTIN_SCALARS = {
    "bool": ("<?", 1),
    "int8": ("<b", 1),
    "uint8": ("<B", 1),
    "byte": ("<B", 1),
    "char": ("<b", 1),
    "int16": ("<h", 2),
    "uint16": ("<H", 2),
    "int32": ("<i", 4),
    "uint32": ("<I", 4),
    "int64": ("<q", 8),
    "uint64": ("<Q", 8),
    "float32": ("<f", 4),
    "float64": ("<d", 8),
}

_SCALAR_ALIASES = {
    "std_msgs/String": "string",
    "std_msgs/Int32": "int32",
    "std_msgs/Float32": "float32",
    "std_msgs/Bool": "bool",
    "std_msgs/Float64": "float64",
    "std_msgs/Int64": "int64",
    "std_msgs/UInt32": "uint32",
    "std_msgs/UInt64": "uint64",
    "std_msgs/Byte": "byte",
    "std_msgs/Char": "char",
    "std_msgs/Duration": "duration",
}


@dataclass(frozen=True)
class FieldDef:
    name: str
    type_name: str
    is_array: bool = False
    array_len: Optional[int] = None


@dataclass(frozen=True)
class MessageDef:
    type_name: str
    fields: tuple[FieldDef, ...]


message_registry: dict[str, MessageDef] = {}


def type_encoder(type_str):
    return type_encoders.get(type_str, DYNAMIC_TYPE_BYTE)


def typeFromByte(byte):
    for type_str, type_byte in type_encoders.items():
        if byte == type_byte:
            return type_str
    if byte == DYNAMIC_TYPE_BYTE:
        return "__dynamic__"
    raise ValueError(f"Unknown type byte: {byte}")


def _normalize_type_name(type_name: str, package: Optional[str] = None) -> str:
    if "/" in type_name:
        return type_name
    scalar = type_name.lower()
    if scalar in BUILTIN_SCALARS or scalar in {"string", "time", "duration"}:
        return scalar
    if package:
        return f"{package}/{type_name}"
    return type_name


def _parse_field_type(type_token: str):
    m = re.fullmatch(r"([A-Za-z0-9_/]+)(\[(\d*)\])?", type_token)
    if not m:
        raise ValueError(f"Invalid field type token '{type_token}'")
    base = m.group(1)
    is_array = m.group(2) is not None
    fixed_len = None
    if is_array and m.group(3):
        fixed_len = int(m.group(3))
    return base, is_array, fixed_len


def register_message_type(type_name: str, fields: list[FieldDef]):
    normalized = _normalize_type_name(type_name)
    message_registry[normalized] = MessageDef(type_name=normalized, fields=tuple(fields))


def load_message_definition(type_name: str, definition: str):
    if "/" not in type_name:
        raise ValueError("Type name must be in the form 'package/MessageName'")

    package_name = type_name.split("/", 1)[0]
    fields: list[FieldDef] = []

    for raw_line in definition.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" in line:
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        type_token, name = parts[0], parts[1]
        base, is_array, fixed_len = _parse_field_type(type_token)
        resolved_base = _normalize_type_name(base, package_name)
        fields.append(FieldDef(name=name, type_name=resolved_base, is_array=is_array, array_len=fixed_len))

    register_message_type(type_name, fields)
    return _normalize_type_name(type_name)


def load_message_file(file_path: Union[str, os.PathLike], package: Optional[str] = None):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(path)

    inferred_package = package or path.parent.parent.name
    msg_name = path.stem
    full_type = f"{inferred_package}/{msg_name}"
    return load_message_definition(full_type, path.read_text(encoding="utf-8"))


def load_message_folder(folder_path: Union[str, os.PathLike], package: Optional[str] = None):
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(folder)

    resolved_package = package or folder.name
    msg_dirs = [folder / "msg"] if (folder / "msg").is_dir() else [folder]

    loaded: list[str] = []
    for msg_dir in msg_dirs:
        for msg_file in sorted(msg_dir.glob("*.msg")):
            loaded.append(load_message_file(msg_file, package=resolved_package))
    return loaded


def load_message_root(root_path: Union[str, os.PathLike]):
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(root)

    loaded: list[str] = []
    for package_dir in sorted(root.iterdir()):
        if not package_dir.is_dir():
            continue
        msg_dir = package_dir / "msg"
        if msg_dir.is_dir():
            loaded.extend(load_message_folder(package_dir, package=package_dir.name))
    return loaded


def _auto_discover_message_defs():
    env_paths = os.getenv("ORCH_MSG_PATHS", "").strip()
    candidates: list[Path] = []
    if env_paths:
        for token in env_paths.split(os.pathsep):
            token = token.strip()
            if token:
                candidates.append(Path(token))

    cwd = Path.cwd()
    candidates.extend([
        cwd / "messages",
        cwd / "msgs",
        cwd / "msg",
    ])

    for candidate in candidates:
        if not candidate.exists() or not candidate.is_dir():
            continue
        try:
            has_package_dirs = any((child / "msg").is_dir() for child in candidate.iterdir() if child.is_dir())
        except Exception:
            has_package_dirs = False

        try:
            if has_package_dirs:
                load_message_root(candidate)
            else:
                load_message_folder(candidate)
        except Exception:
            continue


def _encode_builtin_scalar(type_name: str, value):
    scalar = type_name.lower()
    if scalar == "string":
        text = "" if value is None else str(value)
        encoded = text.encode("utf-8")
        return len(encoded).to_bytes(4, "little") + encoded

    if scalar == "duration":
        sec = int(value)
        nsec = int((float(value) - sec) * 1e9)
        return struct.pack("<ii", sec, nsec)

    if scalar == "time":
        if isinstance(value, dict):
            sec = int(value.get("sec", 0))
            nsec = int(value.get("nsec", 0))
        elif isinstance(value, (tuple, list)) and len(value) == 2:
            sec, nsec = int(value[0]), int(value[1])
        else:
            sec = int(value)
            nsec = 0
        return struct.pack("<II", sec, nsec)

    if scalar in {"byte", "uint8"} and isinstance(value, (bytes, bytearray)):
        return bytes(value)

    if scalar == "char":
        if isinstance(value, str):
            if len(value) != 1:
                raise ValueError("char value must be a single character")
            value = ord(value)

    fmt, _ = BUILTIN_SCALARS[scalar]
    return struct.pack(fmt, value)


def _decode_builtin_scalar(type_name: str, data: bytes, offset: int):
    scalar = type_name.lower()
    if scalar == "string":
        length = int.from_bytes(data[offset : offset + 4], "little")
        start = offset + 4
        end = start + length
        return data[start:end].decode("utf-8"), end

    if scalar == "duration":
        sec, nsec = struct.unpack("<ii", data[offset : offset + 8])
        return sec + nsec / 1e9, offset + 8

    if scalar == "time":
        sec, nsec = struct.unpack("<II", data[offset : offset + 8])
        return {"sec": sec, "nsec": nsec}, offset + 8

    fmt, size = BUILTIN_SCALARS[scalar]
    value = struct.unpack(fmt, data[offset : offset + size])[0]
    return value, offset + size


def _is_builtin(type_name: str):
    scalar = type_name.lower()
    return scalar in BUILTIN_SCALARS or scalar in {"string", "time", "duration"}


def _encode_field(field: FieldDef, value):
    if field.is_array:
        sequence = value or []
        if field.array_len is not None and len(sequence) != field.array_len:
            raise ValueError(f"Field '{field.name}' expects length {field.array_len}, got {len(sequence)}")

        out = bytearray()
        if field.array_len is None:
            out.extend(len(sequence).to_bytes(4, "little"))

        if field.type_name.lower() in {"uint8", "byte"} and isinstance(sequence, (bytes, bytearray)):
            out.extend(sequence)
            return bytes(out)

        for item in sequence:
            out.extend(_encode_value_raw(field.type_name, item))
        return bytes(out)

    return _encode_value_raw(field.type_name, value)


def _decode_field(field: FieldDef, data: bytes, offset: int):
    if field.is_array:
        count = field.array_len
        if count is None:
            count = int.from_bytes(data[offset : offset + 4], "little")
            offset += 4

        if field.type_name.lower() in {"uint8", "byte"}:
            end = offset + count
            return bytes(data[offset:end]), end

        items = []
        for _ in range(count):
            item, offset = _decode_value_raw(field.type_name, data, offset)
            items.append(item)
        return items, offset

    return _decode_value_raw(field.type_name, data, offset)


def _encode_message(type_name: str, value):
    if type_name not in message_registry:
        raise ValueError(f"Type '{type_name}' not supported. Load a .msg schema first.")
    msg = message_registry[type_name]
    if not isinstance(value, dict):
        raise ValueError(f"Message '{type_name}' expects dict payload")

    out = bytearray()
    for field in msg.fields:
        out.extend(_encode_field(field, value.get(field.name)))
    return bytes(out)


def _decode_message(type_name: str, data: bytes, offset: int):
    if type_name not in message_registry:
        raise ValueError(f"Type '{type_name}' not supported. Load a .msg schema first.")

    msg = message_registry[type_name]
    result = {}
    for field in msg.fields:
        val, offset = _decode_field(field, data, offset)
        result[field.name] = val
    return result, offset


def _encode_value_raw(type_name: str, value):
    normalized = _SCALAR_ALIASES.get(type_name, type_name)

    if normalized == "std_msgs/ColorRGBA":
        if not isinstance(value, (tuple, list)) or len(value) != 4:
            raise ValueError("Data for std_msgs/ColorRGBA must be a tuple/list of 4 floats (r, g, b, a).")
        return struct.pack("<ffff", *value)

    if _is_builtin(normalized):
        return _encode_builtin_scalar(normalized, value)

    return _encode_message(normalized, value)


def _decode_value_raw(type_name: str, data: bytes, offset: int):
    normalized = _SCALAR_ALIASES.get(type_name, type_name)

    if normalized == "std_msgs/ColorRGBA":
        return struct.unpack("<ffff", data[offset : offset + 16]), offset + 16

    if _is_builtin(normalized):
        return _decode_builtin_scalar(normalized, data, offset)

    return _decode_message(normalized, data, offset)


def encode(type_str, data):
    if type_str == "std_msgs/Byte":
        if data is None:
            value_payload = b""
        elif isinstance(data, (bytes, bytearray)):
            value_payload = bytes(data)
        elif isinstance(data, (list, tuple)):
            value_payload = bytes(data)
        else:
            value_payload = bytes([int(data)])
        return bytes([type_encoder(type_str)]) + len(value_payload).to_bytes(4, "little") + value_payload

    value_payload = _encode_value_raw(type_str, data)

    if type_str in type_encoders:
        return bytes([type_encoder(type_str)]) + len(value_payload).to_bytes(4, "little") + value_payload

    type_name_bytes = type_str.encode("utf-8")
    ext_payload = len(type_name_bytes).to_bytes(2, "little") + type_name_bytes + value_payload
    return bytes([DYNAMIC_TYPE_BYTE]) + len(ext_payload).to_bytes(4, "little") + ext_payload


def decode_typed(type_str: str, payload: bytes):
    return _decode_value_raw(type_str, payload, 0)[0]


def decode(data: bytes):
    type_byte = data[0]
    count = int.from_bytes(data[1:5], byteorder="little")
    payload = data[5 : 5 + count]

    if type_byte == DYNAMIC_TYPE_BYTE:
        type_name_len = int.from_bytes(payload[0:2], "little")
        type_name_start = 2
        type_name_end = type_name_start + type_name_len
        type_name = payload[type_name_start:type_name_end].decode("utf-8")
        value = decode_typed(type_name, payload[type_name_end:])
        return type_name, value

    type_name = typeFromByte(type_byte)
    if type_name == "std_msgs/Byte":
        return type_name, bytes(payload)
    value = decode_typed(type_name, payload)
    return type_name, value


_auto_discover_message_defs()