//! Binary protocol codec and ROS-style message schemas for Orchestrator.

#![cfg_attr(docsrs, feature(doc_cfg))]
#![deny(missing_docs)]

mod codec;
mod error;
mod frames;
mod schema;
mod types;
mod value;

pub use codec::{decode, decode_typed, encode, encode_topic_name};
pub use error::{Error, Result};
pub use frames::{
    build_publish_frame, build_request_frame, build_topic_data, decode_error_payload,
    decode_response, encode_error_frame, parse_big_update, parse_echo, parse_topic_info,
    parse_update, Operation, ProtocolErrorInfo, Response, ResponseKind, TopicInfo, TopicUpdate,
    MAX_TOPIC_NAME_LEN,
};
pub use schema::{
    discover_message_defs, load_message_definition, load_message_file, load_message_folder,
    load_message_root, FieldDef, MessageDef, MessageRegistry,
};
pub use types::{type_byte_for, type_name_from_byte, DYNAMIC_TYPE_BYTE, STANDARD_TYPE_BYTES};
pub use value::{ColorRgba, TimeValue, Value};
