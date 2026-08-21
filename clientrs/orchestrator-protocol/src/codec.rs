//! Encode and decode typed payloads.

use crate::error::{Error, Result};
use crate::schema::{is_builtin, FieldDef, MessageRegistry};
use crate::types::{scalar_alias, type_byte_for, type_name_from_byte, DYNAMIC_TYPE_BYTE};
use crate::value::{ColorRgba, TimeValue, Value};
use crate::MAX_TOPIC_NAME_LEN;
use std::collections::BTreeMap;

fn require_bytes(data: &[u8], offset: usize, size: usize, label: &'static str) -> Result<()> {
    if offset
        .checked_add(size)
        .map(|end| end > data.len())
        .unwrap_or(true)
    {
        return Err(Error::Truncated {
            label,
            offset,
            needed: size,
            available: data.len().saturating_sub(offset),
        });
    }
    Ok(())
}

fn read_u16_le(data: &[u8], offset: usize, label: &'static str) -> Result<u16> {
    require_bytes(data, offset, 2, label)?;
    Ok(u16::from_le_bytes([data[offset], data[offset + 1]]))
}

fn read_u32_le(data: &[u8], offset: usize, label: &'static str) -> Result<u32> {
    require_bytes(data, offset, 4, label)?;
    Ok(u32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ]))
}

fn read_i32_le(data: &[u8], offset: usize, label: &'static str) -> Result<i32> {
    require_bytes(data, offset, 4, label)?;
    Ok(i32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ]))
}

/// Encode a topic name and enforce the 255-byte limit.
pub fn encode_topic_name(topic_name: &str) -> Result<Vec<u8>> {
    let encoded = topic_name.as_bytes();
    if encoded.len() > MAX_TOPIC_NAME_LEN {
        return Err(Error::TopicNameTooLong);
    }
    Ok(encoded.to_vec())
}

fn coerce_bool(value: &Value) -> Result<bool> {
    match value {
        Value::Bool(v) => Ok(*v),
        Value::I32(v) => Ok(*v != 0),
        Value::U8(v) => Ok(*v != 0),
        other => Err(Error::InvalidValue(format!("expected bool, got {other:?}"))),
    }
}

fn coerce_i8(value: &Value) -> Result<i8> {
    match value {
        Value::I8(v) => Ok(*v),
        Value::I32(v) => {
            i8::try_from(*v).map_err(|_| Error::InvalidValue(format!("i8 out of range: {v}")))
        }
        Value::U8(v) => {
            i8::try_from(*v).map_err(|_| Error::InvalidValue(format!("i8 out of range: {v}")))
        }
        other => Err(Error::InvalidValue(format!("expected i8, got {other:?}"))),
    }
}

fn coerce_u8(value: &Value) -> Result<u8> {
    match value {
        Value::U8(v) => Ok(*v),
        Value::I32(v) => {
            u8::try_from(*v).map_err(|_| Error::InvalidValue(format!("u8 out of range: {v}")))
        }
        Value::I8(v) => {
            u8::try_from(*v).map_err(|_| Error::InvalidValue(format!("u8 out of range: {v}")))
        }
        other => Err(Error::InvalidValue(format!("expected u8, got {other:?}"))),
    }
}

fn coerce_i16(value: &Value) -> Result<i16> {
    match value {
        Value::I16(v) => Ok(*v),
        Value::I32(v) => {
            i16::try_from(*v).map_err(|_| Error::InvalidValue(format!("i16 out of range: {v}")))
        }
        Value::U8(v) => Ok(i16::from(*v)),
        Value::I8(v) => Ok(i16::from(*v)),
        other => Err(Error::InvalidValue(format!("expected i16, got {other:?}"))),
    }
}

fn coerce_u16(value: &Value) -> Result<u16> {
    match value {
        Value::U16(v) => Ok(*v),
        Value::I32(v) => {
            u16::try_from(*v).map_err(|_| Error::InvalidValue(format!("u16 out of range: {v}")))
        }
        Value::U8(v) => Ok(u16::from(*v)),
        other => Err(Error::InvalidValue(format!("expected u16, got {other:?}"))),
    }
}

fn coerce_i32(value: &Value) -> Result<i32> {
    match value {
        Value::I32(v) => Ok(*v),
        Value::I8(v) => Ok(i32::from(*v)),
        Value::I16(v) => Ok(i32::from(*v)),
        Value::U8(v) => Ok(i32::from(*v)),
        Value::U16(v) => Ok(i32::from(*v)),
        Value::U32(v) => {
            i32::try_from(*v).map_err(|_| Error::InvalidValue(format!("i32 out of range: {v}")))
        }
        Value::I64(v) => {
            i32::try_from(*v).map_err(|_| Error::InvalidValue(format!("i32 out of range: {v}")))
        }
        other => Err(Error::InvalidValue(format!("expected i32, got {other:?}"))),
    }
}

fn coerce_u32(value: &Value) -> Result<u32> {
    match value {
        Value::U32(v) => Ok(*v),
        Value::U8(v) => Ok(u32::from(*v)),
        Value::U16(v) => Ok(u32::from(*v)),
        Value::I32(v) => {
            u32::try_from(*v).map_err(|_| Error::InvalidValue(format!("u32 out of range: {v}")))
        }
        Value::U64(v) => {
            u32::try_from(*v).map_err(|_| Error::InvalidValue(format!("u32 out of range: {v}")))
        }
        other => Err(Error::InvalidValue(format!("expected u32, got {other:?}"))),
    }
}

fn coerce_i64(value: &Value) -> Result<i64> {
    match value {
        Value::I64(v) => Ok(*v),
        Value::I32(v) => Ok(i64::from(*v)),
        Value::I16(v) => Ok(i64::from(*v)),
        Value::I8(v) => Ok(i64::from(*v)),
        Value::U8(v) => Ok(i64::from(*v)),
        Value::U16(v) => Ok(i64::from(*v)),
        Value::U32(v) => Ok(i64::from(*v)),
        Value::U64(v) => {
            i64::try_from(*v).map_err(|_| Error::InvalidValue(format!("i64 out of range: {v}")))
        }
        other => Err(Error::InvalidValue(format!("expected i64, got {other:?}"))),
    }
}

fn coerce_u64(value: &Value) -> Result<u64> {
    match value {
        Value::U64(v) => Ok(*v),
        Value::U32(v) => Ok(u64::from(*v)),
        Value::U16(v) => Ok(u64::from(*v)),
        Value::U8(v) => Ok(u64::from(*v)),
        Value::I32(v) => {
            u64::try_from(*v).map_err(|_| Error::InvalidValue(format!("u64 out of range: {v}")))
        }
        Value::I64(v) => {
            u64::try_from(*v).map_err(|_| Error::InvalidValue(format!("u64 out of range: {v}")))
        }
        other => Err(Error::InvalidValue(format!("expected u64, got {other:?}"))),
    }
}

fn coerce_f32(value: &Value) -> Result<f32> {
    match value {
        Value::F32(v) => Ok(*v),
        Value::F64(v) => Ok(*v as f32),
        Value::I32(v) => Ok(*v as f32),
        other => Err(Error::InvalidValue(format!("expected f32, got {other:?}"))),
    }
}

fn coerce_f64(value: &Value) -> Result<f64> {
    match value {
        Value::F64(v) => Ok(*v),
        Value::F32(v) => Ok(f64::from(*v)),
        Value::I32(v) => Ok(f64::from(*v)),
        Value::Duration(v) => Ok(*v),
        other => Err(Error::InvalidValue(format!("expected f64, got {other:?}"))),
    }
}

fn encode_builtin_scalar(type_name: &str, value: &Value) -> Result<Vec<u8>> {
    let scalar = type_name.to_ascii_lowercase();
    match scalar.as_str() {
        "string" => {
            let text = match value {
                Value::String(s) => s.clone(),
                Value::I32(v) => v.to_string(),
                Value::I64(v) => v.to_string(),
                Value::U32(v) => v.to_string(),
                Value::U64(v) => v.to_string(),
                Value::F32(v) => v.to_string(),
                Value::F64(v) => v.to_string(),
                Value::Bool(v) => {
                    if *v {
                        "True".to_owned()
                    } else {
                        "False".to_owned()
                    }
                }
                _ => String::new(),
            };
            encode_string(&text)
        }
        "duration" => {
            let seconds = coerce_f64(value)?;
            let sec = seconds.trunc() as i32;
            let nsec = ((seconds - f64::from(sec)) * 1e9).round() as i32;
            let mut out = Vec::with_capacity(8);
            out.extend_from_slice(&sec.to_le_bytes());
            out.extend_from_slice(&nsec.to_le_bytes());
            Ok(out)
        }
        "time" => {
            let (sec, nsec) = match value {
                Value::Time(t) => (t.sec, t.nsec),
                Value::Message(m) => (
                    coerce_u32(m.get("sec").unwrap_or(&Value::U32(0)))?,
                    coerce_u32(m.get("nsec").unwrap_or(&Value::U32(0)))?,
                ),
                Value::Array(items) if items.len() == 2 => {
                    (coerce_u32(&items[0])?, coerce_u32(&items[1])?)
                }
                other => (coerce_u32(other)?, 0),
            };
            let mut out = Vec::with_capacity(8);
            out.extend_from_slice(&sec.to_le_bytes());
            out.extend_from_slice(&nsec.to_le_bytes());
            Ok(out)
        }
        "byte" | "uint8" => {
            if let Value::Bytes(b) = value {
                return Ok(b.clone());
            }
            Ok(vec![coerce_u8(value)?])
        }
        "char" => {
            let code = match value {
                Value::String(s) => {
                    let mut chars = s.chars();
                    let Some(ch) = chars.next() else {
                        return Err(Error::InvalidChar("char value must be a single character"));
                    };
                    if chars.next().is_some() {
                        return Err(Error::InvalidChar("char value must be a single character"));
                    }
                    let codepoint = ch as u32;
                    if codepoint > 127 {
                        return Err(Error::InvalidChar(
                            "char value must be a single ASCII character (0-127)",
                        ));
                    }
                    codepoint as i8
                }
                other => {
                    let v = coerce_i32(other)?;
                    if !(-128..=127).contains(&v) {
                        return Err(Error::InvalidChar("char value must fit in signed int8"));
                    }
                    v as i8
                }
            };
            Ok(vec![code as u8])
        }
        "bool" => Ok(vec![u8::from(coerce_bool(value)?)]),
        "int8" => Ok(vec![coerce_i8(value)? as u8]),
        "int16" => Ok(coerce_i16(value)?.to_le_bytes().to_vec()),
        "uint16" => Ok(coerce_u16(value)?.to_le_bytes().to_vec()),
        "int32" => Ok(coerce_i32(value)?.to_le_bytes().to_vec()),
        "uint32" => Ok(coerce_u32(value)?.to_le_bytes().to_vec()),
        "int64" => Ok(coerce_i64(value)?.to_le_bytes().to_vec()),
        "uint64" => Ok(coerce_u64(value)?.to_le_bytes().to_vec()),
        "float32" => Ok(coerce_f32(value)?.to_le_bytes().to_vec()),
        "float64" => Ok(coerce_f64(value)?.to_le_bytes().to_vec()),
        other => Err(Error::UnknownType(other.to_owned())),
    }
}

fn encode_string(text: &str) -> Result<Vec<u8>> {
    let encoded = text.as_bytes();
    let mut out = Vec::with_capacity(4 + encoded.len());
    out.extend_from_slice(&(encoded.len() as u32).to_le_bytes());
    out.extend_from_slice(encoded);
    Ok(out)
}

fn decode_builtin_scalar(type_name: &str, data: &[u8], offset: usize) -> Result<(Value, usize)> {
    let scalar = type_name.to_ascii_lowercase();
    match scalar.as_str() {
        "string" => {
            let length = read_u32_le(data, offset, "string length")? as usize;
            let start = offset + 4;
            require_bytes(data, start, length, "string payload")?;
            let end = start + length;
            let text = std::str::from_utf8(&data[start..end])?;
            Ok((Value::String(text.to_owned()), end))
        }
        "duration" => {
            require_bytes(data, offset, 8, "duration")?;
            let sec = i32::from_le_bytes(data[offset..offset + 4].try_into().unwrap());
            let nsec = i32::from_le_bytes(data[offset + 4..offset + 8].try_into().unwrap());
            Ok((
                Value::Duration(f64::from(sec) + f64::from(nsec) / 1e9),
                offset + 8,
            ))
        }
        "time" => {
            require_bytes(data, offset, 8, "time")?;
            let sec = u32::from_le_bytes(data[offset..offset + 4].try_into().unwrap());
            let nsec = u32::from_le_bytes(data[offset + 4..offset + 8].try_into().unwrap());
            Ok((Value::Time(TimeValue { sec, nsec }), offset + 8))
        }
        "char" => {
            require_bytes(data, offset, 1, "char")?;
            let value = data[offset] as i8;
            if !(0..=127).contains(&value) {
                return Err(Error::InvalidChar(
                    "char payload must be an ASCII codepoint (0-127)",
                ));
            }
            Ok((
                Value::String(char::from(value as u8).to_string()),
                offset + 1,
            ))
        }
        "bool" => {
            require_bytes(data, offset, 1, "bool")?;
            Ok((Value::Bool(data[offset] != 0), offset + 1))
        }
        "int8" => {
            require_bytes(data, offset, 1, "int8")?;
            Ok((Value::I8(data[offset] as i8), offset + 1))
        }
        "uint8" | "byte" => {
            require_bytes(data, offset, 1, "uint8")?;
            Ok((Value::U8(data[offset]), offset + 1))
        }
        "int16" => {
            require_bytes(data, offset, 2, "int16")?;
            Ok((
                Value::I16(i16::from_le_bytes(
                    data[offset..offset + 2].try_into().unwrap(),
                )),
                offset + 2,
            ))
        }
        "uint16" => {
            require_bytes(data, offset, 2, "uint16")?;
            Ok((
                Value::U16(u16::from_le_bytes(
                    data[offset..offset + 2].try_into().unwrap(),
                )),
                offset + 2,
            ))
        }
        "int32" => Ok((Value::I32(read_i32_le(data, offset, "int32")?), offset + 4)),
        "uint32" => Ok((Value::U32(read_u32_le(data, offset, "uint32")?), offset + 4)),
        "int64" => {
            require_bytes(data, offset, 8, "int64")?;
            Ok((
                Value::I64(i64::from_le_bytes(
                    data[offset..offset + 8].try_into().unwrap(),
                )),
                offset + 8,
            ))
        }
        "uint64" => {
            require_bytes(data, offset, 8, "uint64")?;
            Ok((
                Value::U64(u64::from_le_bytes(
                    data[offset..offset + 8].try_into().unwrap(),
                )),
                offset + 8,
            ))
        }
        "float32" => {
            require_bytes(data, offset, 4, "float32")?;
            Ok((
                Value::F32(f32::from_le_bytes(
                    data[offset..offset + 4].try_into().unwrap(),
                )),
                offset + 4,
            ))
        }
        "float64" => {
            require_bytes(data, offset, 8, "float64")?;
            Ok((
                Value::F64(f64::from_le_bytes(
                    data[offset..offset + 8].try_into().unwrap(),
                )),
                offset + 8,
            ))
        }
        other => Err(Error::UnknownType(other.to_owned())),
    }
}

fn encode_field(
    registry: &MessageRegistry,
    field: &FieldDef,
    value: Option<&Value>,
) -> Result<Vec<u8>> {
    if field.is_array {
        let sequence = match value {
            Some(Value::Array(items)) => items.as_slice(),
            Some(Value::Bytes(_))
                if field.type_name.eq_ignore_ascii_case("uint8")
                    || field.type_name.eq_ignore_ascii_case("byte") =>
            {
                let Value::Bytes(bytes) = value.unwrap() else {
                    unreachable!()
                };
                if let Some(expected) = field.array_len {
                    if bytes.len() != expected {
                        return Err(Error::ArrayLength {
                            name: field.name.clone(),
                            expected,
                            got: bytes.len(),
                        });
                    }
                }
                let mut out = Vec::new();
                if field.array_len.is_none() {
                    out.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
                }
                out.extend_from_slice(bytes);
                return Ok(out);
            }
            Some(other) => {
                return Err(Error::InvalidValue(format!(
                    "field '{}' expects array, got {other:?}",
                    field.name
                )));
            }
            None => &[][..],
        };

        if let Some(expected) = field.array_len {
            if sequence.len() != expected {
                return Err(Error::ArrayLength {
                    name: field.name.clone(),
                    expected,
                    got: sequence.len(),
                });
            }
        }

        let mut out = Vec::new();
        if field.array_len.is_none() {
            out.extend_from_slice(&(sequence.len() as u32).to_le_bytes());
        }
        for item in sequence {
            out.extend_from_slice(&encode_value_raw(registry, &field.type_name, item)?);
        }
        return Ok(out);
    }

    encode_value_raw(
        registry,
        &field.type_name,
        value.unwrap_or(&Value::Message(BTreeMap::new())),
    )
}

fn decode_field(
    registry: &MessageRegistry,
    field: &FieldDef,
    data: &[u8],
    mut offset: usize,
) -> Result<(Value, usize)> {
    if field.is_array {
        let count = if let Some(fixed) = field.array_len {
            fixed
        } else {
            let c = read_u32_le(data, offset, "array length")? as usize;
            offset += 4;
            c
        };

        if field.type_name.eq_ignore_ascii_case("uint8")
            || field.type_name.eq_ignore_ascii_case("byte")
        {
            require_bytes(data, offset, count, "byte array")?;
            let end = offset + count;
            return Ok((Value::Bytes(data[offset..end].to_vec()), end));
        }

        let mut items = Vec::with_capacity(count);
        for _ in 0..count {
            let (item, next) = decode_value_raw(registry, &field.type_name, data, offset)?;
            items.push(item);
            offset = next;
        }
        return Ok((Value::Array(items), offset));
    }

    decode_value_raw(registry, &field.type_name, data, offset)
}

fn encode_message(registry: &MessageRegistry, type_name: &str, value: &Value) -> Result<Vec<u8>> {
    let msg = registry
        .get(type_name)
        .ok_or_else(|| Error::UnknownType(type_name.to_owned()))?;
    let map = match value {
        Value::Message(m) => m,
        _ => return Err(Error::ExpectedMap(type_name.to_owned())),
    };
    let mut out = Vec::new();
    for field in &msg.fields {
        out.extend_from_slice(&encode_field(registry, field, map.get(&field.name))?);
    }
    Ok(out)
}

fn decode_message(
    registry: &MessageRegistry,
    type_name: &str,
    data: &[u8],
    mut offset: usize,
) -> Result<(Value, usize)> {
    let msg = registry
        .get(type_name)
        .ok_or_else(|| Error::UnknownType(type_name.to_owned()))?;
    let mut result = BTreeMap::new();
    for field in &msg.fields {
        let (val, next) = decode_field(registry, field, data, offset)?;
        result.insert(field.name.clone(), val);
        offset = next;
    }
    Ok((Value::Message(result), offset))
}

fn encode_value_raw(registry: &MessageRegistry, type_name: &str, value: &Value) -> Result<Vec<u8>> {
    let normalized = scalar_alias(type_name);
    if normalized == "std_msgs/ColorRGBA" {
        let color = match value {
            Value::Color(c) => *c,
            Value::Array(items) if items.len() == 4 => ColorRgba::new(
                coerce_f32(&items[0])?,
                coerce_f32(&items[1])?,
                coerce_f32(&items[2])?,
                coerce_f32(&items[3])?,
            ),
            _ => return Err(Error::InvalidColor),
        };
        let mut out = Vec::with_capacity(16);
        out.extend_from_slice(&color.r.to_le_bytes());
        out.extend_from_slice(&color.g.to_le_bytes());
        out.extend_from_slice(&color.b.to_le_bytes());
        out.extend_from_slice(&color.a.to_le_bytes());
        return Ok(out);
    }
    if is_builtin(normalized) {
        return encode_builtin_scalar(normalized, value);
    }
    encode_message(registry, normalized, value)
}

fn decode_value_raw(
    registry: &MessageRegistry,
    type_name: &str,
    data: &[u8],
    offset: usize,
) -> Result<(Value, usize)> {
    let normalized = scalar_alias(type_name);
    if normalized == "std_msgs/ColorRGBA" {
        require_bytes(data, offset, 16, "colorrgba")?;
        let r = f32::from_le_bytes(data[offset..offset + 4].try_into().unwrap());
        let g = f32::from_le_bytes(data[offset + 4..offset + 8].try_into().unwrap());
        let b = f32::from_le_bytes(data[offset + 8..offset + 12].try_into().unwrap());
        let a = f32::from_le_bytes(data[offset + 12..offset + 16].try_into().unwrap());
        return Ok((Value::Color(ColorRgba::new(r, g, b, a)), offset + 16));
    }
    if is_builtin(normalized) {
        return decode_builtin_scalar(normalized, data, offset);
    }
    decode_message(registry, normalized, data, offset)
}

/// Decode a typed value given an explicit type name (no envelope).
pub fn decode_typed(registry: &MessageRegistry, type_str: &str, payload: &[u8]) -> Result<Value> {
    let (value, consumed) = decode_value_raw(registry, type_str, payload, 0)?;
    if consumed != payload.len() {
        return Err(Error::TrailingBytes {
            label: "typed value",
            count: payload.len() - consumed,
        });
    }
    Ok(value)
}

/// Encode a typed envelope: `[type_byte][count:u32le][payload...]`.
pub fn encode(registry: &MessageRegistry, type_str: &str, data: &Value) -> Result<Vec<u8>> {
    if type_str == "std_msgs/Byte" {
        let value_payload = match data {
            Value::Bytes(b) => b.clone(),
            Value::Array(items) => {
                let mut bytes = Vec::with_capacity(items.len());
                for item in items {
                    bytes.push(coerce_u8(item)?);
                }
                bytes
            }
            Value::U8(v) => vec![*v],
            Value::I32(v) => vec![u8::try_from(*v)
                .map_err(|_| Error::InvalidValue(format!("byte out of range: {v}")))?],
            _ => vec![coerce_u8(data)?],
        };
        let mut out = Vec::with_capacity(5 + value_payload.len());
        out.push(type_byte_for(type_str));
        out.extend_from_slice(&(value_payload.len() as u32).to_le_bytes());
        out.extend_from_slice(&value_payload);
        return Ok(out);
    }

    let value_payload = encode_value_raw(registry, type_str, data)?;
    let type_byte = type_byte_for(type_str);
    if type_byte != DYNAMIC_TYPE_BYTE {
        let mut out = Vec::with_capacity(5 + value_payload.len());
        out.push(type_byte);
        out.extend_from_slice(&(value_payload.len() as u32).to_le_bytes());
        out.extend_from_slice(&value_payload);
        return Ok(out);
    }

    let type_name_bytes = type_str.as_bytes();
    let mut ext_payload = Vec::with_capacity(2 + type_name_bytes.len() + value_payload.len());
    ext_payload.extend_from_slice(&(type_name_bytes.len() as u16).to_le_bytes());
    ext_payload.extend_from_slice(type_name_bytes);
    ext_payload.extend_from_slice(&value_payload);

    let mut out = Vec::with_capacity(5 + ext_payload.len());
    out.push(DYNAMIC_TYPE_BYTE);
    out.extend_from_slice(&(ext_payload.len() as u32).to_le_bytes());
    out.extend_from_slice(&ext_payload);
    Ok(out)
}

/// Decode a typed envelope into `(type_name, value)`.
pub fn decode(registry: &MessageRegistry, data: &[u8]) -> Result<(String, Value)> {
    if data.is_empty() {
        return Err(Error::EmptyPayload);
    }
    require_bytes(data, 0, 5, "typed envelope")?;
    let type_byte = data[0];
    let count = read_u32_le(data, 1, "typed count")? as usize;
    require_bytes(data, 5, count, "typed payload")?;
    if 5 + count != data.len() {
        return Err(Error::TrailingBytes {
            label: "typed payload",
            count: data.len() - (5 + count),
        });
    }
    let payload = &data[5..5 + count];

    if type_byte == DYNAMIC_TYPE_BYTE {
        let type_name_len = read_u16_le(payload, 0, "dynamic type name length")? as usize;
        let type_name_start = 2;
        require_bytes(payload, type_name_start, type_name_len, "dynamic type name")?;
        let type_name_end = type_name_start + type_name_len;
        let type_name = std::str::from_utf8(&payload[type_name_start..type_name_end])?.to_owned();
        let value = decode_typed(registry, &type_name, &payload[type_name_end..])?;
        return Ok((type_name, value));
    }

    let type_name = type_name_from_byte(type_byte)?.to_owned();
    if type_name == "std_msgs/Byte" {
        return Ok((type_name, Value::Bytes(payload.to_vec())));
    }
    let value = decode_typed(registry, &type_name, payload)?;
    Ok((type_name, value))
}
