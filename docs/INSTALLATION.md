# Installation

## Requirements

- Python 3.10+
- ~200 MB disk (dependencies include ChromaDB, ONNX Runtime for embeddings)

## Quick Install (PyPI)

```bash
pip install cortex-mem
```

## From Source (Development)

```bash
git clone https://github.com/dhawalc/cortex-mem.git
cd cortex-mem
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Docker

```bash
docker pull ghcr.io/dhawalc/cortex-mem:latest
docker run -d -p 9100:9100 --name cortex-mem ghcr.io/dhawalc/cortex-mem:latest
```

Or build locally:

```bash
git clone https://github.com/dhawalc/cortex-mem.git
cd cortex-mem
docker build -t cortex-mem .
docker run -d -p 9100:9100 cortex-mem
```

## One-Line Install Script

```bash
curl -sSL https://raw.githubusercontent.com/dhawalc/cortex-mem/main/install.sh | bash
```

This script will:
1. Install the `cortex-mem` pip package
2. Start the service as a background daemon
3. Auto-detect OpenClaw and migrate existing workspace data

## Systemd Service (Linux)

For persistent operation across reboots:

```bash
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/cortex-mem.service << 'EOF'
[Unit]
Description=cortex-mem AOMS
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m cortex_mem.cli start --port 9100
Restart=always
WorkingDirectory=/home/YOUR_USER/cortex-mem/cortex-mem

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now cortex-mem
```

Replace `/home/YOUR_USER/cortex-mem/cortex-mem` with the actual path to the repo (or omit `WorkingDirectory` if installed via pip globally).

Check status:

```bash
systemctl --user status cortex-mem
journalctl --user -u cortex-mem -f
```

## Verify Installation

```bash
cortex-mem --version
# cortex-mem, version 1.0.0

cortex-mem start --daemon
cortex-mem status
# cortex-mem: ok
# Uptime: 2s
# Entries: 0
```
