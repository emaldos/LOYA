# LOYA NG developer docs
Start here if you cloned this repository to work on it. The root [README](../README.md) explains what the app does and how to install it; these pages explain how it is built, how to change it safely and how it got here.
## Reading order
1. [ARCHITECTURE.md](ARCHITECTURE.md): the launcher, the app process, the windows, the JS to Python bridge, the UI shell and the services layer.
2. [SUBSYSTEMS.md](SUBSYSTEMS.md): storage and encryption, security, the updater, the terminal, chains, AI and MCP, reporting and CVE Intel.
3. [DEVELOPMENT.md](DEVELOPMENT.md): setup, tests, the pre commit gate, house rules, recipes for common changes, and releasing.
4. [HISTORY.md](HISTORY.md): versions, how the work was organized, decisions and lessons, ideas not built yet and known gaps.
## Reference
| File | What it holds |
|---|---|
| [SECURITY-AUDIT.md](SECURITY-AUDIT.md) | The security audit: every finding, its fix and its regression test |
| [MCP-COVERAGE.md](MCP-COVERAGE.md) | Every MCP tool, resource and prompt with its permission key and default |
| [`Cores/storage_migration_plan.md`](../Cores/storage_migration_plan.md) | The as built storage and encryption design |
| [`.claude/skills/`](../.claude/skills) | Checklists for the quality gate, the Linux UI audit and porting from the original LOYA Note |
| `screenshots/` | Images used by the root README |
## Five things to know before your first change
- Run the app with `python RunNote.py` and the tests through discovery: `python -m unittest discover -s tests -p "test_*.py"` and `node tests/js/run.js`.
- Every change has to work on Windows and Linux.
- `Data/`, `Logs/` and `Backups/` hold real user data and are never committed. Stage files by name.
- New bridge methods are refused while the app is locked unless you add them to `_LOCK_OPEN`.
- The original [LOYA Note](https://github.com/emaldos/LOYA-Note) is the behaviour spec when you are unsure how a feature should act.
