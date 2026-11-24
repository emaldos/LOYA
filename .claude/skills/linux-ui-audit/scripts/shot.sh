#!/bin/sh
# Screenshot the app window (pinned above other windows first). usage: shot.sh name  -> $D/shots/name.png
# LOYA_SHOT_TITLE="LOYA NG Mini" shoots another window.
D="${LOYA_AUDIT_DIR:-${TMPDIR:-/tmp}/loya-audit}"; mkdir -p "$D/shots"
W=$(xdotool search --name "^(${LOYA_SHOT_TITLE:-LOYA NG|LOYA Note NG})$" | head -1); [ -z "$W" ] && { echo "app window not found"; exit 1; }
wmctrl -i -r "$W" -b add,above; eval $(xdotool getwindowgeometry --shell "$W")
import -window root -crop ${WIDTH}x${HEIGHT}+${X}+${Y} +repage "$D/shots/$1.png" && echo "$D/shots/$1.png"
