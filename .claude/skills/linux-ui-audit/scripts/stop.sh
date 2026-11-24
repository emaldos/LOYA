#!/bin/sh
# Stop the harnessed app started from THIS checkout only. Other copies (sandboxes, other agents) are left alone:
# a process matches only if its command line contains this checkout's absolute harness path.
H="$(cd "$(dirname "$0")" && pwd)/harness.py"
pids=$(pgrep -af 'harness\.py' | grep -F -- "$H" | awk '$2 ~ /python[0-9.]*$/ {print $1}')
[ -z "$pids" ] && { echo "not running"; exit 0; }
kill $pids && echo "stopped ($pids)"
