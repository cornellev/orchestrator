import hashlib,io,sys,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from install_zenoh import verified_binary
class RouterInstallTest(unittest.TestCase):
    def test_checksum_and_safe_extraction(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,"w") as z:z.writestr("../../zenohd",b"router")
        raw=data.getvalue()
        self.assertEqual(verified_binary(raw,hashlib.sha256(raw).hexdigest(),"zenohd"),b"router")
        with self.assertRaises(ValueError):verified_binary(raw,"bad","zenohd")
