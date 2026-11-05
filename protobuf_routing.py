"""Descriptor-driven Protobuf routing. No simulator or project schemas are imported."""
import base64
import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, json_format

PROTOCOL = "orch.protobuf.v1"
MAX_PAYLOAD = 8 * 1024 * 1024
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


class Profile:
    def __init__(self, value):
        if not isinstance(value, dict):
            raise ValueError("Profile must be an object")
        if "onboarding" in value and not isinstance(value["onboarding"], bool):
            raise ValueError("onboarding must be a boolean")
        self.value = json.loads(json.dumps(value))
        raw = base64.b64decode(value["descriptor"], validate=True)
        if not raw or len(raw) > 700_000:
            raise ValueError("Descriptor must contain 1..700000 bytes")
        self.fingerprint = hashlib.sha256(raw).hexdigest()
        if value.get("fingerprint") != self.fingerprint:
            raise ValueError("Descriptor fingerprint mismatch")
        try:
            files = descriptor_pb2.FileDescriptorSet.FromString(raw)
        except Exception as exc:
            raise ValueError("Malformed descriptor set") from exc
        self.pool = descriptor_pool.DescriptorPool()
        pending = list(files.file)
        while pending:
            remaining = []
            for file in pending:
                try:
                    self.pool.Add(file)
                except (TypeError, KeyError):
                    remaining.append(file)
            if len(remaining) == len(pending):
                raise ValueError("Descriptor has unresolved imports or duplicate types")
            pending = remaining
        routes = value["routes"]
        if not isinstance(routes, list) or not 1 <= len(routes) <= 64:
            raise ValueError("Profile needs 1..64 routes")
        self.routes = {}
        keys = set()
        from protobuf_sim import ADAPTERS, ADAPTER_TYPES
        for route in routes:
            if not isinstance(route, dict) or not all(isinstance(route.get(k), str) for k in ("id", "key", "type")):
                raise ValueError("Route id, key, and type must be strings")
            if any(not isinstance(route.get(k, False), bool) for k in ("ws_publish", "ws_subscribe")):
                raise ValueError("Route permissions must be booleans")
            name, key = route["id"], route["key"]
            if not IDENTIFIER.fullmatch(name) or name in self.routes:
                raise ValueError("Invalid or duplicate route id")
            normalized = key.replace("{run_id}", "run")
            if not normalized or normalized.startswith("/") or any(c in normalized for c in "*?#{}") or "//" in normalized:
                raise ValueError("Route key must be literal or contain only {run_id}")
            if key in keys:
                raise ValueError("Duplicate route key")
            keys.add(key)
            message_factory.GetMessageClass(self.pool.FindMessageTypeByName(route["type"]))
            adapter = route.get("adapter")
            if adapter and adapter not in ADAPTERS:
                raise ValueError("Unknown adapter")
            if adapter and (not value.get("onboarding") or ADAPTER_TYPES[adapter] != (name, route["type"].removeprefix("cev.onboarding.v1."))):
                raise ValueError("Adapter route/type is incompatible")
            self.routes[name] = dict(route)

    def message(self, route, data, binary=False):
        cls = message_factory.GetMessageClass(self.pool.FindMessageTypeByName(self.routes[route]["type"]))
        msg = cls()
        if binary:
            if len(data) > MAX_PAYLOAD:
                raise ValueError("Protobuf payload too large")
            msg.ParseFromString(data)
        else:
            json_format.ParseDict(data, msg, descriptor_pool=self.pool)
        return msg

    @staticmethod
    def value(msg, internal=False):
        return json_format.MessageToDict(msg, preserving_proto_field_name=internal,
            always_print_fields_with_no_presence=True)


class ProtobufRouter:
    def __init__(self, endpoint="tcp/127.0.0.1:7447", sim=None, session=None):
        import zenoh
        self.zenoh = zenoh
        self.session = session or zenoh.open(zenoh.Config.from_json5(json.dumps({
            "mode": "client", "connect": {"endpoints": [endpoint], "exit_on_failure": True},
            "scouting": {"multicast": {"enabled": False}, "gossip": {"enabled": False}}
        })))
        self.sim = sim
        self.profiles = {}
        self.run = None
        self.retired = set()
        self.lock = threading.RLock()
        self.clients = {}
        self.subscribers = {}
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._tick, daemon=True)
        self.worker.start()

    def register(self, name, value):
        if not IDENTIFIER.fullmatch(name):
            raise ValueError("Invalid profile id")
        profile = Profile(value)
        with self.lock:
            if self.run and self.run["profile_id"] == name:
                raise ValueError("Cannot replace an in-use profile")
            self.profiles[name] = profile
        return self.inspect(name)

    def inspect(self, name):
        with self.lock:
            p = self.profiles[name]
            return {"id": name, "fingerprint": p.fingerprint, "routes": list(p.routes.values()),
                    "protocol": PROTOCOL, "active_run": self.status()}

    def prepare(self, value):
        with self.lock:
            run_id = value["run_id"]
            if not IDENTIFIER.fullmatch(run_id) or run_id in self.retired or self.run:
                raise ValueError("Use a new run id and deactivate the previous run first")
            p = self.profiles[value["profile_id"]]
            if value["fingerprint"] != p.fingerprint:
                raise ValueError("Schema fingerprint mismatch")
            keys = [r["key"].replace("{run_id}", run_id) for r in p.routes.values()]
            if len(set(keys)) != len(keys):
                raise ValueError("Resolved routes have duplicate keys")
            if p.value.get("onboarding"):
                for topic in ("tf_topic", "lidar_topic", "command_topic"):
                    if not value[topic].startswith(f"/onboarding/{run_id}/"):
                        raise ValueError("Simulator topics must be scoped to the new run")
            from protobuf_sim import SimAdapter
            adapter = SimAdapter(self, value) if p.value.get("onboarding") else None
            self.run = {**value, "active": False, "fault": None, "adapter": adapter,
                        "profile": p, "last_info": 0.0, "last_monitor": None, "completed_reason": None}
            try:
                for name, route in p.routes.items():
                    if route.get("adapter") in ("command-v1", "path-overlay-v1"):
                        self._subscribe(name)
                if adapter:
                    adapter.prepare()
            except Exception:
                self.deactivate(run_id)
                raise
            return self.status()

    def activate(self, run_id, identity):
        with self.lock:
            run = self._run(run_id)
            if run["active"] or run["fault"]:
                raise ValueError("Run already activated or failed")
            allowed = {"browser_id", "sim_run_id", "resolved_hash"}
            if not isinstance(identity, dict) or set(identity)-allowed or any(not isinstance(v,str) or not v or len(v)>256 for v in identity.values()):
                raise ValueError("Activation accepts only browser_id, sim_run_id, and resolved_hash")
            if run["profile"].value.get("onboarding") and not all(identity.get(k) for k in ("browser_id", "sim_run_id", "resolved_hash")):
                raise ValueError("Browser, simulation run, and resolved hash are required")
            run.update(identity)
            run["active"] = True
            if run["adapter"]:
                run["adapter"].stop()
            return self.status()

    def status(self):
        if not self.run:
            return None
        return {k: self.run.get(k) for k in ("run_id", "active", "fault", "browser_id", "sim_run_id", "resolved_hash", "completed_reason")}

    def monitor(self):
        with self.lock:
            if self.run:
                self.run["last_monitor"] = time.monotonic()
            return self.status()

    def _run(self, run_id=None):
        if not self.run or (run_id is not None and self.run["run_id"] != run_id):
            raise ValueError("No matching prepared run")
        return self.run

    def deactivate(self, run_id):
        with self.lock:
            run = self._run(run_id)
            if run["adapter"]:
                run["adapter"].stop()
            self.retired.add(run_id)
            self.run = None
            subs, self.subscribers = self.subscribers, {}
            self.clients.clear()
        for subscriber in subs.values():
            subscriber.undeclare()
        return {"stopped": True}

    def _key(self, route):
        run = self._run()
        return run["profile"].routes[route]["key"].replace("{run_id}", run["run_id"])

    def publish(self, route, data):
        run = self._run()
        msg = run["profile"].message(route, data)
        payload = msg.SerializeToString()
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("Protobuf payload too large")
        self.session.put(self._key(route), payload, encoding=self.zenoh.Encoding("application/protobuf"),
                         congestion_control=self.zenoh.CongestionControl.DROP)

    def _subscribe(self, route):
        if route not in self.subscribers:
            run_id = self._run()["run_id"]
            self.subscribers[route] = self.session.declare_subscriber(self._key(route),
                lambda sample: self._receive(run_id, route, bytes(sample.payload)))

    def _receive(self, run_id, route, payload):
        with self.lock:
            if not self.run or self.run["run_id"] != run_id:
                return
            try:
                run = self.run
                msg = run["profile"].message(route, payload, binary=True)
                if run["adapter"]:
                    run["adapter"].incoming(route, Profile.value(msg, True))
                value = Profile.value(msg)
                for client in self.clients.values():
                    if route in client["routes"]:
                        client["pending"][route] = {"protocol": PROTOCOL, "op": "sample", "route": route,
                            "run_id": run_id, "fingerprint": run["profile"].fingerprint, "value": value}
            except Exception as exc:
                self.fail(f"Invalid {route}: {exc}")

    def fail(self, detail):
        if self.run:
            self.run["fault"] = str(detail)
            if self.run["adapter"]:
                self.run["adapter"].stop()

    def handle_text(self, client, text):
        with self.lock:
            body = json.loads(text)
            if body.get("protocol") != PROTOCOL:
                raise ValueError("Unsupported text protocol")
            run = self._run(body.get("run_id"))
            profile = run["profile"]
            if body.get("fingerprint") != profile.fingerprint:
                raise ValueError("Schema fingerprint mismatch")
            op = body["op"]
            if op == "hello":
                self.clients[client] = {"run_id": run["run_id"], "routes": set(), "pending": OrderedDict()}
            else:
                state = self.clients.get(client)
                if not state or state["run_id"] != run["run_id"]:
                    raise ValueError("Protobuf hello required")
                route_id = body["route"]
                route = profile.routes[route_id]
                if op == "publish":
                    if not route.get("ws_publish") or not run["active"] or run["fault"]:
                        raise ValueError("Publication not permitted")
                    self.publish(route_id, body["value"])
                elif op == "subscribe":
                    if not route.get("ws_subscribe"):
                        raise ValueError("Subscription not permitted")
                    self._subscribe(route_id)
                    state["routes"].add(route_id)
                elif op == "unsubscribe":
                    state["routes"].discard(route_id)
                    state["pending"].pop(route_id, None)
                else:
                    raise ValueError("Unknown Protobuf operation")
            return {"protocol": PROTOCOL, "op": "ack", "request_id": body.get("request_id"), "action": op}

    def drain(self, client):
        with self.lock:
            state = self.clients.get(client)
            if not state:
                return []
            values = list(state["pending"].values())
            state["pending"].clear()
            return values

    def disconnect(self, client):
        with self.lock:
            self.clients.pop(client, None)

    def enqueue_ws_publish(self, topic, type_name, value):
        with self.lock:
            if self.run and self.run["adapter"]:
                try:
                    self.run["adapter"].legacy(topic, type_name, value)
                except Exception as exc:
                    self.fail(exc)

    def _tick(self):
        while not self.stop_event.wait(0.02):
            with self.lock:
                if self.run and self.run["active"] and not self.run["fault"]:
                    try:
                        if self.run["adapter"]:
                            adapter = self.run["adapter"]
                            adapter.tick()
                            if adapter.last_sensor is not None:
                                if self.run["last_monitor"] is None:
                                    self.run["last_monitor"] = time.monotonic()
                                elif time.monotonic()-self.run["last_monitor"] > .75:
                                    raise ValueError("Launcher lost; start a fresh run")
                        if "run_info" in self.run["profile"].routes and time.monotonic() - self.run["last_info"] >= 0.5:
                            self.publish("run_info", self.run["run_info"])
                            self.run["last_info"] = time.monotonic()
                    except Exception as exc:
                        self.fail(exc)

    def stop(self):
        self.stop_event.set()
        if self.run:
            self.deactivate(self.run["run_id"])
        self.worker.join(timeout=1)
        self.session.close()
