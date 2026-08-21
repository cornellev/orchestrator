//! Error types for the orchestrator protocol.

use thiserror::Error;

/// Convenient result alias for protocol operations.
pub type Result<T> = std::result::Result<T, Error>;

/// Protocol encode/decode and schema errors.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum Error {
    /// Input was truncated before a complete field could be read.
    #[error("truncated {label}: need {needed} bytes at offset {offset}, have {available}")]
    Truncated {
        /// Human-readable field label.
        label: &'static str,
        /// Byte offset into the buffer.
        offset: usize,
        /// Required byte count.
        needed: usize,
        /// Remaining available bytes.
        available: usize,
    },
    /// Trailing bytes remained after a successful decode.
    #[error("trailing bytes after {label}: {count}")]
    TrailingBytes {
        /// Human-readable field label.
        label: &'static str,
        /// Number of leftover bytes.
        count: usize,
    },
    /// Unknown standard type byte.
    #[error("unknown type byte: {0:#04x}")]
    UnknownTypeByte(u8),
    /// Unknown response opcode.
    #[error("unknown response opcode: {0:#04x}")]
    UnknownOpcode(u8),
    /// Empty typed payload envelope.
    #[error("empty typed payload")]
    EmptyPayload,
    /// Topic name exceeds the 255 UTF-8 byte limit.
    #[error("topic name exceeds {MAX} UTF-8 bytes", MAX = crate::frames::MAX_TOPIC_NAME_LEN)]
    TopicNameTooLong,
    /// Message type has not been registered.
    #[error("type '{0}' not supported; load a .msg schema first")]
    UnknownType(String),
    /// Invalid type name (must be `package/Message`).
    #[error("type name must be in the form 'package/MessageName'")]
    InvalidTypeName,
    /// Invalid field type token in a `.msg` definition.
    #[error("invalid field type token '{0}'")]
    InvalidFieldType(String),
    /// Message payload was not a map/object.
    #[error("message '{0}' expects a map payload")]
    ExpectedMap(String),
    /// Array length mismatch for a fixed-size field.
    #[error("field '{name}' expects length {expected}, got {got}")]
    ArrayLength {
        /// Field name.
        name: String,
        /// Expected length.
        expected: usize,
        /// Actual length.
        got: usize,
    },
    /// Char value validation failure.
    #[error("{0}")]
    InvalidChar(&'static str),
    /// ColorRGBA must be four floats.
    #[error("data for std_msgs/ColorRGBA must be 4 floats (r, g, b, a)")]
    InvalidColor,
    /// Type mismatch between topic metadata and payload.
    #[error("mismatched update type for topic '{name}': {got} != {expected}")]
    TypeMismatch {
        /// Topic name.
        name: String,
        /// Expected type string.
        expected: String,
        /// Actual type string.
        got: String,
    },
    /// Invalid UTF-8 in a string or type name.
    #[error("invalid utf-8: {0}")]
    Utf8(String),
    /// Filesystem / IO style failures surfaced as protocol errors.
    #[error("{0}")]
    Io(String),
    /// Generic invalid value.
    #[error("{0}")]
    InvalidValue(String),
}

impl From<std::str::Utf8Error> for Error {
    fn from(value: std::str::Utf8Error) -> Self {
        Self::Utf8(value.to_string())
    }
}

impl From<std::string::FromUtf8Error> for Error {
    fn from(value: std::string::FromUtf8Error) -> Self {
        Self::Utf8(value.to_string())
    }
}
