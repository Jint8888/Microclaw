#!/bin/bash

# Wait until run_tunnel.py exists
echo "Starting tunnel API..."

sleep 1
while [ ! -f /a0/run_tunnel.py ]; do
    echo "Waiting for /a0/run_tunnel.py to be available..."
    sleep 1
done

. "/ins/setup_venv.sh" "$@"
# Ensure all files are copied to /a0
. "/ins/copy_A0.sh" "$@"

# Change to /a0 directory and run with relative path for proper Python imports
cd /a0
exec python run_tunnel.py \
    --dockerized=true \
    --port=80 \
    --tunnel_api_port=55520 \
    --host="0.0.0.0" \
    --code_exec_docker_enabled=false \
    --code_exec_ssh_enabled=true
