//! Publish a standard string to a running Orchestrator server.

use orchestrator_protocol::Value;
use orchestrator_ws_client::{Client, ClientEvent};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let uri = std::env::var("ORCH_WS_URI").unwrap_or_else(|_| "ws://127.0.0.1:8080".into());
    let (client, mut events) = Client::builder().uri(uri).connect().await?;

    client.subscribe().await?;
    client
        .publish(
            "/example",
            "std_msgs/String",
            Value::string("hello from Rust"),
        )
        .await?;

    let deadline = tokio::time::Instant::now() + tokio::time::Duration::from_secs(5);
    while tokio::time::Instant::now() < deadline {
        tokio::select! {
            event = events.recv() => {
                match event {
                    Some(ClientEvent::Update(update)) => {
                        println!(
                            "update on {}: {:?}",
                            update.name,
                            update.value
                        );
                        break;
                    }
                    Some(ClientEvent::ProtocolError(err)) => {
                        eprintln!("protocol error {}: {}", err.code, err.message);
                        break;
                    }
                    Some(other) => println!("event: {other:?}"),
                    None => break,
                }
            }
            _ = tokio::time::sleep_until(deadline) => {
                println!("timed out waiting for update");
                break;
            }
        }
    }

    client.stop().await?;
    Ok(())
}
