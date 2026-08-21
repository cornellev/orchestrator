//! Client error types.

use thiserror::Error;

/// Result alias for the WebSocket client.
pub type Result<T> = std::result::Result<T, Error>;

/// Errors produced by the Orchestrator WebSocket client.
#[derive(Debug, Error)]
pub enum Error {
    /// The client was stopped before the operation completed.
    #[error("client stopped")]
    Stopped,
    /// The client is not currently connected.
    #[error("websocket not connected")]
    NotConnected,
    /// Failed to establish or maintain a connection.
    #[error("connection failed: {0}")]
    Connection(String),
    /// Protocol encode/decode failure.
    #[error(transparent)]
    Protocol(#[from] orchestrator_protocol::Error),
    /// Invalid URI.
    #[error("invalid uri: {0}")]
    InvalidUri(String),
    /// Types API HTTP failure.
    #[cfg(feature = "types-api")]
    #[error("types api error: {0}")]
    TypesApi(String),
    /// Internal channel closed unexpectedly.
    #[error("client channel closed")]
    ChannelClosed,
}
