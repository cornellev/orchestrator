//! WebSocket client implementation.

use crate::error::{Error, Result};
use crate::events::{ClientEvent, EventStream};
use futures_util::{SinkExt, StreamExt};
use orchestrator_protocol::{
    build_publish_frame, build_request_frame, decode_response, MessageRegistry, Operation,
    Response, Value,
};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, oneshot, watch, Mutex};
use tokio_tungstenite::{connect_async, tungstenite::Message};

enum Command {
    Send {
        bytes: Vec<u8>,
        ack: oneshot::Sender<Result<()>>,
    },
    Stop {
        ack: oneshot::Sender<()>,
    },
}

/// Builder for [`Client`].
#[derive(Debug, Clone)]
pub struct ClientBuilder {
    uri: String,
    reconnect: bool,
    backoff: Duration,
    backoff_max: Duration,
    auto_subscribe: bool,
    registry: Option<Arc<MessageRegistry>>,
}

impl Default for ClientBuilder {
    fn default() -> Self {
        Self {
            uri: "ws://127.0.0.1:8080".to_owned(),
            reconnect: true,
            backoff: Duration::from_millis(500),
            backoff_max: Duration::from_secs(10),
            auto_subscribe: true,
            registry: None,
        }
    }
}

impl ClientBuilder {
    /// Create a builder with defaults matching the Python client.
    pub fn new() -> Self {
        Self::default()
    }

    /// WebSocket URI (`ws://` or `wss://`).
    pub fn uri(mut self, uri: impl Into<String>) -> Self {
        self.uri = uri.into();
        self
    }

    /// Enable or disable automatic reconnection.
    pub fn reconnect(mut self, reconnect: bool) -> Self {
        self.reconnect = reconnect;
        self
    }

    /// Initial reconnect backoff delay.
    pub fn backoff(mut self, backoff: Duration) -> Self {
        self.backoff = backoff;
        self
    }

    /// Maximum reconnect backoff delay.
    pub fn backoff_max(mut self, backoff_max: Duration) -> Self {
        self.backoff_max = backoff_max;
        self
    }

    /// Whether to send `subscribe` automatically after each successful connect.
    pub fn auto_subscribe(mut self, auto_subscribe: bool) -> Self {
        self.auto_subscribe = auto_subscribe;
        self
    }

    /// Shared message registry used for dynamic encode/decode.
    pub fn registry(mut self, registry: Arc<MessageRegistry>) -> Self {
        self.registry = Some(registry);
        self
    }

    /// Build a client and event stream without connecting.
    ///
    /// Call [`Client::start`] to begin the connection loop.
    pub fn build(self) -> (Client, EventStream) {
        let registry = self
            .registry
            .unwrap_or_else(|| Arc::new(MessageRegistry::new()));
        let (event_tx, event_rx) = mpsc::unbounded_channel();
        let (cmd_tx, cmd_rx) = mpsc::unbounded_channel::<Command>();
        let connected_flag = Arc::new(AtomicBool::new(false));
        let stopped = Arc::new(AtomicBool::new(true));
        let want_subscribe = Arc::new(AtomicBool::new(self.auto_subscribe));

        let handle = ClientHandle {
            cmd_tx: cmd_tx.clone(),
            registry: Arc::clone(&registry),
            want_subscribe: Arc::clone(&want_subscribe),
            connected_flag: Arc::clone(&connected_flag),
            stopped: Arc::clone(&stopped),
        };

        let client = Client {
            handle,
            uri: self.uri,
            reconnect: self.reconnect,
            backoff: self.backoff,
            backoff_max: self.backoff_max,
            registry,
            event_tx,
            cmd_tx,
            cmd_rx: Mutex::new(Some(cmd_rx)),
            connected_flag,
            stopped,
            want_subscribe,
            join: Mutex::new(None),
            state_rx: Mutex::new(None),
        };

        (client, EventStream::new(event_rx))
    }

    /// Build and [`Client::start`] in one step.
    pub async fn connect(self) -> Result<(Client, EventStream)> {
        let auto_subscribe = self.auto_subscribe;
        let (client, events) = self.build();
        client.start(auto_subscribe).await?;
        Ok((client, events))
    }
}

#[derive(Debug, Clone)]
enum RunnerState {
    Starting,
    Connected,
    Reconnecting,
    Failed(String),
    Stopped,
}

/// Clonable command handle for sending operations.
#[derive(Debug, Clone)]
pub struct ClientHandle {
    cmd_tx: mpsc::UnboundedSender<Command>,
    registry: Arc<MessageRegistry>,
    want_subscribe: Arc<AtomicBool>,
    connected_flag: Arc<AtomicBool>,
    stopped: Arc<AtomicBool>,
}

impl ClientHandle {
    /// Shared message registry.
    pub fn registry(&self) -> Arc<MessageRegistry> {
        Arc::clone(&self.registry)
    }

    /// Whether the socket is currently connected.
    pub fn is_connected(&self) -> bool {
        self.connected_flag.load(Ordering::SeqCst)
    }

    /// Ask the server for the current topic list.
    pub async fn echo(&self) -> Result<()> {
        self.send_raw(build_request_frame(Operation::Echo)).await
    }

    /// Subscribe to topic updates.
    pub async fn subscribe(&self) -> Result<()> {
        self.want_subscribe.store(true, Ordering::SeqCst);
        self.send_raw(build_request_frame(Operation::Subscribe))
            .await
    }

    /// Request a full snapshot of topic values.
    pub async fn request_all(&self) -> Result<()> {
        self.send_raw(build_request_frame(Operation::RequestAll))
            .await
    }

    /// Publish a typed value to a topic.
    pub async fn publish(&self, topic: &str, type_str: &str, data: Value) -> Result<()> {
        let frame = build_publish_frame(&self.registry, topic, type_str, &data)?;
        self.send_raw(frame).await
    }

    async fn send_raw(&self, bytes: Vec<u8>) -> Result<()> {
        if self.stopped.load(Ordering::SeqCst) {
            return Err(Error::Stopped);
        }
        let (ack_tx, ack_rx) = oneshot::channel();
        self.cmd_tx
            .send(Command::Send { bytes, ack: ack_tx })
            .map_err(|_| Error::ChannelClosed)?;
        ack_rx.await.map_err(|_| Error::ChannelClosed)?
    }
}

/// Owned Orchestrator WebSocket client.
#[derive(Debug)]
pub struct Client {
    handle: ClientHandle,
    uri: String,
    reconnect: bool,
    backoff: Duration,
    backoff_max: Duration,
    registry: Arc<MessageRegistry>,
    event_tx: mpsc::UnboundedSender<ClientEvent>,
    cmd_tx: mpsc::UnboundedSender<Command>,
    cmd_rx: Mutex<Option<mpsc::UnboundedReceiver<Command>>>,
    connected_flag: Arc<AtomicBool>,
    stopped: Arc<AtomicBool>,
    want_subscribe: Arc<AtomicBool>,
    join: Mutex<Option<tokio::task::JoinHandle<Result<()>>>>,
    state_rx: Mutex<Option<watch::Receiver<RunnerState>>>,
}

impl Client {
    /// Start building a client.
    pub fn builder() -> ClientBuilder {
        ClientBuilder::new()
    }

    /// Clonable handle for concurrent publishing from other tasks.
    pub fn handle(&self) -> ClientHandle {
        self.handle.clone()
    }

    /// Shared message registry.
    pub fn registry(&self) -> Arc<MessageRegistry> {
        Arc::clone(&self.registry)
    }

    /// Whether the socket is currently connected.
    pub fn is_connected(&self) -> bool {
        self.handle.is_connected()
    }

    /// Start the connection loop and wait until connected (or fail if reconnect is disabled).
    pub async fn start(&self, auto_subscribe: bool) -> Result<()> {
        self.want_subscribe.store(auto_subscribe, Ordering::SeqCst);
        self.stopped.store(false, Ordering::SeqCst);

        let mut join_guard = self.join.lock().await;
        if let Some(handle) = join_guard.as_ref() {
            if !handle.is_finished() {
                drop(join_guard);
                return self.wait_until_connected().await;
            }
        }

        let cmd_rx = self
            .cmd_rx
            .lock()
            .await
            .take()
            .ok_or_else(|| Error::Connection("client already started".into()))?;
        let (state_tx, state_rx) = watch::channel(RunnerState::Starting);
        *self.state_rx.lock().await = Some(state_rx);

        let runner = Runner {
            uri: self.uri.clone(),
            reconnect: self.reconnect,
            backoff: self.backoff,
            backoff_max: self.backoff_max,
            registry: Arc::clone(&self.registry),
            event_tx: self.event_tx.clone(),
            cmd_rx,
            state_tx,
            connected_flag: Arc::clone(&self.connected_flag),
            stopped: Arc::clone(&self.stopped),
            want_subscribe: Arc::clone(&self.want_subscribe),
        };
        *join_guard = Some(tokio::spawn(runner.run()));
        drop(join_guard);

        self.wait_until_connected().await
    }

    async fn wait_until_connected(&self) -> Result<()> {
        let mut state_rx = self
            .state_rx
            .lock()
            .await
            .clone()
            .ok_or_else(|| Error::Connection("client not started".into()))?;

        loop {
            let state = state_rx.borrow_and_update().clone();
            match state {
                RunnerState::Connected => return Ok(()),
                RunnerState::Failed(msg) => return Err(Error::Connection(msg)),
                RunnerState::Stopped => return Err(Error::Stopped),
                RunnerState::Starting | RunnerState::Reconnecting => {
                    if state_rx.changed().await.is_err() {
                        return Err(Error::Connection("runner exited".into()));
                    }
                }
            }
        }
    }

    /// Ask the server for the current topic list.
    pub async fn echo(&self) -> Result<()> {
        self.handle.echo().await
    }

    /// Subscribe to topic updates.
    pub async fn subscribe(&self) -> Result<()> {
        self.handle.subscribe().await
    }

    /// Request a full snapshot of topic values.
    pub async fn request_all(&self) -> Result<()> {
        self.handle.request_all().await
    }

    /// Publish a typed value to a topic.
    pub async fn publish(&self, topic: &str, type_str: &str, data: Value) -> Result<()> {
        self.handle.publish(topic, type_str, data).await
    }

    /// Stop the client and wait for the background task to exit.
    pub async fn stop(&self) -> Result<()> {
        self.stopped.store(true, Ordering::SeqCst);
        let (ack_tx, ack_rx) = oneshot::channel();
        let _ = self.cmd_tx.send(Command::Stop { ack: ack_tx });
        let _ = tokio::time::timeout(Duration::from_secs(2), ack_rx).await;

        let mut join_guard = self.join.lock().await;
        if let Some(handle) = join_guard.take() {
            let _ = handle.await;
        }
        Ok(())
    }
}

struct Runner {
    uri: String,
    reconnect: bool,
    backoff: Duration,
    backoff_max: Duration,
    registry: Arc<MessageRegistry>,
    event_tx: mpsc::UnboundedSender<ClientEvent>,
    cmd_rx: mpsc::UnboundedReceiver<Command>,
    state_tx: watch::Sender<RunnerState>,
    connected_flag: Arc<AtomicBool>,
    stopped: Arc<AtomicBool>,
    want_subscribe: Arc<AtomicBool>,
}

impl Runner {
    async fn run(mut self) -> Result<()> {
        let mut delay = self.backoff;
        let mut last_error: Option<Error> = None;
        let mut ever_connected = false;

        while !self.stopped.load(Ordering::SeqCst) {
            match self.session().await {
                Ok(()) => {
                    delay = self.backoff;
                    last_error = None;
                    ever_connected = true;
                }
                Err(Error::Stopped) => {
                    let _ = self.state_tx.send(RunnerState::Stopped);
                    break;
                }
                Err(err) => {
                    last_error = Some(err);
                    self.connected_flag.store(false, Ordering::SeqCst);
                    let _ = self.event_tx.send(ClientEvent::Disconnected);
                    if !self.reconnect || self.stopped.load(Ordering::SeqCst) {
                        break;
                    }
                    let _ = self.state_tx.send(RunnerState::Reconnecting);
                    tokio::select! {
                        _ = tokio::time::sleep(delay) => {}
                        cmd = self.cmd_rx.recv() => {
                            match cmd {
                                Some(Command::Stop { ack }) => {
                                    self.stopped.store(true, Ordering::SeqCst);
                                    let _ = ack.send(());
                                    let _ = self.state_tx.send(RunnerState::Stopped);
                                    return Ok(());
                                }
                                Some(Command::Send { ack, .. }) => {
                                    let _ = ack.send(Err(Error::NotConnected));
                                }
                                None => {
                                    let _ = self.state_tx.send(RunnerState::Stopped);
                                    return Ok(());
                                }
                            }
                        }
                    }
                    delay = std::cmp::min(self.backoff_max, delay.saturating_mul(2));
                }
            }
        }

        self.connected_flag.store(false, Ordering::SeqCst);
        if self.stopped.load(Ordering::SeqCst) {
            let _ = self.state_tx.send(RunnerState::Stopped);
            Ok(())
        } else if let Some(err) = last_error {
            if !ever_connected {
                let _ = self.state_tx.send(RunnerState::Failed(err.to_string()));
            }
            Err(err)
        } else {
            Ok(())
        }
    }

    async fn session(&mut self) -> Result<()> {
        let connect = connect_async(&self.uri);
        tokio::pin!(connect);

        let (ws, _) = loop {
            tokio::select! {
                result = &mut connect => {
                    break result.map_err(|e| Error::Connection(e.to_string()))?;
                }
                cmd = self.cmd_rx.recv() => {
                    match cmd {
                        Some(Command::Stop { ack }) => {
                            self.stopped.store(true, Ordering::SeqCst);
                            let _ = ack.send(());
                            return Err(Error::Stopped);
                        }
                        Some(Command::Send { ack, .. }) => {
                            let _ = ack.send(Err(Error::NotConnected));
                        }
                        None => return Err(Error::ChannelClosed),
                    }
                }
            }
        };
        let (mut sink, mut stream) = ws.split();

        self.connected_flag.store(true, Ordering::SeqCst);
        let _ = self.state_tx.send(RunnerState::Connected);
        let _ = self.event_tx.send(ClientEvent::Connected);

        if self.want_subscribe.load(Ordering::SeqCst) {
            sink.send(Message::Binary(
                build_request_frame(Operation::Subscribe).into(),
            ))
            .await
            .map_err(|e| Error::Connection(e.to_string()))?;
        }

        loop {
            tokio::select! {
                cmd = self.cmd_rx.recv() => {
                    match cmd {
                        Some(Command::Stop { ack }) => {
                            self.stopped.store(true, Ordering::SeqCst);
                            let _ = sink.close().await;
                            let _ = ack.send(());
                            return Err(Error::Stopped);
                        }
                        Some(Command::Send { bytes, ack }) => {
                            let result = sink
                                .send(Message::Binary(bytes.into()))
                                .await
                                .map_err(|e| Error::Connection(e.to_string()));
                            let _ = ack.send(result.map(|_| ()));
                        }
                        None => {
                            let _ = sink.close().await;
                            return Err(Error::ChannelClosed);
                        }
                    }
                }
                msg = stream.next() => {
                    match msg {
                        Some(Ok(Message::Binary(data))) => {
                            self.dispatch_binary(&data);
                        }
                        Some(Ok(Message::Close(_))) | None => {
                            self.connected_flag.store(false, Ordering::SeqCst);
                            let _ = self.event_tx.send(ClientEvent::Disconnected);
                            return Err(Error::Connection("connection closed".into()));
                        }
                        Some(Ok(_)) => {}
                        Some(Err(err)) => {
                            self.connected_flag.store(false, Ordering::SeqCst);
                            let _ = self.event_tx.send(ClientEvent::Disconnected);
                            return Err(Error::Connection(err.to_string()));
                        }
                    }
                }
            }
        }
    }

    fn dispatch_binary(&self, data: &[u8]) {
        match decode_response(&self.registry, data) {
            Ok(Response::Echo(topics)) => {
                let _ = self.event_tx.send(ClientEvent::Echo(topics));
            }
            Ok(Response::EchoNew(info)) => {
                let _ = self.event_tx.send(ClientEvent::NewTopic(info));
            }
            Ok(Response::Update(update)) => {
                let _ = self.event_tx.send(ClientEvent::Update(update));
            }
            Ok(Response::BigUpdate(map)) => {
                let _ = self.event_tx.send(ClientEvent::BigUpdate(map));
            }
            Ok(Response::Error(info)) => {
                let _ = self.event_tx.send(ClientEvent::ProtocolError(info));
            }
            Err(err) => {
                let _ = self.event_tx.send(ClientEvent::LocalError(err.to_string()));
            }
        }
    }
}
