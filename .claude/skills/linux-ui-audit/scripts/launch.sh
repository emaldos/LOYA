#!/bin/sh
# Start the real app under the audit harness (console -> log, JS RPC). Run in the background.
# Uses the same WebKit env the launcher sets on Linux (RunNote._linux_app_env).
H="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$H/../../../.." && pwd)"
D="${LOYA_AUDIT_DIR:-${TMPDIR:-/tmp}/loya-audit}"; mkdir -p "$D/shots"
cd "$ROOT" && env WEBKIT_DMABUF_RENDERER_FORCE_SHM="${WEBKIT_DMABUF_RENDERER_FORCE_SHM:-1}" WEBKIT_SKIA_ENABLE_CPU_RENDERING="${WEBKIT_SKIA_ENABLE_CPU_RENDERING:-1}" .venv_linux/bin/python3 "$H/harness.py" > "$D/app.log" 2>&1
