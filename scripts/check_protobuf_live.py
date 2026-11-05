"""Exercise JS -> orchestrator -> real Zenoh -> Rust and the reverse response.
Start zenohd and orchestrator first. Set CEV_ORCHESTRATOR_API, CEV_ORCHESTRATOR_WS,
and CEV_ZENOH_ENDPOINT for nondefault ports.
"""
import argparse,json,os,subprocess,sys,urllib.request,uuid,queue,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"test"))
from test_protobuf_routing import profile

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--onboarding",type=Path,required=True);p.add_argument("--sim",type=Path,required=True)
    args=p.parse_args()
    base=os.environ.get("CEV_ORCHESTRATOR_API","http://localhost:8090")
    ws=os.environ.get("CEV_ORCHESTRATOR_WS","ws://localhost:8080")
    def request(method,path,body=None):
        data=json.dumps(body).encode() if body is not None else None
        headers={"Content-Type":"application/json"}
        if os.environ.get("CEV_API_TOKEN"):headers["Authorization"]="Bearer "+os.environ["CEV_API_TOKEN"]
        with urllib.request.urlopen(urllib.request.Request(base+path,data=data,method=method,headers=headers),timeout=10) as response:return json.load(response)
    value=profile();run=str(uuid.uuid4())
    request("PUT","/api/protobuf/profiles/interop",value)
    request("POST","/api/protobuf/runs",{"run_id":run,"profile_id":"interop","fingerprint":value["fingerprint"]})
    rust=None
    try:
        request("POST",f"/api/protobuf/runs/{run}/activate",{})
        rust=subprocess.Popen([str(args.onboarding/"target/debug/examples/transport_probe"),run],stdout=subprocess.PIPE,text=True)
        ready=queue.Queue(maxsize=1)
        threading.Thread(target=lambda:ready.put(rust.stdout.readline()),daemon=True).start()
        assert ready.get(timeout=10).strip()=="READY"
        subprocess.run(["node", "--experimental-default-type=module",str(args.sim/"scripts/protobuf-probe.mjs"),ws,run,value["fingerprint"]],check=True,timeout=15)
        assert rust.wait(timeout=10)==0
        print("PASS: JavaScript / Python / binary Protobuf / Zenoh / Rust interoperability")
    finally:
        if rust and rust.poll() is None:rust.kill();rust.wait()
        request("DELETE",f"/api/protobuf/runs/{run}")
if __name__=="__main__":main()
