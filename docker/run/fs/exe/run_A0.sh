#!/bin/bash

. "/ins/setup_venv.sh" "$@"

# Use source code directly from /git/agent-zero (mounted volume)
cd /git/agent-zero

python /git/agent-zero/prepare.py --dockerized=true

echo "Starting A0..."
exec python /git/agent-zero/run_ui.py \
    --dockerized=true \
    --port=80 \
    --host="0.0.0.0"
