#!/bin/sh
# Evaluate a JS expression in the live LOYA NG main window (sync result). usage: js.sh 'expr'
# LOYA_WIN="LOYA NG Mini" targets another window by its exact title.
D="${LOYA_AUDIT_DIR:-${TMPDIR:-/tmp}/loya-audit}"
rm -f "$D/result.json"
if [ -n "$LOYA_WIN" ]; then printf '//win:%s\n%s' "$LOYA_WIN" "$1" > "$D/cmd.js.tmp"; else printf '%s' "$1" > "$D/cmd.js.tmp"; fi
mv "$D/cmd.js.tmp" "$D/cmd.js"
i=0; while [ ! -f "$D/result.json" ] && [ $i -lt 100 ]; do sleep 0.1; i=$((i+1)); done
cat "$D/result.json" 2>/dev/null || echo '{"ok":false,"error":"timeout - is launch.sh running?"}'
