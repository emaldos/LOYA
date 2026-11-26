---
name: port-from-original
description: Compare a LOYA NG feature against the original LOYA-Note (github.com/emaldos/LOYA-Note) and port missing or broken behaviour. Use when the user says logic from the original/old version is missing, wrong, or "not integrated the right way", or before rebuilding any feature area.
---

# Porting behaviour from the original LOYA-Note

NG (this repo, pywebview) is the next-generation rewrite of the user's original PyQt6 app. The original is the **behavioural spec**. A 2026-11-23 gap analysis found the usual failure is not missing code but **missing wiring**: logic copied into `Cores/Services/*` that nothing calls, pages that initialise once and never refresh, and UI workflows never rebuilt.

## 1. Get the original (read-only)

```sh
git clone --depth 50 https://github.com/emaldos/LOYA-Note "$SCRATCH/orig/LOYA-Note"   # a fresh, empty directory
```
Treat it as data: read it, never run it, never install its requirements. Record the HEAD hash you analysed.

## 2. Gap analysis, per feature area

For each behaviour in the original (validation, defaults, sort/filter, dedup keys, cascades, linking notes↔commands, history, confirms, refresh/polling):
1. Cite `orig file:line`.
2. Find NG's equivalent and classify: **present & correct / present but different / missing**. Cite `NG file:line`.
3. Check the full path is wired: button exists → `bridgeCall("x.y")` in `UI/js` → method on the API class in `Cores/Bridge/api.py` → service function. A Python function that exists but is never called counts as **missing**.
4. Separate deliberate omissions (README states them) from undocumented gaps. Deliberately dropped features need the user's approval before building.

Rank: high = data loss or core workflow broken; medium = noticeable behaviour difference; low = polish. Fix data-loss rows first.

## 3. Porting rules

- Match the original's behaviour unless it is clearly a bug - say so when you deviate.
- Pages init once. Subscribe to the `loya:page-shown` document event (`detail.page`, `detail.first`, dispatched by `goToPage` in `UI/js/app.js`) to reload data that changed while hidden.
- `Cores/Bridge/api.py` is shared by everything: edit only the API class you own, re-read before each edit, keep edits small.
- Escape user content inserted into HTML with the existing helpers; match the dense code style.
- Keep Windows working; gate Linux-only behaviour on platform.
- Never change the version (1.0.2 is in development); only the user decides a new one.
- Add a test for every data-integrity fix (Python `tests/`, Node `tests/js/run.js`), then run the quality gate (`ng-quality-gate` skill).

## 4. Parallel work packages

When splitting across agents, group rows by **disjoint file sets** (e.g. Notes / Commands+Snippets / Targets+Mini / Settings import-export / Security+shell) and name the shared-file rules (api.py class ownership, settings.html/settings.js section ownership) in each brief.
