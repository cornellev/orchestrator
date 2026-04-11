import importlib.util
from pathlib import Path

_root_serialization = Path(__file__).resolve().parents[1] / "serialization.py"
_spec = importlib.util.spec_from_file_location("orchestrator_root_serialization", _root_serialization)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load serializer from {_root_serialization}")

_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name in dir(_module):
    if _name.startswith("_"):
        continue
    globals()[_name] = getattr(_module, _name)
