import base64
import hashlib
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import zenoh
    from google.protobuf import descriptor_pb2
except ImportError:
    raise unittest.SkipTest("Install requirements-protobuf.txt for Protobuf routing tests")
from protobuf_routing import Profile, ProtobufRouter
from protobuf_sim import cloud


def profile(package="example"):
    f = descriptor_pb2.FileDescriptorProto(name=package+".proto", package=package, syntax="proto3")
    for name, fields in [("Note", [("title", 9), ("nonce", 4)]), ("Reply", [("accepted", 8)])]:
        m=f.message_type.add(name=name)
        for i, (field, typ) in enumerate(fields, 1):
            m.field.add(name=field, number=i, type=typ, label=1)
    raw=descriptor_pb2.FileDescriptorSet(file=[f]).SerializeToString()
    return {"descriptor":base64.b64encode(raw).decode(),"fingerprint":hashlib.sha256(raw).hexdigest(),
            "routes":[{"id":n.lower(),"key":"test/{run_id}/"+n.lower(),"type":package+"."+n,"ws_publish":True,"ws_subscribe":True} for n in ("Note","Reply")]}


class Subscription:
    def undeclare(self): pass
class Payload:
    def __init__(self, value): self.payload=value
class Session:
    def __init__(self): self.callbacks={}; self.published=[]
    def declare_subscriber(self,key,cb): self.callbacks[key]=cb; return Subscription()
    def put(self,key,data,**kwargs):
        self.published.append((key,data))
        if key in self.callbacks: self.callbacks[key](Payload(data))
    def close(self): pass


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.session=Session()
        self.router=ProtobufRouter(session=self.session)
        self.value=profile()
        self.router.register("test",self.value)
        self.router.prepare({"profile_id":"test","run_id":"one","fingerprint":self.value["fingerprint"]})
        self.router.activate("one",{})
    def tearDown(self): self.router.stop()
    def request(self, op, **args):
        return self.router.handle_text("client", json.dumps({"protocol":"orch.protobuf.v1","op":op,"run_id":"one","fingerprint":self.value["fingerprint"],**args}))
    def test_generic_round_trip_exact_integer_and_second_schema(self):
        self.request("hello")
        self.request("subscribe",route="note")
        self.request("publish",route="note",value={"title":"hello","nonce":"18446744073709551615"})
        self.assertEqual(self.router.drain("client")[0]["value"]["nonce"],"18446744073709551615")
        self.router.register("other",profile("unrelated"))
        self.assertIn("other",self.router.profiles)
        self.router.deactivate("one")
        self.value=profile("unrelated")
        self.router.prepare({"profile_id":"other","run_id":"one-new","fingerprint":self.value["fingerprint"]})
        self.router.activate("one-new",{})
        body={"protocol":"orch.protobuf.v1","run_id":"one-new","fingerprint":self.value["fingerprint"]}
        for op, fields in [("hello",{}),("subscribe",{"route":"note"}),("publish",{"route":"note","value":{"nonce":"42"}})]:
            self.router.handle_text("second",json.dumps({**body,"op":op,**fields}))
        self.assertEqual(self.router.drain("second")[0]["value"]["nonce"],"42")
    def test_invalid_profile_does_not_replace_or_change_live_profile(self):
        original=self.router.profiles["test"]
        bad=profile();bad["fingerprint"]="wrong"
        with self.assertRaises(ValueError):self.router.register("test",bad)
        self.assertIs(original,self.router.profiles["test"])
        with self.assertRaises(ValueError):self.router.register("test",profile())
        bad=profile();bad["routes"][0]["key"]="test/**"
        with self.assertRaises(ValueError):Profile(bad)
    def test_rejection_directions_fields_and_run_identity(self):
        self.request("hello")
        with self.assertRaises(Exception):self.request("publish",route="note",value={"unknown":3})
        with self.assertRaises(Exception):self.request("publish",route="absent",value={})
        self.router.deactivate("one")
        with self.assertRaises(ValueError):self.router.prepare({"profile_id":"test","run_id":"one","fingerprint":self.value["fingerprint"]})
    def test_pending_samples_are_latest_only(self):
        self.request("hello");self.request("subscribe",route="note")
        for i in range(100):self.request("publish",route="note",value={"nonce":str(i)})
        self.assertEqual(len(self.router.clients["client"]["pending"]),1)
        self.assertEqual(self.router.drain("client")[0]["value"]["nonce"],"99")

class PointCloudTests(unittest.TestCase):
    def test_endian_bounds_duplicates_and_nonfinite(self):
        import struct
        for big in (True,False):
            value={"header":{"frame_id":"front_lidar_frame","stamp":{"sec":0,"nanosec":5}},"width":1,"height":1,"point_step":12,"row_step":16,
            "fields":[{"name":n,"offset":i*4,"datatype":7,"count":1} for i,n in enumerate("xyz")],"is_bigendian":big,"data":struct.pack(">fff" if big else "<fff",1,-2,0)+bytes(4)}
            self.assertEqual(cloud(value),(5,[{"x":1.,"y":-2.}]))
            value["data"]=value["data"][:-1]
            with self.assertRaises(ValueError):cloud(value)
        value["data"]=struct.pack("<fff",float("nan"),0,0)+bytes(4)
        self.assertEqual(cloud(value),(5,[]))
        value["fields"].append(value["fields"][0])
        with self.assertRaises(ValueError):cloud(value)

if __name__ == '__main__':unittest.main()
