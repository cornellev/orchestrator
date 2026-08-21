# Graph Report - .  (2026-08-20)

## Corpus Check
- Corpus is ~11,921 words - fits in a single context window. You may not need a graph.

## Summary
- 251 nodes · 439 edges · 22 communities (12 shown, 10 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 13 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- JavaScript Client
- Python Client
- Serialization Core
- ROS2 Bridge
- WebSocket Server
- Types API
- Protocol Documentation
- Application Entry Point
- Serialization Tests
- Browser Frontend
- Frontend Bootstrap
- Random Publisher Demo
- Schema Discovery Docs
- Echo Operation
- File Schema Loader
- Folder Schema Loader
- Root Schema Loader
- Publish Operation
- Request All Operation
- Subscribe Operation

## God Nodes (most connected - your core abstractions)
1. `OrchestratorClient` - 18 edges
2. `Client` - 17 edges
3. `ROSSim` - 14 edges
4. `TypesAPIHandler` - 13 edges
5. `ROS2Bridge` - 12 edges
6. `TypesAPIServer` - 9 edges
7. `main()` - 8 edges
8. `_ros_msg_to_value()` - 7 edges
9. `_dict_to_ros_msg()` - 7 edges
10. `CustomTypeSerializationTests` - 7 edges

## Surprising Connections (you probably didn't know these)
- `ClientCustomTopicsTests` --uses--> `OrchestratorClient`  [INFERRED]
  test/test_client_custom_topics.py → client/client.py
- `main()` --calls--> `ROS2Bridge`  [EXTRACTED]
  main.py → ros.py
- `main()` --calls--> `WebSocketServer`  [EXTRACTED]
  main.py → ws.py
- `TypesAPITests` --uses--> `TypesAPIServer`  [INFERRED]
  test/test_types_api.py → types_api.py
- `Orchestrator WebSocket Server` --references--> `websockets`  [EXTRACTED]
  readme.md → requirements.txt

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Shared Client Operation Surface** — readme_javascript_client, readme_python_client, readme_echo, readme_subscribe, readme_request_all, readme_publish [EXTRACTED 1.00]
- **Binary Protocol Response Family** — readme_shared_binary_protocol, readme_echo_response, readme_update_response, readme_big_update_response [EXTRACTED 1.00]
- **Dynamic Message Loading APIs** — readme_dynamic_ros_message_schemas, readme_load_message_file, readme_load_message_folder, readme_load_message_root [EXTRACTED 1.00]

## Communities (22 total, 10 thin omitted)

### Community 0 - "JavaScript Client"
Cohesion: 0.08
Nodes (30): buildTopicData(), Client, _concatBuffers(), _decodePrimitive(), decoder, _decodeTypedValue(), decodeValue(), DYNAMIC_SCHEMAS (+22 more)

### Community 1 - "Python Client"
Cohesion: 0.12
Nodes (16): _build_topic_data(), _collect_msg_definitions(), maybe_await(), OrchestratorClient, _parse_big_update(), _parse_topic_info(), _parse_update(), Path (+8 more)

### Community 2 - "Serialization Core"
Cohesion: 0.16
Nodes (25): PathLike, _auto_discover_message_defs(), decode(), _decode_builtin_scalar(), _decode_field(), _decode_message(), decode_typed(), _decode_value_raw() (+17 more)

### Community 3 - "ROS2 Bridge"
Cohesion: 0.14
Nodes (18): Any, _dict_to_ros_msg(), _ensure_orch_schema_for_ros_msg(), _orch_to_ros_msg_type(), _orch_value_hash(), Ensure a dynamic schema exists in serialization.message_registry for ros_msg_typ, Best-effort conversion of a ROS2 message instance into a rosidl type string pkg/, Convert ROS2 message instance into orchestrator-compatible value (scalar or nest (+10 more)

### Community 4 - "WebSocket Server"
Cohesion: 0.16
Nodes (6): AbstractEventLoop, construct_topicData(), decode_topicData(), encode_topic_value(), ROSSim, WebSocketServer

### Community 5 - "Types API"
Cohesion: 0.18
Nodes (6): BaseHTTPRequestHandler, HTTPStatus, CustomTypeStore, Path, StoredType, TypesAPIHandler

### Community 6 - "Protocol Documentation"
Cohesion: 0.13
Nodes (17): big_update Response, Custom Type Synchronization, Persisted Custom Type Store, echo Response, JavaScript Client, Orchestrator WebSocket Server, Python OrchestratorClient, REST API for Custom Type Sync (+9 more)

### Community 7 - "Application Entry Point"
Cohesion: 0.20
Nodes (7): _env_bool(), _env_float(), _env_int(), main(), ROS2BridgeConfig, TypesAPITests, TypesAPIServer

### Community 9 - "Browser Frontend"
Cohesion: 0.48
Nodes (4): escapeHtml(), formatValueForCell(), renderTopics(), toReadable()

### Community 10 - "Frontend Bootstrap"
Cohesion: 0.50
Nodes (4): Bootstrap 5.3.8, Client.js Browser Client, HTML Document, Frontend Script

## Knowledge Gaps
- **23 isolated node(s):** `OP_CODES`, `RESP_CODES`, `TYPE_ENCODERS`, `TYPE_DECODERS`, `STD_ALIASES` (+18 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TypesAPIHandler` connect `Types API` to `Application Entry Point`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **What connects `OP_CODES`, `RESP_CODES`, `TYPE_ENCODERS` to the rest of the system?**
  _23 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `JavaScript Client` be split into smaller, more focused modules?**
  _Cohesion score 0.08048103607770583 - nodes in this community are weakly interconnected._
- **Should `Python Client` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._
- **Should `ROS2 Bridge` be split into smaller, more focused modules?**
  _Cohesion score 0.14245014245014245 - nodes in this community are weakly interconnected._
- **Should `Protocol Documentation` be split into smaller, more focused modules?**
  _Cohesion score 0.1323529411764706 - nodes in this community are weakly interconnected._