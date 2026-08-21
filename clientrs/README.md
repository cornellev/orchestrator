# Orchestrator Rust Clients

Rust workspace providing wire-compatible clients for the Orchestrator WebSocket
server and Types API.

## Crates

| Crate | crates.io name | Description |
|-------|----------------|-------------|
| [`orchestrator-protocol`](orchestrator-protocol/) | `orchestrator-protocol` | Binary codec, schemas, and frame types |
| [`orchestrator-ws-client`](orchestrator-ws-client/) | `orchestrator-ws-client` | Async Tokio WebSocket client + Types REST sync |

## License

Licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT license ([LICENSE-MIT](LICENSE-MIT))

at your option.

## MSRV

Rust 1.88 or newer (required by the current dependency tree, including ICU crates used by the Types API HTTP client).

## Publishing

1. Publish `orchestrator-protocol` first:
   `cargo publish -p orchestrator-protocol`
2. Then publish `orchestrator-ws-client` (it depends on the crates.io version of
   `orchestrator-protocol`):
   `cargo publish -p orchestrator-ws-client`

Use `--dry-run` before any real publish. Do not publish as part of routine CI.
