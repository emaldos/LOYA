#!/usr/bin/env bash
# LOYA NG pre-commit gate. Exit 0 only if everything passes.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"; cd "$ROOT" || exit 2
fail=0; say(){ printf '%s\n' "$*"; }
PY=.venv_linux/bin/python3; [ -x "$PY" ] || PY=python3
say "== Python tests ($PY)"
out=$("$PY" -m unittest discover -s tests -p "test_*.py" 2>&1); rc=$?
say "$(printf '%s\n' "$out" | grep -E '^(Ran|OK|FAILED)' | tail -2)"; [ $rc -eq 0 ] || { fail=1; printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):' | head -20; }
say "== Node tests"
for t in $(ls tests/js/*.js 2>/dev/null); do
  head -c 400 "$t" | grep -q "require(" || continue
  o=$(node "$t" 2>&1); r=$?; say "$t: $(printf '%s\n' "$o" | tail -1)"; [ $r -eq 0 ] || fail=1
done
say "== Line endings"
churn=(); crlf_edit=()
while IFS= read -r f; do
  [ -f "$f" ] || continue
  git cat-file -e "HEAD:$f" 2>/dev/null || continue
  head_crlf=$(git show "HEAD:$f" | grep -c $'\r$'); tree_crlf=$(grep -c $'\r$' "$f")
  if git diff --quiet --ignore-cr-at-eol -- "$f"; then churn+=("$f")
  elif [ "$head_crlf" -eq 0 ] && [ "$tree_crlf" -gt 0 ]; then crlf_edit+=("$f"); fi
done < <(git diff --name-only)
say "content-free CRLF churn (do NOT commit): ${#churn[@]}"; for f in "${churn[@]}"; do say "  $f"; done
say "real edits saved with CRLF over LF HEAD (normalise first): ${#crlf_edit[@]}"; for f in "${crlf_edit[@]}"; do say "  $f"; done; [ ${#crlf_edit[@]} -eq 0 ] || fail=1
say "== Version (must stay unchanged)"
for f in Cores/Update/CurrentVersion.info Cores/Update/CurentVersion.info; do
  [ -f "$f" ] || continue
  if git diff --quiet --ignore-cr-at-eol -- "$f"; then say "  $f unchanged ($(tr -d '\r\n' < "$f"))"; else say "  CHANGED: $f"; git diff --ignore-cr-at-eol -- "$f" | grep '^[-+][^-+]'; fail=1; fi
done
# Only real code assignments in .py files count (README/docs text that mentions the name is not a bump).
git diff --ignore-cr-at-eol -U0 -- '*.py' | grep -v '^+++' | grep -E '^\+.*DEFAULT_APP_VERSION[[:space:]]*(:[^=]*)?=([^=]|$)' && { say "  DEFAULT_APP_VERSION changed"; fail=1; }
say "== Sensitive paths in index"
git diff --cached --name-only | grep -E '^(Data|Logs|Backups)/|\.env$|settings\.local\.json$' && { say "  refuse: sensitive file staged"; fail=1; } || say "  none staged"
say "== Secrets in staged changes"
# Real-looking keys/tokens in added lines. Fake test keys must carry TEST/EXAMPLE/fake in the value or live under tests/.
# The test/example/fake exemption applies to the matched key itself, not to the whole line (a line that merely says "latest" or
# "# test" must not hide a real key), and tests/ is scanned too - only key-shaped values that say so are exempt there.
SECRET_RX='sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|glpat-[A-Za-z0-9_-]{20,}|(AKIA|ASIA)[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|xox[abprs]-[0-9A-Za-z-]{20,}|AIza[0-9A-Za-z_-]{35}|"private_key": *"-----BEGIN'
hits=$(git diff --cached -U0 -- . | grep -E '^\+' | grep -oE "$SECRET_RX" | grep -vE '^-----BEGIN [A-Z ]*PRIVATE KEY$' | grep -viE 'test|example|fake|dummy|redact|x{8,}|0{8,}|abcdefgh')
# A private-key header carries no value to inspect: outside tests/ any staged one is refused.
pk=$(git diff --cached -U0 -- . ':(exclude)tests/' | grep -E '^\+' | grep -E -- '-----BEGIN [A-Z ]*PRIVATE KEY' | grep -viE 'redact')
hits=$(printf '%s\n%s\n' "$hits" "$pk" | sed '/^$/d' | sort -u)
if [ -n "$hits" ]; then say "  refuse: possible secret staged"; printf '%s\n' "$hits" | cut -c1-120; fail=1; else say "  none found"; fi
git diff --cached --name-only | grep -E '(^|/)(\.credentials\.json|auth\.json|\.mcp\.json|usage\.json|sessions\.json)$' && { say "  refuse: agent credential/session file staged"; fail=1; }
[ $fail -eq 0 ] && say "GATE: PASS" || say "GATE: FAIL"; exit $fail
