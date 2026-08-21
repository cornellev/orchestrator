//! Live integration against the in-repo Python WebSocket server.
//!
//! Requires Python deps (`websockets`) and is ignored by default so unit CI stays hermetic.
//! Run with: `cargo test -p orchestrator-ws-client --test integration -- --ignored --nocapture`

use orchestrator_protocol::{load_message_definition, MessageRegistry, Value};
use orchestrator_ws_client::{Client, ClientEvent};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::Duration;

struct PythonServer {
    child: Child,
    ws_port: u16,
    #[allow(dead_code)]
    api_port: u16,
}

impl Drop for PythonServer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

async fn wait_for_port(port: u16, timeout: Duration) {
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        if tokio::net::TcpStream::connect(("127.0.0.1", port))
            .await
            .is_ok()
        {
            return;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    panic!("timed out waiting for port {port}");
}

impl PythonServer {
    async fn spawn() -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .canonicalize()
            .expect("repo root");

        let ws_port = free_port();
        let api_port = free_port();

        let child = Command::new("python3")
            .arg("-u")
            .arg("main.py")
            .current_dir(&root)
            .env("WS_HOST", "127.0.0.1")
            .env("WS_PORT", ws_port.to_string())
            .env("API_HOST", "127.0.0.1")
            .env("API_PORT", api_port.to_string())
            .env("API_WRITE_TOKEN", "test-token")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("failed to spawn python main.py");

        wait_for_port(ws_port, Duration::from_secs(10)).await;
        wait_for_port(api_port, Duration::from_secs(5)).await;

        Self {
            child,
            ws_port,
            api_port,
        }
    }

    fn ws_uri(&self) -> String {
        format!("ws://127.0.0.1:{}", self.ws_port)
    }

    #[cfg(feature = "types-api")]
    fn api_base(&self) -> String {
        format!("http://127.0.0.1:{}", self.api_port)
    }
}

async fn wait_for_update(
    events: &mut orchestrator_ws_client::EventStream,
    timeout: Duration,
) -> Option<orchestrator_protocol::TopicUpdate> {
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        tokio::select! {
            event = events.recv() => {
                match event {
                    Some(ClientEvent::Update(update)) => return Some(update),
                    Some(ClientEvent::ProtocolError(err)) => {
                        panic!("unexpected protocol error: {} {}", err.code, err.message);
                    }
                    Some(_) => {}
                    None => return None,
                }
            }
            _ = tokio::time::sleep(remaining) => return None,
        }
    }
    None
}

#[tokio::test]
#[ignore = "requires local Python server dependencies"]
async fn publish_subscribe_round_trip() {
    let server = PythonServer::spawn().await;
    let (client, mut events) = Client::builder()
        .uri(server.ws_uri())
        .reconnect(false)
        .connect()
        .await
        .expect("connect");

    client
        .publish("/demo", "std_msgs/String", Value::string("hello"))
        .await
        .unwrap();

    let update = wait_for_update(&mut events, Duration::from_secs(3))
        .await
        .expect("update");
    assert_eq!(update.name, "/demo");
    assert_eq!(update.type_str, "std_msgs/String");
    assert_eq!(
        update.value.as_ref().and_then(|v| v.as_str()),
        Some("hello")
    );

    client.stop().await.unwrap();
}

#[tokio::test]
#[ignore = "requires local Python server dependencies"]
async fn type_mismatch_sends_error() {
    let server = PythonServer::spawn().await;
    let (client, mut events) = Client::builder()
        .uri(server.ws_uri())
        .reconnect(false)
        .connect()
        .await
        .expect("connect");

    client
        .publish("/typed", "std_msgs/Int32", Value::I32(1))
        .await
        .unwrap();
    let _ = wait_for_update(&mut events, Duration::from_secs(2)).await;

    client
        .publish("/typed", "std_msgs/String", Value::string("nope"))
        .await
        .unwrap();

    let deadline = tokio::time::Instant::now() + Duration::from_secs(3);
    let mut saw_error = false;
    while tokio::time::Instant::now() < deadline {
        tokio::select! {
            event = events.recv() => {
                if let Some(ClientEvent::ProtocolError(err)) = event {
                    assert!(err.message.contains("Type mismatch") || err.message.contains("mismatch") || err.code == 104);
                    saw_error = true;
                    break;
                }
            }
            _ = tokio::time::sleep(Duration::from_millis(50)) => {}
        }
    }
    assert!(saw_error, "expected protocol error for type mismatch");
    client.stop().await.unwrap();
}

#[tokio::test]
#[ignore = "requires local Python server dependencies"]
async fn dynamic_message_round_trip() {
    let server = PythonServer::spawn().await;
    let registry = Arc::new(MessageRegistry::new());
    load_message_definition(
        &registry,
        "geometry_msgs/Point32",
        "float32 x\nfloat32 y\nfloat32 z\n",
    )
    .unwrap();

    let (client, mut events) = Client::builder()
        .uri(server.ws_uri())
        .registry(Arc::clone(&registry))
        .reconnect(false)
        .connect()
        .await
        .expect("connect");

    let mut fields = std::collections::BTreeMap::new();
    fields.insert("x".into(), Value::F32(1.25));
    fields.insert("y".into(), Value::F32(-2.5));
    fields.insert("z".into(), Value::F32(3.75));

    client
        .publish("/point", "geometry_msgs/Point32", Value::Message(fields))
        .await
        .unwrap();

    let update = wait_for_update(&mut events, Duration::from_secs(3))
        .await
        .expect("update");
    assert_eq!(update.type_str, "geometry_msgs/Point32");
    let msg = update.value.as_ref().and_then(|v| v.as_message()).unwrap();
    match msg.get("x") {
        Some(Value::F32(v)) => assert!((v - 1.25).abs() < 1e-5),
        other => panic!("unexpected x: {other:?}"),
    }

    client.stop().await.unwrap();
}

#[cfg(feature = "types-api")]
#[tokio::test]
#[ignore = "requires local Python server dependencies"]
async fn types_api_sync_round_trip() {
    let server = PythonServer::spawn().await;
    let registry = MessageRegistry::new();
    let client = orchestrator_ws_client::TypesApiClient::new(server.api_base())
        .unwrap()
        .with_token("test-token");

    let mut defs = std::collections::BTreeMap::new();
    defs.insert("demo_msgs/Thing".into(), "int32 value\n".into());
    let sync = client.sync_types(&defs).await.expect("sync");
    assert_eq!(sync.count, 1);

    let loaded = orchestrator_ws_client::sync_types_from_server(
        &registry,
        &server.api_base(),
        None,
        Some("test-token"),
    )
    .await
    .expect("pull");
    assert!(loaded.contains_key("demo_msgs/Thing"));
    assert!(registry.contains("demo_msgs/Thing"));
}
