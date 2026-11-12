"""Install the official pinned router, verifying its release checksum first."""
import argparse
import hashlib
import io
import os
import platform
from pathlib import Path
import urllib.request
import zipfile
VERSION = "1.10.2"
ASSETS = {
    ("Darwin","arm64"):("aarch64-apple-darwin","7de8b1467ced19bd157b43ca0e0d5b7e65f7f1dfd2365c6dae854cd8c24d52fe"),
    ("Darwin","x86_64"):("x86_64-apple-darwin","7b00623216177a1d5561b681a5cfd96451926dcddf5e10247a5fb17b8ed1bed5"),
    ("Linux","x86_64"):("x86_64-unknown-linux-gnu","319a29fe9a5883103d2f96acc31643435a9453e95d2350f5f2572c56d85092a5"),
    ("Linux","aarch64"):("aarch64-unknown-linux-gnu","7852171c442d94b5ab000a358ecc8ecbedefbc257a43669265926ce04802d1d3"),
    ("Windows","AMD64"):("x86_64-pc-windows-msvc","9bca926f65cd4802395fa25a859278423064c9125c10a8d29fb86d29364a967b"),
}


def verified_binary(data, checksum, executable):
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError("Zenoh archive checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        matches=[n for n in archive.namelist() if Path(n).name == executable and "/" not in n]
        if len(matches)!=1:
            raise ValueError("Expected exactly one router executable")
        return archive.read(matches[0])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",type=Path,default=Path(os.environ.get("ORCHESTRATOR_BIN_DIR", Path.home()/".local"/"bin")))
    args=parser.parse_args()
    target, checksum=ASSETS[(platform.system(),platform.machine())]
    executable="zenohd.exe" if os.name=="nt" else "zenohd"
    url=f"https://github.com/eclipse-zenoh/zenoh/releases/download/{VERSION}/zenoh-{VERSION}-{target}-standalone.zip"
    with urllib.request.urlopen(url,timeout=60) as response:
        data=response.read(100*1024*1024)
    binary=verified_binary(data,checksum,executable)
    args.directory.mkdir(parents=True,exist_ok=True)
    destination=args.directory/executable
    temp=destination.with_suffix(".installing")
    try:
        temp.write_bytes(binary)
        temp.chmod(0o755)
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    print(f"Installed Zenoh {VERSION}: {destination}")

if __name__=="__main__":main()
