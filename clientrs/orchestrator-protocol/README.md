# orchestrator-protocol

Runtime-independent binary codec and ROS-style message schemas for the
Orchestrator WebSocket protocol.

This crate is the single source of truth for:

- Typed payload envelopes (`[type_byte][count:u32le][payload]`)
- All standard `std_msgs/*` type bytes
- Dynamic `0xFF` envelopes with nested `.msg` schemas
- Client/server frame layout (ops, responses, topic metadata, errors)

## License

Licensed under MIT OR Apache-2.0.
