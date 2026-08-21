//! Async Tokio WebSocket client for the Orchestrator server.

#![cfg_attr(docsrs, feature(doc_cfg))]
#![deny(missing_docs)]

mod client;
mod error;
mod events;

#[cfg(feature = "types-api")]
mod types_api;

pub use client::{Client, ClientBuilder, ClientHandle};
pub use error::{Error, Result};
pub use events::{ClientEvent, EventStream};

#[cfg(feature = "types-api")]
#[cfg_attr(docsrs, doc(cfg(feature = "types-api")))]
pub use types_api::{
    sync_types_folder_to_server, sync_types_from_server, sync_types_to_server, TypeDefinition,
    TypesApiClient, TypesListResponse, TypesSyncResponse,
};
