//! Value representation for encoded/decoded messages.

use std::collections::BTreeMap;

/// RGBA color matching `std_msgs/ColorRGBA`.
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct ColorRgba {
    /// Red channel.
    pub r: f32,
    /// Green channel.
    pub g: f32,
    /// Blue channel.
    pub b: f32,
    /// Alpha channel.
    pub a: f32,
}

impl ColorRgba {
    /// Construct from four floats.
    pub fn new(r: f32, g: f32, b: f32, a: f32) -> Self {
        Self { r, g, b, a }
    }
}

/// ROS time (`sec`, `nsec`) representation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TimeValue {
    /// Seconds since epoch.
    pub sec: u32,
    /// Nanoseconds.
    pub nsec: u32,
}

/// Decoded / encodable protocol value.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "serde", serde(untagged))]
pub enum Value {
    /// Boolean.
    Bool(bool),
    /// Signed 8-bit integer.
    I8(i8),
    /// Unsigned 8-bit integer.
    U8(u8),
    /// Signed 16-bit integer.
    I16(i16),
    /// Unsigned 16-bit integer.
    U16(u16),
    /// Signed 32-bit integer.
    I32(i32),
    /// Unsigned 32-bit integer.
    U32(u32),
    /// Signed 64-bit integer.
    I64(i64),
    /// Unsigned 64-bit integer.
    U64(u64),
    /// 32-bit float.
    F32(f32),
    /// 64-bit float.
    F64(f64),
    /// UTF-8 string (also used for `std_msgs/Char` as a one-character string).
    String(String),
    /// Raw bytes (`std_msgs/Byte` or `uint8[]`).
    Bytes(Vec<u8>),
    /// Color RGBA.
    Color(ColorRgba),
    /// Duration in seconds (fractional).
    Duration(f64),
    /// Time stamp.
    Time(TimeValue),
    /// Homogeneous array of values.
    Array(Vec<Value>),
    /// Nested message fields keyed by field name.
    Message(BTreeMap<String, Value>),
}

impl Value {
    /// Convenience constructor for a string value.
    pub fn string(s: impl Into<String>) -> Self {
        Self::String(s.into())
    }

    /// Convenience constructor for a message map.
    pub fn message(fields: BTreeMap<String, Value>) -> Self {
        Self::Message(fields)
    }

    /// Attempt to borrow as a string.
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Self::String(s) => Some(s),
            _ => None,
        }
    }

    /// Attempt to borrow as a message map.
    pub fn as_message(&self) -> Option<&BTreeMap<String, Value>> {
        match self {
            Self::Message(m) => Some(m),
            _ => None,
        }
    }

    /// Attempt to convert into an i32.
    pub fn as_i32(&self) -> Option<i32> {
        match self {
            Self::I32(v) => Some(*v),
            Self::I8(v) => Some(i32::from(*v)),
            Self::I16(v) => Some(i32::from(*v)),
            Self::U8(v) => Some(i32::from(*v)),
            Self::U16(v) => Some(i32::from(*v)),
            _ => None,
        }
    }

    /// Attempt to convert into a bool.
    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Self::Bool(v) => Some(*v),
            _ => None,
        }
    }

    /// Attempt to borrow bytes.
    pub fn as_bytes(&self) -> Option<&[u8]> {
        match self {
            Self::Bytes(b) => Some(b),
            _ => None,
        }
    }
}

impl From<bool> for Value {
    fn from(value: bool) -> Self {
        Self::Bool(value)
    }
}

impl From<i32> for Value {
    fn from(value: i32) -> Self {
        Self::I32(value)
    }
}

impl From<i64> for Value {
    fn from(value: i64) -> Self {
        Self::I64(value)
    }
}

impl From<u32> for Value {
    fn from(value: u32) -> Self {
        Self::U32(value)
    }
}

impl From<u64> for Value {
    fn from(value: u64) -> Self {
        Self::U64(value)
    }
}

impl From<f32> for Value {
    fn from(value: f32) -> Self {
        Self::F32(value)
    }
}

impl From<f64> for Value {
    fn from(value: f64) -> Self {
        Self::F64(value)
    }
}

impl From<String> for Value {
    fn from(value: String) -> Self {
        Self::String(value)
    }
}

impl From<&str> for Value {
    fn from(value: &str) -> Self {
        Self::String(value.to_owned())
    }
}

impl From<Vec<u8>> for Value {
    fn from(value: Vec<u8>) -> Self {
        Self::Bytes(value)
    }
}

impl From<ColorRgba> for Value {
    fn from(value: ColorRgba) -> Self {
        Self::Color(value)
    }
}

impl From<BTreeMap<String, Value>> for Value {
    fn from(value: BTreeMap<String, Value>) -> Self {
        Self::Message(value)
    }
}
