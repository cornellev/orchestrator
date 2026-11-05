"""Four explicit adapters for the existing browser simulator contracts."""
import math
import struct
import time
from collections import OrderedDict

ADAPTER_TYPES = {"pointcloud2-v1": ("lidar", "LidarUpdate"), "tf-state-v1": ("state", "StateUpdate"),
                 "command-v1": ("command", "CommandUpdate"), "path-overlay-v1": ("path", "PathUpdate")}
ADAPTERS = set(ADAPTER_TYPES)
FRESH = 300_000_000


def stamp(value):
    sec, ns = value["sec"], value["nanosec"]
    if not isinstance(sec, int) or not isinstance(ns, int) or sec < 0 or not 0 <= ns < 1_000_000_000:
        raise ValueError("Invalid capture timestamp")
    total = sec * 1_000_000_000 + ns
    if total > 2**64 - 1:
        raise ValueError("Timestamp overflow")
    return total


def cloud(value):
    if value["header"]["frame_id"] != "front_lidar_frame":
        raise ValueError("Unexpected LiDAR frame")
    width, height, step, row = (value[k] for k in ("width", "height", "point_step", "row_step"))
    data = bytes(value["data"])
    if min(width, height, row) < 0 or step <= 0 or width * height > 100_000 or row < width * step or height * row != len(data) or len(data) > 16_000_000:
        raise ValueError("Invalid PointCloud2 dimensions/strides/payload")
    offsets = []
    for axis in ("x", "y", "z"):
        fields = [f for f in value["fields"] if f["name"] == axis]
        if len(fields) != 1:
            raise ValueError("Missing/duplicate coordinate field")
        f = fields[0]
        if f["datatype"] != 7 or f["count"] != 1 or not 0 <= f["offset"] <= step - 4:
            raise ValueError("Coordinates must be FLOAT32 within point_step")
        offsets.append(f["offset"])
    if any(abs(a-b) < 4 for i, a in enumerate(offsets) for b in offsets[i+1:]):
        raise ValueError("Overlapping coordinate fields")
    fmt = ">f" if value["is_bigendian"] else "<f"
    points = []
    for r in range(height):
        for c in range(width):
            xyz = [struct.unpack_from(fmt, data, r*row+c*step+o)[0] for o in offsets]
            if not all(math.isfinite(v) for v in xyz):
                continue
            x, y, z = xyz
            if abs(z) > .01:
                raise ValueError("Expected horizontal planar LiDAR")
            if math.hypot(x, y) > .001:
                points.append({"x": x, "y": y})
    return stamp(value["header"]["stamp"]), points


class SimAdapter:
    def __init__(self, router, context):
        self.router, self.context = router, context
        self.spec = context["vehicle"]
        self.now = 0
        self.last_sensor = None
        self.last_scan = None
        self.last_scan_time = None
        self.previous = None
        self.scans = OrderedDict()
        self.states = OrderedDict()
        self.path = None
        self.path_sequence = 0
        self.sequence = 0
        self.command_sequence = -1
        self.last_command = None
        self.moving = False
        self.saturated = False
        self.counts = {}
        if not all(math.isfinite(self.spec[k]) and self.spec[k] > 0 for k in ("wheelbase_m", "length_m", "width_m", "max_speed_mps", "max_steering_rad")) or self.spec["max_speed_mps"] > .3 or self.spec["max_steering_rad"] >= math.pi/2:
            raise ValueError("Invalid training vehicle limits")

    def prepare(self):
        sim = self.router.sim
        if not sim:
            raise ValueError("Browser transport missing")
        sim.add_topic(self.context["command_topic"], "sensor_fusion_msgs/StampedAckermannDrive")
        sim.add_topic("/planning/waypoints", "sensor_fusion_msgs/WaypointList")
        self.stop()
        sim.update_topic("/planning/waypoints", {"points": []})

    def header(self, route, ns, frame):
        self.counts[route] = self.counts.get(route, 0) + 1
        return {"run_id": self.context["run_id"], "sequence": str(self.counts[route]), "time_ns": str(ns), "frame_id": frame}

    def legacy(self, topic, type_name, value):
        if not self.router.run["active"]:
            return
        if topic == self.context["lidar_topic"]:
            if type_name != "sensor_msgs/PointCloud2":
                raise ValueError("Unexpected scan type")
            ns, points = cloud(value)
            if self.last_scan_time is not None and ns <= self.last_scan_time:
                return
            self.last_scan_time = ns
            h = self.header("lidar", ns, "front_lidar_frame")
            self.scans[int(h["sequence"])] = ns
            while len(self.scans) > 32:
                self.scans.popitem(last=False)
            self.last_scan = time.monotonic()
            self.router.publish("lidar", {"header": h, "scan": {"points": points, "sensor_in_vehicle": self.spec["sensor_in_vehicle"]}})
        elif topic == self.context["tf_topic"]:
            if type_name != "tf2_msgs/TFMessage":
                raise ValueError("Unexpected TF type")
            for link in value["transforms"]:
                parent, child = link["header"]["frame_id"], link["child_frame_id"]
                t, q = link["transform"]["translation"], link["transform"]["rotation"]
                values = [*t.values(), *q.values()]
                if not all(math.isfinite(v) for v in values):
                    raise ValueError("Non-finite TF")
                if parent == "map" and child == "odom":
                    if any(abs(v) > 1e-6 for v in (*t.values(), q["x"], q["y"], q["z"], q["w"]-1)):
                        raise ValueError("Expected identity map -> odom")
                elif parent == "odom" and child == "base_link":
                    if abs(sum(v*v for v in q.values())-1) > .01 or abs(q["x"]) > .01 or abs(q["y"]) > .01:
                        raise ValueError("Non-planar quaternion")
                    ns = stamp(link["header"]["stamp"])
                    if self.previous and ns == self.previous[0]:
                        continue
                    if self.previous and ns < self.previous[0]:
                        raise ValueError("Repeated/reset simulation timestamp")
                    yaw = math.atan2(2*(q["w"]*q["z"]+q["x"]*q["y"]), 1-2*(q["y"]**2+q["z"]**2))
                    rear = self.spec["rear_axle_in_base"]
                    x = t["x"] + math.cos(yaw)*rear["x"] - math.sin(yaw)*rear["y"]
                    y = t["y"] + math.sin(yaw)*rear["x"] + math.cos(yaw)*rear["y"]
                    speed = 0.0
                    if self.previous:
                        old_ns, old_x, old_y = self.previous
                        speed = ((x-old_x)*math.cos(yaw)+(y-old_y)*math.sin(yaw))/((ns-old_ns)/1e9)
                    info = self.context.get("run_info", {})
                    goal = info.get("goal")
                    if goal and math.hypot(x-goal["x"], y-goal["y"]) <= info["goal_tolerance_m"]:
                        self.router.run["completed_reason"] = "goal reached"
                        self.stop()
                    elif info.get("timeout_s") and ns >= info["timeout_s"]*1e9:
                        self.router.run["completed_reason"] = "timeout"
                        self.stop()
                    self.previous = (ns, x, y)
                    self.now, self.last_sensor = ns, time.monotonic()
                    h = self.header("state", ns, "map")
                    self.states[int(h["sequence"])] = ns
                    while len(self.states) > 32:
                        self.states.popitem(last=False)
                    self.router.publish("state", {"header": h, "state": {"pose": {"position": {"x": x, "y": y}, "yaw_rad": yaw}, "speed_mps": speed}})

    def valid_header(self, header):
        return header["run_id"] == self.context["run_id"] and header["frame_id"] == "map" and 0 <= self.now-int(header["time_ns"]) <= FRESH

    def incoming(self, route, value):
        if not self.router.run["active"] or self.router.run["fault"]:
            return
        if route == "path":
            h = value.get("header", {})
            source = value.get("source", {})
            if not self.valid_header(h) or not self.valid_header(source) or self.scans.get(int(source["sequence"])) != int(source["time_ns"]):
                self.path = None
                self.stop()
                return
            if int(h["sequence"]) <= self.path_sequence:
                return
            self.path_sequence = int(h["sequence"])
            points = value.get("path", {}).get("points", [])
            if value["availability"] != "READY" or not points:
                self.path = None
                self.stop()
                self.router.sim.update_topic("/planning/waypoints", {"points": []})
                return
            if len(points) > 100_000 or not all(math.isfinite(p[k]) and abs(p[k]) < 1e30 for p in points for k in ("x", "y")):
                raise ValueError("Invalid path coordinates")
            self.path = value
            self.router.sim.update_topic("/planning/waypoints", {"points": [{"x":p["x"], "y":0.0, "z":-p["y"]} for p in points]})
        elif route == "command":
            h = value["header"]
            if not self.valid_header(h) or int(h["sequence"]) <= self.command_sequence:
                self.stop()
                return
            self.command_sequence = int(h["sequence"])
            command = value["command"]
            if self.router.run.get("completed_reason"):
                self.stop()
                return
            speed, steer = command["speed_mps"], command["steering_rad"]
            if not all(math.isfinite(v) for v in (speed, steer)):
                raise ValueError("Non-finite command")
            if speed == 0 and steer == 0:
                self.stop()
                return
            source = value["source"]
            if not self.valid_header(source) or self.last_scan is None or time.monotonic()-self.last_scan > .3 or self.last_sensor is None or time.monotonic()-self.last_sensor > .3:
                raise ValueError("Expired command source")
            state_ns = self.states.get(int(value["state_sequence"]))
            if state_ns is None or not 0 <= self.now-state_ns <= FRESH:
                raise ValueError("Missing command state")
            if self.context["mode"] == "drive-test":
                if self.now >= 1_000_000_000:
                    self.stop()
                    return
                if source["sequence"] != str(value["state_sequence"]) or int(source["time_ns"]) != state_ns or speed > .1 or abs(steer) > .1:
                    raise ValueError("Drive test bounds exceeded")
            else:
                if not self.path or int(value["path_sequence"]) != int(self.path["header"]["sequence"]) or source != self.path["source"]:
                    raise ValueError("No matching valid path")
            deadline = int(value["valid_until_ns"])
            if not self.now < deadline <= int(source["time_ns"])+FRESH:
                raise ValueError("Command deadline extends source lifetime")
            limited = max(0, min(speed, self.spec["max_speed_mps"]))
            steering = max(-self.spec["max_steering_rad"], min(steer, self.spec["max_steering_rad"]))
            self.saturated = limited != speed or steering != steer
            if self.context["mode"] == "drive-test":
                deadline = min(deadline, 1_000_000_000)
            self.send(limited, steering, deadline)
            self.last_command, self.moving = time.monotonic(), limited > 0

    def send(self, speed, steer, deadline):
        if self.now > 2**53 or self.sequence >= 2**32-1:
            raise ValueError("Simulator command representation exhausted")
        self.sequence += 1
        self.router.sim.update_topic(self.context["command_topic"], {
            "header": {"stamp": {"sec":self.now//1_000_000_000,"nanosec":self.now%1_000_000_000},"frame_id":"base_link"},
            "sequence":self.sequence, "mode":"velocity" if speed else "stop", "deadline_ns":float(deadline),
            "steering_angle":steer,"steering_angle_velocity":0.,"speed":speed,"acceleration":0.,"jerk":0.})

    def stop(self):
        self.send(0., 0., self.now+FRESH)
        self.moving = False

    def tick(self):
        now = time.monotonic()
        if self.last_sensor is not None and now-self.last_sensor > .3:
            raise ValueError("Simulator transport lost; start a fresh run")
        if self.last_scan is not None and now-self.last_scan > .3:
            raise ValueError("LiDAR transport lost; start a fresh run")
        if self.moving and (now-self.last_command > .3 or (self.path and not self.valid_header(self.path["source"]))):
            raise ValueError("Command/path expired; start a fresh run")
