#!/bin/bash
set -e

echo "Installing cortex-mem..."

pip install cortex-mem

cortex-mem start --daemon

sleep 2
cortex-mem status

if [ -d "$HOME/.openclaw" ]; then
    echo ""
    echo "OpenClaw detected. Configuring..."
    cortex-mem migrate "$HOME/.openclaw/workspace"
fi

echo ""
echo "cortex-mem installed and running!"
echo "  Service: http://localhost:9100"
echo "  Docs:    http://localhost:9100/docs"
echo ""
echo "Next steps:"
echo "  cortex-mem search 'your query'"
echo "  cortex-mem status"
