//! Standard type byte map.

use crate::error::{Error, Result};
use std::collections::HashMap;
use std::sync::OnceLock;

/// Dynamic / custom message type byte.
pub const DYNAMIC_TYPE_BYTE: u8 = 0xFF;

/// Canonical standard type byte assignments.
pub const STANDARD_TYPE_BYTES: &[(&str, u8)] = &[
    ("std_msgs/String", 0x01),
    ("std_msgs/Int32", 0x02),
    ("std_msgs/Float32", 0x03),
    ("std_msgs/Bool", 0x04),
    ("std_msgs/Float64", 0x05),
    ("std_msgs/Int64", 0x06),
    ("std_msgs/UInt32", 0x07),
    ("std_msgs/UInt64", 0x08),
    ("std_msgs/Byte", 0x09),
    ("std_msgs/Char", 0x0A),
    ("std_msgs/ColorRGBA", 0x0B),
    ("std_msgs/Duration", 0x0C),
];

fn name_to_byte() -> &'static HashMap<&'static str, u8> {
    static MAP: OnceLock<HashMap<&'static str, u8>> = OnceLock::new();
    MAP.get_or_init(|| STANDARD_TYPE_BYTES.iter().copied().collect())
}

fn byte_to_name() -> &'static HashMap<u8, &'static str> {
    static MAP: OnceLock<HashMap<u8, &'static str>> = OnceLock::new();
    MAP.get_or_init(|| {
        STANDARD_TYPE_BYTES
            .iter()
            .map(|(name, byte)| (*byte, *name))
            .collect()
    })
}

/// Return the type byte for a type name, or [`DYNAMIC_TYPE_BYTE`] for custom types.
pub fn type_byte_for(type_name: &str) -> u8 {
    name_to_byte()
        .get(type_name)
        .copied()
        .unwrap_or(DYNAMIC_TYPE_BYTE)
}

/// Resolve a standard type byte to its type name.
pub fn type_name_from_byte(byte: u8) -> Result<&'static str> {
    if byte == DYNAMIC_TYPE_BYTE {
        return Ok("__dynamic__");
    }
    byte_to_name()
        .get(&byte)
        .copied()
        .ok_or(Error::UnknownTypeByte(byte))
}

/// Scalar alias map used when encoding nested fields that reference std_msgs types.
pub(crate) fn scalar_alias(type_name: &str) -> &str {
    match type_name {
        "std_msgs/String" => "string",
        "std_msgs/Int32" => "int32",
        "std_msgs/Float32" => "float32",
        "std_msgs/Bool" => "bool",
        "std_msgs/Float64" => "float64",
        "std_msgs/Int64" => "int64",
        "std_msgs/UInt32" => "uint32",
        "std_msgs/UInt64" => "uint64",
        "std_msgs/Byte" => "byte",
        "std_msgs/Char" => "char",
        "std_msgs/Duration" => "duration",
        other => other,
    }
}
