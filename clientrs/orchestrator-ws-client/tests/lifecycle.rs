use orchestrator_protocol::Value;
use orchestrator_ws_client::{Client, Error};
use std::time::Duration;

#[tokio::test]
async fn start_fails_fast_when_server_unreachable() {
    let (client, _events) = Client::builder()
        .uri("ws://127.0.0.1:1")
        .reconnect(false)
        .backoff(Duration::from_millis(10))
        .build();
    let result = client.start(true).await;
    assert!(matches!(result, Err(Error::Connection(_))));
}

#[tokio::test]
async fn stop_unblocks_start_wait() {
    let (client, _events) = Client::builder()
        .uri("ws://127.0.0.1:1")
        .reconnect(true)
        .backoff(Duration::from_millis(50))
        .build();

    let start = {
        let client = &client;
        async move { client.start(true).await }
    };
    tokio::pin!(start);

    tokio::select! {
        _ = &mut start => {
            // May fail with Stopped if stop wins; either way should not hang.
        }
        _ = async {
            tokio::time::sleep(Duration::from_millis(100)).await;
            client.stop().await.unwrap();
        } => {
            let result = tokio::time::timeout(Duration::from_secs(2), start).await;
            assert!(result.is_ok(), "start should unblock after stop");
            let start_result = result.unwrap();
            assert!(
                matches!(start_result, Err(Error::Stopped) | Err(Error::Connection(_))),
                "unexpected start result: {start_result:?}"
            );
        }
    }
}

#[tokio::test]
async fn publish_after_stop_raises() {
    let (client, _events) = Client::builder()
        .uri("ws://127.0.0.1:1")
        .reconnect(false)
        .build();
    client.stop().await.unwrap();
    let err = client
        .publish("/x", "std_msgs/Int32", Value::I32(1))
        .await
        .unwrap_err();
    assert!(matches!(err, Error::Stopped | Error::ChannelClosed));
}
