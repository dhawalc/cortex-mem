import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ChromaDB import currently breaks under this runtime (pydantic/chromadb mismatch).
# Unit/integration tests in this suite mock retrieval internals anyway, so a minimal
# stub keeps imports deterministic.
chromadb_stub = types.ModuleType("chromadb")
chromadb_stub.ClientAPI = object


class _StubPersistentClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_or_create_collection(self, *args, **kwargs):
        return types.SimpleNamespace(count=lambda: 0, query=lambda **kw: {"ids": [[]], "distances": [[]]})


chromadb_stub.PersistentClient = _StubPersistentClient
sys.modules["chromadb"] = chromadb_stub
