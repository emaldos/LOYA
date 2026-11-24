---
name: ng-quality-gate
description: Pre-commit checks for LOYA NG - run both test suites, catch accidental CRLF line-ending churn, confirm the version was not bumped, and stage only intended changes. Use before every commit in this repo, or when asked to verify the tree is clean and ready.
---

# LOYA NG quality gate

Run `scripts/gate.sh` (relative to this skill directory) from anywhere; it prints a pass/fail summary. Then review its output before staging.

What it checks and why:

1. **Python suite**: `.venv_linux/bin/python3 -m unittest discover -s tests -p "test_*.py"` (on Windows: `.venv_windows\Scripts\python`). Import the module under test through the test discovery path - `python -m unittest tests.test_x` fails on `_isolate` imports.
2. **Node suite**: `node tests/js/run.js` plus any extra `tests/js/*.js` runners.
3. **Line-ending churn**: files that are CRLF in the working tree but LF in `HEAD` produce whole-file diffs with no content change (this repo had 15 such files after editing on Windows). Content-free churn must **not** be committed; files with real edits should be normalised to the `HEAD` ending first (`sed -i 's/\r$//' file`). The gate lists both kinds.
4. **Version**: `Cores/Update/CurrentVersion.info`, `CurentVersion.info` and `DEFAULT_APP_VERSION` must be unchanged - NG stays 1.0.0 until its first release.
5. **Secrets**: refuse to stage `Data/`, `Logs/`, `Backups/`, `.env`, `settings.local.json`, API keys.

Staging rule: stage files by name (never `git add -A`), leave the user's untracked notes and content-free CRLF churn out, and summarise what was deliberately left unstaged.
