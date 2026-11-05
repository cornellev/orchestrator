import math,sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from protobuf_sim import SimAdapter,FRESH
class Sim:
    def __init__(self):self.values={}
    def update_topic(self,k,v):self.values[k]=v
    def add_topic(self,*a):pass
class Router:
    def __init__(self):self.sim=Sim();self.run={"active":True,"fault":None}
class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.r=Router()
        self.a=SimAdapter(self.r,{"run_id":"run","mode":"autonomous","command_topic":"/cmd","vehicle":{"wheelbase_m":.2,"length_m":.3,"width_m":.18,"max_speed_mps":.3,"max_steering_rad":.5}})
        self.a.now=100_000_000;self.a.last_scan=self.a.last_sensor=time.monotonic();self.a.states[5]=self.a.now;self.a.scans[9]=self.a.now
        self.source={"run_id":"run","sequence":"9","time_ns":str(self.a.now),"frame_id":"map"}
        self.path={"header":{**self.source,"sequence":"10"},"source":self.source,"availability":"READY","path":{"points":[{"x":1.,"y":0.},{"x":2.,"y":0.}]}}
        self.a.incoming("path",self.path)
        self.command={"header":{**self.source,"sequence":"1"},"source":self.source,"path_sequence":"10","state_sequence":"5","valid_until_ns":str(self.a.now+FRESH),"command":{"speed_mps":.1,"steering_rad":.1}}
    def test_clamps_finite_rejects_nonfinite(self):
        self.command["command"]["speed_mps"]=8
        self.a.incoming("command",self.command)
        self.assertEqual(self.r.sim.values["/cmd"]["speed"],.3)
        self.assertTrue(self.a.saturated)
        self.command["header"]["sequence"]="2";self.command["command"]["speed_mps"]=float("nan")
        with self.assertRaises(ValueError):self.a.incoming("command",self.command)
    def test_fresh_command_cannot_extend_old_path(self):
        self.a.now+=FRESH+1;self.command["header"]["time_ns"]=str(self.a.now)
        self.command["valid_until_ns"]=str(self.a.now+FRESH)
        with self.assertRaises(ValueError):self.a.incoming("command",self.command)
    def test_deadline_must_not_extend_source(self):
        self.command["valid_until_ns"]=str(self.a.now+FRESH+1)
        with self.assertRaises(ValueError):self.a.incoming("command",self.command)
    def test_no_path_invalidates_previous_command(self):
        self.a.incoming("command",self.command)
        self.a.incoming("path",{**self.path,"header":{**self.source,"sequence":"11"},"availability":"NO_PATH"})
        self.assertEqual(self.r.sim.values["/cmd"]["speed"],0)
        self.assertIsNone(self.a.path)
    def test_wrong_epoch_and_old_commands_stop(self):
        self.a.incoming("command",self.command)
        self.a.incoming("command",self.command)
        self.assertEqual(self.r.sim.values["/cmd"]["speed"],0)
        self.command["header"]["run_id"]="previous"
        self.a.incoming("command",self.command)
        self.assertEqual(self.r.sim.values["/cmd"]["speed"],0)
    def test_wall_transport_loss_and_command_loss_stop(self):
        self.a.last_sensor=time.monotonic()-1
        with self.assertRaises(ValueError):self.a.tick()
        self.a.last_sensor=time.monotonic();self.a.incoming("command",self.command)
        self.a.last_command=time.monotonic()-1
        with self.assertRaises(ValueError):self.a.tick()

    def test_late_drive_test_packet_stops_normally(self):
        self.a.context["mode"]="drive-test"
        self.a.now=1_000_000_000
        self.a.states[5]=self.a.now
        self.command["header"]["time_ns"]=str(self.a.now)
        self.command["source"]={**self.command["header"],"sequence":"5"}
        self.a.incoming("command",self.command)
        self.assertEqual(self.r.sim.values["/cmd"]["speed"],0)
    def test_delayed_ready_path_cannot_revive_an_invalidated_path(self):
        self.a.incoming("path",{**self.path,"header":{**self.source,"sequence":"11"},"availability":"NO_PATH"})
        self.a.incoming("path",self.path)
        self.assertIsNone(self.a.path)
