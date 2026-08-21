# orchestrator-ws-client

Async Tokio WebSocket client for the Orchestrator server, with optional Types
REST API sync for dynamic message schemas.

## Quick start

```rust,no_run
use orchestrator_protocol::{Value, MessageRegistry};
use orchestrator_ws_client::{Client, ClientEvent};
use std::sync::Arc;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let registry = Arc::new(MessageRegistry::new());
    let (client, mut events) = Client::builder()
        .uri("ws://127.0.0.1:8080")
        .registry(registry)
        .connect()
        .await?;

    client.subscribe().await?;
    client.publish("/example", "std_msgs/String", Value::String("hello".into())).await?;

    while let Some(event) = events.recv().await {
        println!("{event:?}");
        if matches!(event, ClientEvent::Update(_)) {
            break;
        }
    }
    client.stop().await?;
    Ok(())
}
```

## Features

- `types-api` (default): REST client for `/api/types*`
- `rustls-tls` (default): TLS via rustls
- `native-tls`: TLS via native-tls

## License

Licensed under MIT OR Apache-2.0.
