#!/usr/bin/env bash
set -euo pipefail

startup_log=$(mktemp)
# Keep environment-provided API credentials out of the smoke-test process.
env -u OPENDEV_API_KEY -u GRADIO_SERVER_NAME GRADIO_ANALYTICS_ENABLED=False \
    GRADIO_SERVER_PORT=17860 PYTHONUNBUFFERED=1 python app.py > "$startup_log" 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true; wait "$server" 2>/dev/null || true; rm -f "$startup_log"' EXIT
for attempt in $(seq 1 30); do
    if curl -fsS --noproxy '*' http://127.0.0.1:17860/config >/dev/null 2>&1; then
        grep -F 'http://0.0.0.0:17860' "$startup_log" >/dev/null
        echo 'Gradio startup verified on 0.0.0.0:17860.'
        exit 0
    fi
    kill -0 "$server" 2>/dev/null || break
    sleep 1
done
cat "$startup_log" >&2
echo 'Gradio startup check failed.' >&2
exit 1
