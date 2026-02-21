import struct

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

# basic type encodings (1 byte)
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

## -- encoding functions --

def type_encoder(type_str):
    # encode the type itself to a map
    return type_encoders.get(type_str, 0xFF)

def encodeString(data: str) -> bytearray:
    return data.encode('utf-8')

def encodeInt32(data: int) -> bytearray:
    return data.to_bytes(4, byteorder='little', signed=True)

def encodeFloat32(data: float) -> bytearray:
    return struct.pack('<f', data)

def encodeBool(data: bool) -> bytearray:
    return b'\x01' if data else b'\x00'

def encodeFloat64(data: float) -> bytearray:
    return struct.pack('<d', data)

def encodeInt64(data: int) -> bytearray:
    return data.to_bytes(8, byteorder='little', signed=True)

def encodeUInt32(data: int) -> bytearray:
    return data.to_bytes(4, byteorder='little', signed=False)

def encodeUInt64(data: int) -> bytearray:
    return data.to_bytes(8, byteorder='little', signed=False)

def encodeByte(data: bytes) -> bytearray:
    return data

def encodeChar(data: str) -> bytearray:
    if len(data) != 1:
        raise ValueError("Data for std_msgs/Char must be a single character.")
    return data.encode('utf-8')

def encodeColorRGBA(data: tuple) -> bytearray:
    if len(data) != 4:
        raise ValueError("Data for std_msgs/ColorRGBA must be a tuple of 4 floats (r, g, b, a).")
    return struct.pack('<ffff', *data)

def encodeDuration(data: float) -> bytearray:
    sec = int(data)
    nsec = int((data - sec) * 1e9)
    return struct.pack('<ii', sec, nsec)

def encode(type, data):
    if type in types:
        encoder = globals().get(f"encode{type.split('/')[-1]}")
        if encoder:
            value = encoder(data)
            count = len(value)
            return bytes([type_encoder(type)]) + count.to_bytes(4, byteorder='little') + value
        else:
            raise ValueError(f"No encoder found for type '{type}'.")
    else:
        raise ValueError(f"Type '{type}' not supported.")
    

## -- decoding functions --
def decodeString(data: bytes) -> str:
    return data.decode('utf-8')

def decodeInt32(data: bytes) -> int:
    return int.from_bytes(data, byteorder='little', signed=True)

def decodeFloat32(data: bytes) -> float:
    return struct.unpack('<f', data)[0]

def decodeBool(data: bytes) -> bool:
    return data != b'\x00'

def decodeFloat64(data: bytes) -> float:
    return struct.unpack('<d', data)[0]

def decodeInt64(data: bytes) -> int:
    return int.from_bytes(data, byteorder='little', signed=True)

def decodeUInt32(data: bytes) -> int:
    return int.from_bytes(data, byteorder='little', signed=False)

def decodeUInt64(data: bytes) -> int:
    return int.from_bytes(data, byteorder='little', signed=False)

def decodeByte(data: bytes) -> bytes:
    return data

def decodeChar(data: bytes) -> str:
    return data.decode('utf-8')

def decodeColorRGBA(data: bytes) -> tuple:
    return struct.unpack('<ffff', data)

def decodeDuration(data: bytes) -> float:
    sec, nsec = struct.unpack('<ii', data)
    return sec + nsec / 1e9

def typeFromByte(byte):
    for type_str, type_byte in type_encoders.items():
        if byte == type_byte:
            return type_str
    raise ValueError(f"Unknown type byte: {byte}")

def decode(data: bytes):
    type_byte = data[0]
    type = typeFromByte(type_byte)
    count = int.from_bytes(data[1:5], byteorder='little')
    data = data[5:5+count]

    if type in types:
        decoder = globals().get(f"decode{type.split('/')[-1]}")
        if decoder:
            return type, decoder(data)
        else:
            raise ValueError(f"No decoder found for type '{type}'.")
    else:
        raise ValueError(f"Type '{type}' not supported.")