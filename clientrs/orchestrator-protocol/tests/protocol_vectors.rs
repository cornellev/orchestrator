use orchestrator_protocol::{
    decode, encode, encode_error_frame, encode_topic_name, load_message_definition,
    parse_topic_info, ColorRgba, Error, MessageRegistry, Value, MAX_TOPIC_NAME_LEN,
};
use serde_json::Value as JsonValue;
use std::collections::BTreeMap;

fn load_vectors() -> serde_json::Map<String, JsonValue> {
    let raw = include_str!("fixtures/protocol_vectors.json");
    serde_json::from_str::<JsonValue>(raw)
        .unwrap()
        .as_object()
        .unwrap()
        .clone()
}

fn json_to_value(v: &JsonValue) -> Value {
    match v {
        JsonValue::Null => Value::String(String::new()),
        JsonValue::Bool(b) => Value::Bool(*b),
        JsonValue::Number(n) => {
            if let Some(i) = n.as_i64() {
                if i >= i32::MIN as i64 && i <= i32::MAX as i64 && n.as_u64().is_none() {
                    // Prefer I32 when it fits and value is signed-looking; but for uint tests
                    // we need to look at context. Use I64 for large magnitudes.
                    if i >= 0 && i <= i32::MAX as i64 {
                        // Could be i32 or u32; keep as I64/U64 based on magnitude later.
                    }
                }
            }
            if let Some(u) = n.as_u64() {
                if u > i64::MAX as u64 {
                    return Value::U64(u);
                }
                if u > i32::MAX as u64 {
                    return Value::I64(u as i64);
                }
                // Prefer I32 for typical int32 fixtures; U32 for uint32_max handled via u64 path above
                if u == u32::MAX as u64 {
                    return Value::U32(u32::MAX);
                }
                return Value::I32(u as i32);
            }
            if let Some(i) = n.as_i64() {
                if i < i32::MIN as i64 || i > i32::MAX as i64 {
                    return Value::I64(i);
                }
                return Value::I32(i as i32);
            }
            Value::F64(n.as_f64().unwrap())
        }
        JsonValue::String(s) => Value::String(s.clone()),
        JsonValue::Array(items) => {
            // ColorRGBA fixtures are plain float arrays of length 4.
            if items.len() == 4 && items.iter().all(|x| x.as_f64().is_some()) {
                return Value::Color(ColorRgba::new(
                    items[0].as_f64().unwrap() as f32,
                    items[1].as_f64().unwrap() as f32,
                    items[2].as_f64().unwrap() as f32,
                    items[3].as_f64().unwrap() as f32,
                ));
            }
            Value::Array(items.iter().map(json_to_value).collect())
        }
        JsonValue::Object(map) => {
            if let Some(bytes) = map.get("__bytes__").and_then(|b| b.as_array()) {
                let data: Vec<u8> = bytes.iter().map(|x| x.as_u64().unwrap() as u8).collect();
                return Value::Bytes(data);
            }
            let mut out = BTreeMap::new();
            for (k, v) in map {
                out.insert(k.clone(), json_to_value(v));
            }
            Value::Message(out)
        }
    }
}

fn register_from_vector(registry: &MessageRegistry, vector: &JsonValue) {
    if let Some(def) = vector.get("definition").and_then(|d| d.as_str()) {
        let type_name = vector.get("type").and_then(|t| t.as_str()).unwrap();
        load_message_definition(registry, type_name, def).unwrap();
    }
    if let Some(defs) = vector.get("definitions").and_then(|d| d.as_object()) {
        for (type_name, def) in defs {
            load_message_definition(registry, type_name, def.as_str().unwrap()).unwrap();
        }
    }
}

fn value_for_type(type_name: &str, json: &JsonValue) -> Value {
    if let Some(s) = json.as_str() {
        match type_name {
            "std_msgs/Int32" => return Value::I32(s.parse().unwrap()),
            "std_msgs/Int64" => return Value::I64(s.parse().unwrap()),
            "std_msgs/UInt32" => return Value::U32(s.parse().unwrap()),
            "std_msgs/UInt64" => return Value::U64(s.parse().unwrap()),
            "std_msgs/Float32" => return Value::F32(s.parse().unwrap()),
            "std_msgs/Float64" => return Value::F64(s.parse().unwrap()),
            "std_msgs/Duration" => return Value::Duration(s.parse().unwrap()),
            _ => {}
        }
    }
    let mut value = json_to_value(json);
    match type_name {
        "std_msgs/Int32" => {
            if let Some(i) = json.as_i64() {
                value = Value::I32(i as i32);
            }
        }
        "std_msgs/Int64" => {
            if let Some(i) = json.as_i64() {
                value = Value::I64(i);
            }
        }
        "std_msgs/UInt32" => {
            if let Some(u) = json.as_u64() {
                value = Value::U32(u as u32);
            }
        }
        "std_msgs/UInt64" => {
            if let Some(u) = json.as_u64() {
                value = Value::U64(u);
            }
        }
        "std_msgs/Float32" => {
            if let Some(f) = json.as_f64() {
                value = Value::F32(f as f32);
            }
        }
        "std_msgs/Float64" | "std_msgs/Duration" => {
            if let Some(f) = json.as_f64() {
                value = if type_name == "std_msgs/Duration" {
                    Value::Duration(f)
                } else {
                    Value::F64(f)
                };
            }
        }
        _ => {}
    }
    value
}

fn approx_eq(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::F32(x), Value::F32(y)) => (x - y).abs() < 1e-5,
        (Value::F64(x), Value::F64(y)) => (x - y).abs() < 1e-9,
        (Value::F32(x), Value::F64(y)) => (f64::from(*x) - *y).abs() < 1e-5,
        (Value::F64(x), Value::F32(y)) => (*x - f64::from(*y)).abs() < 1e-5,
        (Value::Duration(x), Value::Duration(y)) => (x - y).abs() < 1e-9,
        (Value::Duration(x), Value::F64(y)) => (x - y).abs() < 1e-9,
        (Value::F64(x), Value::Duration(y)) => (x - y).abs() < 1e-9,
        (Value::Color(c1), Value::Color(c2)) => {
            (c1.r - c2.r).abs() < 1e-5
                && (c1.g - c2.g).abs() < 1e-5
                && (c1.b - c2.b).abs() < 1e-5
                && (c1.a - c2.a).abs() < 1e-5
        }
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(x, y)| approx_eq(x, y))
        }
        (Value::Message(a), Value::Message(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(k, v)| b.get(k).map(|o| approx_eq(v, o)).unwrap_or(false))
        }
        (Value::U32(x), Value::I32(y)) => i64::from(*x) == i64::from(*y),
        (Value::I32(x), Value::U32(y)) => i64::from(*x) == i64::from(*y),
        (Value::U64(x), Value::I64(y)) => i128::from(*x) == i128::from(*y),
        (Value::I64(x), Value::U64(y)) => i128::from(*x) == i128::from(*y),
        _ => a == b,
    }
}

#[test]
fn golden_vectors_round_trip() {
    let vectors = load_vectors();
    for (name, vector) in vectors {
        let registry = MessageRegistry::new();
        register_from_vector(&registry, &vector);
        let type_name = vector["type"].as_str().unwrap();
        let expected_hex = vector["hex"].as_str().unwrap();
        let value = value_for_type(type_name, &vector["value"]);
        let encoded = encode(&registry, type_name, &value).unwrap_or_else(|e| {
            panic!("encode failed for {name}: {e:?}");
        });
        assert_eq!(
            hex::encode(&encoded),
            expected_hex,
            "encode mismatch for {name}"
        );
        let (decoded_type, decoded_value) = decode(&registry, &encoded).unwrap();
        assert_eq!(decoded_type, type_name);
        let expected_value = value_for_type(type_name, &vector["value"]);
        assert!(
            approx_eq(&decoded_value, &expected_value),
            "decode mismatch for {name}: {decoded_value:?} != {expected_value:?}"
        );
    }
}

#[test]
fn char_rejects_non_ascii() {
    let registry = MessageRegistry::new();
    let err = encode(&registry, "std_msgs/Char", &Value::string("é")).unwrap_err();
    assert!(matches!(err, Error::InvalidChar(_)));
}

#[test]
fn truncated_payload_rejected() {
    let registry = MessageRegistry::new();
    let err = decode(&registry, &[0x02, 4, 0, 0, 0, 0x01]).unwrap_err();
    assert!(matches!(err, Error::Truncated { .. }));
}

#[test]
fn topic_name_limit() {
    encode_topic_name(&"x".repeat(MAX_TOPIC_NAME_LEN)).unwrap();
    assert!(matches!(
        encode_topic_name(&"x".repeat(MAX_TOPIC_NAME_LEN + 1)),
        Err(Error::TopicNameTooLong)
    ));
}

#[test]
fn error_frame_round_trip() {
    let frame = encode_error_frame("bad frame", 42);
    assert_eq!(frame[0], 0x84);
    let info = orchestrator_protocol::decode_error_payload(&frame[1..]).unwrap();
    assert_eq!(info.code, 42);
    assert_eq!(info.message, "bad frame");
}

#[test]
fn topic_info_parses_standard_type() {
    // topic_id=1 BE, type=String(0x01), dynamic_len=0, count=0, name="/t"
    let mut buf = Vec::new();
    buf.extend_from_slice(&1u32.to_be_bytes());
    buf.push(0x01);
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&0u32.to_le_bytes());
    buf.push(2);
    buf.extend_from_slice(b"/t");
    let (info, end) = parse_topic_info(&buf, 0).unwrap();
    assert_eq!(end, buf.len());
    assert_eq!(info.topic_id, 1);
    assert_eq!(info.type_str, "std_msgs/String");
    assert_eq!(info.name, "/t");
}

// Minimal hex helper without adding a dependency.
mod hex {
    pub fn encode(bytes: &[u8]) -> String {
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    }
}
