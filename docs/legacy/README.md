# Retired v1 daemon documentation

Everything in this directory describes the retired v1 FastAPI/JSONL/Chroma daemon. It is preserved for historical and migration research only; none of these commands or architecture claims describe the v2 `cortex-mem` package.

The frozen `service/` source is not part of the v2 runtime. Reconstructing it requires its historical stack—FastAPI, Uvicorn, ChromaDB, aiosqlite, PyYAML, and the legacy embedding integrations—which is intentionally excluded from the v2 dependency set. Do not run that service against a v2 store.
