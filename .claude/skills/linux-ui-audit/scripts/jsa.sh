#!/bin/sh
# Await an async JS body in the live window (pywebview's evaluate_js does not await promises).
# usage: jsa.sh 'const r=await bridgeCall("notes.list");return r.length'
H="$(dirname "$0")"
"$H/js.sh" "window.__r=undefined;(async()=>{$1})().then(v=>window.__r={ok:1,v},e=>window.__r={ok:0,e:String(e&&e.message||e)});1" >/dev/null
i=0; while [ $i -lt 60 ]; do o=$("$H/js.sh" 'window.__r===undefined?"__pending":JSON.stringify(window.__r)'); case "$o" in *__pending*) sleep 0.25; i=$((i+1));; *) echo "$o"; exit 0;; esac; done; echo timeout
