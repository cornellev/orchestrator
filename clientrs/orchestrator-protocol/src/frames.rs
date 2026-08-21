//! Client/server frame layout helpers.

use crate::codec::{decode, encode, encode_topic_name};
use crate::error::{Error, Result};
use crate::schema::MessageRegistry;
use crate::types::{type_byte_for, type_name_from_byte, DYNAMIC_TYPE_BYTE};
use crate::value::Value;
use std::collections::BTreeMap;

/// Maximum UTF-8 byte length for a topic name.
pub const MAX_TOPIC_NAME_LEN: usize = 255;

/// Client → server operation codes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum Operation {
    /// Request current topic list.
    Echo = 0x00,
    /// Subscribe to topic updates.
    Subscribe = 0x01,
    /// Publish a typed value.
    Publish = 0x02,
    /// Request a full value snapshot.
    RequestAll = 0x03,
}

impl Operation {
    /// Opcode byte.
    pub fn as_u8(self) -> u8 {
        self as u8
    }
}

/// Server → client response kinds.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum ResponseKind {
    /// Topic list metadata.
    Echo = 0x80,
    /// Newly created topic metadata.
    EchoNew = 0x81,
    /// Single topic value update.
    Update = 0x82,
    /// Full snapshot of topic values.
    BigUpdate = 0x83,
    /// Protocol / validation error.
    Error = 0x84,
}

impl ResponseKind {
    /// Parse a response opcode.
    pub fn from_u8(byte: u8) -> Result<Self> {
        match byte {
            0x80 => Ok(Self::Echo),
            0x81 => Ok(Self::EchoNew),
            0x82 => Ok(Self::Update),
            0x83 => Ok(Self::BigUpdate),
            0x84 => Ok(Self::Error),
            other => Err(Error::UnknownOpcode(other)),
        }
    }

    /// Opcode byte.
    pub fn as_u8(self) -> u8 {
        self as u8
    }
}

/// Topic metadata from echo / echo_new / update headers.
#[derive(Debug, Clone, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TopicInfo {
    /// Server-assigned topic id (big-endian on the wire).
    pub topic_id: u32,
    /// Fully-qualified type string.
    pub type_str: String,
    /// Encoded value byte length (0 if no data in this frame).
    pub count: u32,
    /// Topic name.
    pub name: String,
}

/// Topic update carrying an optional decoded value.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TopicUpdate {
    /// Server-assigned topic id.
    pub topic_id: u32,
    /// Fully-qualified type string.
    pub type_str: String,
    /// Encoded value byte length from metadata.
    pub count: u32,
    /// Topic name.
    pub name: String,
    /// Decoded value, if present.
    pub value: Option<Value>,
}

/// Server protocol error payload (`0x84`).
#[derive(Debug, Clone, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct ProtocolErrorInfo {
    /// Numeric error code.
    pub code: u16,
    /// Human-readable message.
    pub message: String,
}

/// Decoded server response.
#[derive(Debug, Clone, PartialEq)]
pub enum Response {
    /// Echo topic list.
    Echo(Vec<TopicInfo>),
    /// New topic announcement.
    EchoNew(TopicInfo),
    /// Single update.
    Update(TopicUpdate),
    /// Snapshot map: topic name → (type, value).
    BigUpdate(BTreeMap<String, (String, Value)>),
    /// Server error frame.
    Error(ProtocolErrorInfo),
}

/// Build a request frame with only an opcode (echo / subscribe / request_all).
pub fn build_request_frame(op: Operation) -> Vec<u8> {
    vec![op.as_u8()]
}

/// Build a publish frame: `[0x02][name_len][name][typed_envelope]`.
pub fn build_publish_frame(
    registry: &MessageRegistry,
    topic: &str,
    type_str: &str,
    data: &Value,
) -> Result<Vec<u8>> {
    let encoded_name = encode_topic_name(topic)?;
    let payload = encode(registry, type_str, data)?;
    let mut out = Vec::with_capacity(1 + 1 + encoded_name.len() + payload.len());
    out.push(Operation::Publish.as_u8());
    out.push(encoded_name.len() as u8);
    out.extend_from_slice(&encoded_name);
    out.extend_from_slice(&payload);
    Ok(out)
}

/// Encode a server-style error frame (useful for tests).
pub fn encode_error_frame(message: &str, code: u16) -> Vec<u8> {
    let msg = message.as_bytes();
    let mut out = Vec::with_capacity(1 + 4 + msg.len());
    out.push(ResponseKind::Error.as_u8());
    out.extend_from_slice(&code.to_le_bytes());
    out.extend_from_slice(&(msg.len() as u16).to_le_bytes());
    out.extend_from_slice(msg);
    out
}

/// Decode an error payload (without the leading opcode byte).
pub fn decode_error_payload(buf: &[u8]) -> Result<ProtocolErrorInfo> {
    if buf.len() < 4 {
        return Err(Error::Truncated {
            label: "error response",
            offset: 0,
            needed: 4,
            available: buf.len(),
        });
    }
    let code = u16::from_le_bytes([buf[0], buf[1]]);
    let length = u16::from_le_bytes([buf[2], buf[3]]) as usize;
    if 4 + length > buf.len() {
        return Err(Error::Truncated {
            label: "error message",
            offset: 4,
            needed: length,
            available: buf.len() - 4,
        });
    }
    let message = String::from_utf8_lossy(&buf[4..4 + length]).into_owned();
    Ok(ProtocolErrorInfo { code, message })
}

fn read_u32_be(buf: &[u8], offset: usize) -> Result<u32> {
    if offset + 4 > buf.len() {
        return Err(Error::Truncated {
            label: "topic id",
            offset,
            needed: 4,
            available: buf.len().saturating_sub(offset),
        });
    }
    Ok(u32::from_be_bytes([
        buf[offset],
        buf[offset + 1],
        buf[offset + 2],
        buf[offset + 3],
    ]))
}

fn read_u32_le(buf: &[u8], offset: usize, label: &'static str) -> Result<u32> {
    if offset + 4 > buf.len() {
        return Err(Error::Truncated {
            label,
            offset,
            needed: 4,
            available: buf.len().saturating_sub(offset),
        });
    }
    Ok(u32::from_le_bytes([
        buf[offset],
        buf[offset + 1],
        buf[offset + 2],
        buf[offset + 3],
    ]))
}

fn read_u16_le(buf: &[u8], offset: usize, label: &'static str) -> Result<u16> {
    if offset + 2 > buf.len() {
        return Err(Error::Truncated {
            label,
            offset,
            needed: 2,
            available: buf.len().saturating_sub(offset),
        });
    }
    Ok(u16::from_le_bytes([buf[offset], buf[offset + 1]]))
}

/// Parse a topic metadata block; returns `(info, next_offset)`.
pub fn parse_topic_info(buf: &[u8], offset: usize) -> Result<(TopicInfo, usize)> {
    if offset + 7 > buf.len() {
        return Err(Error::Truncated {
            label: "topic info header",
            offset,
            needed: 7,
            available: buf.len().saturating_sub(offset),
        });
    }
    let topic_id = read_u32_be(buf, offset)?;
    let type_byte = buf[offset + 4];
    let dynamic_len = read_u16_le(buf, offset + 5, "dynamic type length")? as usize;
    let dynamic_start = offset + 7;
    let dynamic_end = dynamic_start + dynamic_len;
    if dynamic_end + 5 > buf.len() {
        return Err(Error::Truncated {
            label: "topic info payload",
            offset: dynamic_start,
            needed: dynamic_len + 5,
            available: buf.len().saturating_sub(dynamic_start),
        });
    }

    let type_str = if type_byte == DYNAMIC_TYPE_BYTE {
        std::str::from_utf8(&buf[dynamic_start..dynamic_end])?.to_owned()
    } else {
        type_name_from_byte(type_byte)?.to_owned()
    };

    let count = read_u32_le(buf, dynamic_end, "topic count")?;
    let name_len = buf[dynamic_end + 4] as usize;
    let start = dynamic_end + 5;
    let end = start + name_len;
    if end > buf.len() {
        return Err(Error::Truncated {
            label: "topic name",
            offset: start,
            needed: name_len,
            available: buf.len().saturating_sub(start),
        });
    }
    let name = std::str::from_utf8(&buf[start..end])?.to_owned();
    Ok((
        TopicInfo {
            topic_id,
            type_str,
            count,
            name,
        },
        end,
    ))
}

/// Parse an echo payload (`total:u32le` + topic info blocks).
pub fn parse_echo(buf: &[u8]) -> Result<Vec<TopicInfo>> {
    if buf.len() < 4 {
        return Err(Error::Truncated {
            label: "echo total",
            offset: 0,
            needed: 4,
            available: buf.len(),
        });
    }
    let total = read_u32_le(buf, 0, "echo total")? as usize;
    let mut offset = 4;
    let mut topics = Vec::with_capacity(total);
    for _ in 0..total {
        let (info, next) = parse_topic_info(buf, offset)?;
        topics.push(info);
        offset = next;
    }
    Ok(topics)
}

/// Parse an update payload (topic info + optional typed envelope).
pub fn parse_update(registry: &MessageRegistry, buf: &[u8]) -> Result<TopicUpdate> {
    let (info, offset) = parse_topic_info(buf, 0)?;
    let value = if offset < buf.len() {
        let (type_str, value) = decode(registry, &buf[offset..])?;
        if type_str != info.type_str {
            return Err(Error::TypeMismatch {
                name: info.name.clone(),
                expected: info.type_str.clone(),
                got: type_str,
            });
        }
        Some(value)
    } else {
        None
    };
    Ok(TopicUpdate {
        topic_id: info.topic_id,
        type_str: info.type_str,
        count: info.count,
        name: info.name,
        value,
    })
}

/// Parse a big_update snapshot payload.
pub fn parse_big_update(
    registry: &MessageRegistry,
    buf: &[u8],
) -> Result<BTreeMap<String, (String, Value)>> {
    if buf.len() < 4 {
        return Err(Error::Truncated {
            label: "big_update",
            offset: 0,
            needed: 4,
            available: buf.len(),
        });
    }
    let total_topics = read_u32_le(buf, 0, "big_update total")? as usize;
    let mut offset = 4;
    let mut results = BTreeMap::new();
    for _ in 0..total_topics {
        if offset >= buf.len() {
            return Err(Error::Truncated {
                label: "big_update topic entry",
                offset,
                needed: 1,
                available: 0,
            });
        }
        let name_len = buf[offset] as usize;
        if offset + 1 + name_len > buf.len() {
            return Err(Error::Truncated {
                label: "big_update topic name",
                offset: offset + 1,
                needed: name_len,
                available: buf.len().saturating_sub(offset + 1),
            });
        }
        let name = std::str::from_utf8(&buf[offset + 1..offset + 1 + name_len])?.to_owned();
        let data_offset = offset + 1 + name_len;
        if data_offset + 5 > buf.len() {
            return Err(Error::Truncated {
                label: "big_update typed payload",
                offset: data_offset,
                needed: 5,
                available: buf.len().saturating_sub(data_offset),
            });
        }
        let count = read_u32_le(buf, data_offset + 1, "big_update count")? as usize;
        if data_offset + 5 + count > buf.len() {
            return Err(Error::Truncated {
                label: "big_update value",
                offset: data_offset + 5,
                needed: count,
                available: buf.len().saturating_sub(data_offset + 5),
            });
        }
        let raw_value = &buf[data_offset..data_offset + 5 + count];
        let (type_str, value) = decode(registry, raw_value)?;
        results.insert(name, (type_str, value));
        offset = data_offset + 5 + count;
    }
    Ok(results)
}

/// Decode a full server response frame (including opcode byte).
pub fn decode_response(registry: &MessageRegistry, raw: &[u8]) -> Result<Response> {
    if raw.is_empty() {
        return Err(Error::EmptyPayload);
    }
    let kind = ResponseKind::from_u8(raw[0])?;
    let payload = &raw[1..];
    match kind {
        ResponseKind::Echo => Ok(Response::Echo(parse_echo(payload)?)),
        ResponseKind::EchoNew => {
            let (info, _) = parse_topic_info(payload, 0)?;
            Ok(Response::EchoNew(info))
        }
        ResponseKind::Update => Ok(Response::Update(parse_update(registry, payload)?)),
        ResponseKind::BigUpdate => Ok(Response::BigUpdate(parse_big_update(registry, payload)?)),
        ResponseKind::Error => Ok(Response::Error(decode_error_payload(payload)?)),
    }
}

/// Helper used by tests / docs: build topic-data without opcode.
pub fn build_topic_data(
    registry: &MessageRegistry,
    topic: &str,
    type_str: &str,
    data: &Value,
) -> Result<Vec<u8>> {
    let encoded_name = encode_topic_name(topic)?;
    let payload = encode(registry, type_str, data)?;
    let mut out = Vec::with_capacity(1 + encoded_name.len() + payload.len());
    out.push(encoded_name.len() as u8);
    out.extend_from_slice(&encoded_name);
    out.extend_from_slice(&payload);
    let _ = type_byte_for(type_str);
    Ok(out)
}
