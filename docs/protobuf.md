# Protobuf and Zenoh

Install `requirements-protobuf.txt`, install the checked router with
`python scripts/install_zenoh.py`, and start one loopback `zenohd`. Then run:

```sh
orch --zenoh-profile cev-onboarding-v1 --zenoh-connect tcp/127.0.0.1:7447
```

Existing binary WebSocket, ROS, and `orch`/`json` Zenoh modes remain compatible.
Protobuf profile mode declares explicit routes and does not mirror a wildcard
namespace. This feature does not execute scripts or map arbitrary field paths.

Register a profile with `PUT /api/protobuf/profiles/<id>`:

```json
{
  "descriptor": "base64 FileDescriptorSet, including imported definitions",
  "fingerprint": "SHA-256 of the exact descriptor bytes",
  "routes": [{
    "id": "note",
    "type": "example.Note",
    "key": "team/{run_id}/note",
    "ws_publish": true,
    "ws_subscribe": true
  }]
}
```

Keys are literal or substitute `{run_id}`. Types are resolved from descriptors;
adding another ordinary message does not require Python changes. Profiles have
at most 64 unique routes. Descriptors are bounded by the HTTP body limit and
700000 decoded bytes. An invalid registration preserves the previous profile;
an in-use profile cannot be replaced. Registration is process-local: rerun the
project's setup after restarting orchestrator.

`GET /api/protobuf/profiles/<id>` returns routes, fingerprint, protocol version,
and active run status. `POST /api/protobuf/runs` prepares
`{profile_id, fingerprint, run_id}`; `POST /api/protobuf/runs/<id>/activate`
activates it. `DELETE /api/protobuf/runs/<id>` stops and retires it. One prepared
run is allowed per server. A retired ID cannot be reused in that process.
The onboarding profile additionally requires calibrated/training vehicle data,
run information, scoped sensor/command topics, and browser identity on activation.
`GET /api/protobuf/runs` checks status and renews the onboarding launcher's lease;
the launcher calls it every 250 ms. Lost launcher, stale source, and invalid
command failures stop motion and require a new run.

The simulator Client offers `bindProtobuf({runId, fingerprint})`,
`publishProtobuf(routeId, value)`, `subscribeProtobuf(routeId, callback)`, and
`unsubscribeProtobuf(routeId)`. Protobuf frames are WebSocket **text**, with
`protocol: "orch.protobuf.v1"`, `op`, `run_id`, `fingerprint`, and `request_id`.
Operations are `hello`, `publish`, `subscribe`, and `unsubscribe`; route operations
add `route`, and publications add `value`. Replies are `ack` or `error` with the
request ID. Subscribed clients receive `sample` with route/run/fingerprint/value.
Binary legacy subscribers never receive these samples unless they opt in.

Values follow ProtoJSON, including decimal strings for 64-bit integers and base64
for bytes. Python's official Protobuf library validates and encodes them. Zenoh
carries binary Protobuf. The reverse path decodes binary samples into ProtoJSON.
Unknown fields, wrong routes, wrong schema fingerprints, and prohibited directions
are rejected. Acknowledgements confirm routing acceptance, not vehicle application.
Node traffic stays on Zenoh; only browser subscribers and legacy adapters cause
orchestrator subscriptions. Per-client pending samples retain only the latest
sample per route. No command storage or automatic resume is provided.

Four optional onboarding adapters preserve current simulator contracts:
`pointcloud2-v1`, `tf-state-v1`, `command-v1`, and `path-overlay-v1`. They interpret
sensor frames/bytes, rear axle geometry, steering, deadlines, and display axes.
They share the generic codec/router; their names do not introduce a mapping DSL.

Validate the actual JS/Python/Zenoh/Rust path after building the onboarding examples:

```sh
python scripts/check_protobuf_live.py --onboarding /path/to/freshmen-onboarding --sim /path/to/ev-sim
```

Optional endpoints: `CEV_ORCHESTRATOR_API`, `CEV_ORCHESTRATOR_WS`, and
`CEV_ZENOH_ENDPOINT`. The browser itself uses `NEXT_PUBLIC_ORCHESTRATOR_API` and
`NEXT_PUBLIC_ORCHESTRATOR_WS` at build/start time. Run this check on an idle isolated
orchestrator: it prepares and then removes its own run. Visual message blocks and
team-wide schema governance are separate follow-ups.
