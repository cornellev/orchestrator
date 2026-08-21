//! Client event stream types.

use orchestrator_protocol::{ProtocolErrorInfo, TopicInfo, TopicUpdate, Value};
use std::collections::BTreeMap;
use tokio::sync::mpsc;

/// Events emitted by the WebSocket client.
#[derive(Debug, Clone, PartialEq)]
pub enum ClientEvent {
    /// The WebSocket connection became ready.
    Connected,
    /// The WebSocket connection closed (may reconnect).
    Disconnected,
    /// Echo response with topic metadata.
    Echo(Vec<TopicInfo>),
    /// Newly announced topic.
    NewTopic(TopicInfo),
    /// Topic value update.
    Update(TopicUpdate),
    /// Full snapshot of topic values.
    BigUpdate(BTreeMap<String, (String, Value)>),
    /// Server protocol error frame (`0x84`).
    ProtocolError(ProtocolErrorInfo),
    /// Local parse / unknown-opcode error while processing a frame.
    LocalError(String),
}

/// Owned receiver for [`ClientEvent`]s.
#[derive(Debug)]
pub struct EventStream {
    rx: mpsc::UnboundedReceiver<ClientEvent>,
}

impl EventStream {
    pub(crate) fn new(rx: mpsc::UnboundedReceiver<ClientEvent>) -> Self {
        Self { rx }
    }

    /// Receive the next event, waiting if necessary.
    pub async fn recv(&mut self) -> Option<ClientEvent> {
        self.rx.recv().await
    }

    /// Non-blocking poll for the next event.
    pub fn try_recv(&mut self) -> Result<ClientEvent, mpsc::error::TryRecvError> {
        self.rx.try_recv()
    }
}
