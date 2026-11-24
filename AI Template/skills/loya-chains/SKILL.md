---
name: loya-chains
description: Use and build LOYA Action Chains - multi-step flows of commands, HTTP requests, parsers, loops and branches - list and run existing chains with approval, build and validate chain diagrams for the operator to review, and read run results. Use for repeatable recon or post-exploitation workflows.
---
<!-- loya-skill-version: 3 -->
# Action Chains

An Action Chain is a saved flow of command steps that LOYA runs in the terminal. The operator can also start it from the AI panel by typing `/<caller>`.

## Use existing chains
- `chains_list` shows each chain's id, name, caller and steps.
- `chains_run(chain_id)` queues a run for approval. Then poll `chains_status`.
- Explain what the chain will do before you queue it, especially any step that is destructive or noisy.

## Build a chain diagram
A diagram is a graph of nodes joined by edges. The tool descriptions are the authoritative schema; read them first. If these tools are not in your tool list, the operator's LOYA does not have them yet: describe the flow in words instead.
- catalog: `chain_node_types` (the node types; with `type=<id>` the full config fields of one type), `chain_templates` (ready-made graphs, limits)
- reading: `chain_get`, `chain_validate(graph)` (check without saving), `chain_dry_run`, `chain_run_status`, `chain_run_output`
- creating and editing: `chain_create(name, graph, caller)`, `chain_update(chain_id, graph)` (replaces the whole diagram), and the small edits `chain_node_add`, `chain_node_set`, `chain_node_delete`, `chain_connect`
- running: `chain_run(chain_id, reason)`, `chain_run_stop(run_id)`

### The graph
`{"schema":2,"settings":{...},"nodes":[...],"edges":[...]}`
- **Nodes** are `{"id","type","title","x","y","config"}`. Ids are unique; there is exactly one `start` node. Config keys you leave out get their default.
- **Edges** are `{"id","from","port","to"}`: an edge leaves a named output port of `from` and enters `to`. Several edges may leave one port; they run in order.
- **Sticky notes** are nodes of type `comment` with `config:{"text","color","w","h"}`. They are never run and take no edges. Use them to explain a group of nodes to the operator.

### Node types by category
Call `chain_node_types` for the list and `chain_node_types(type="http")` for one type's fields, options and limits. Ports are in brackets.
- Triggers and inputs: start [out], input_target [out, missing], input_text [out], input_file [out, error]
- Actions: command [success, fail], script [your branches + error], subchain [success, fail], http [success, fail]
- Logic: decision [your branches + else], switch [your cases + default], approval [approved, rejected], foreach [item, done], merge [out], wait [out], end [none]
- Calculations and variables: set [out], math [out, error]
- Data transform: parse [out, nomatch], template, fields, map, split, join [out], filter [out, empty], regex [out, nomatch], json [out, error]
- Data analysis: collection [out] (count, sum, min, max, avg, dedupe, sort, reverse, limit, first, last, group, group_count, flatten, pluck), scan_parse [out, nomatch] (nmap normal, XML and grepable output)
- App: note [out], finding [out], report_create [out] (the three write to the operator's notes and reports), target_update [out, missing], live_target [out, missing], cve_lookup [found, none] (offline index only)
- Outputs and log: output [out] (notify, note, finding draft, evidence), file_write [out, error], result [out] (adds a value to the run's results list), log [out]

A node whose port is named fail or error takes that port when it fails. If nothing is connected there the run stops, unless `settings.on_error` is `"continue"`.

### Values
- `{IPv4}`, `{Host}`, `{URL}`: target placeholders, filled from the operator's live target. Use them for anything about the target; never hard-code an address.
- `${name}`, `${last.stdout}`, `${last.parsed}`, `${nodes.n2.stdout}`, `${item}`, `${index}`, `${target.ipv4}`: flow values. In a command line they are shell-quoted for you. Never use `${raw:...}`.
- A node with a `var` field stores its result in that variable: `${scan.open_ports}`, `${response.status}`, `${response.json.items[0].name}`.
- A config value that is exactly one `${...}` keeps lists and objects as they are, so `"items":"${scan.ports}"` loops over the real list.
- A command node: `config.commands:[{"text":"nmap -Pn -sV -oX - {IPv4}"}]`.
- A decision node: `config.branches:[{"name":"alive","match":"any","conditions":[{"source":"output","op":"contains","value":"ttl=","ci":true}]}]` and `config.else`.
- A math node: `"expr":"(open * 100) / total"` with + - * / // % ** and the functions min max abs round floor ceil sqrt len sum int float.
- To collect results from a loop, end the item path in a merge node (`mode:"any"`) and read its variable after the loop's done port.

### Layout
- Lay the diagram out left to right: add about 300 to `x` for each step, and about 160 to `y` for each parallel branch. Keep the main path on one row (`y` 160), with failure paths below it.
- Give every node a short `title` that says what it does ("Scan top ports", not "command").
- Put a `comment` node above each stage of a long diagram (about 60 above the row, `w` 260, `h` 80).

### Workflow
1. Read `chain_node_types` for the types you plan to use. Start from `chain_templates` when one is close.
2. Build the whole graph and check it with `chain_validate`. Fix every error; read the warnings (an unreachable node, an unconnected fail port).
3. Save it with `chain_create`, or change an existing chain with `chain_update` or the small edit tools.
4. Run `chain_dry_run`. It executes nothing and shows each command and what the HTTP, file and app nodes would do.
5. Ask the operator to open the chain in the diagram editor and review it. Tell them what to check: the commands, any script, any HTTP request, any file path.
6. Only then ask for `chain_run(chain_id, reason)`. Poll `chain_run_status` until the state is done, failed, cancelled or timeout.
7. Read the results: `chain_run_status` has the results list; `chain_run_output(run_id, node_id)` has one node's full output, parsed value and variables; `chain_run_log` has the step-by-step log.

Rules:
- A chain you create or edit is marked AI-made and unreviewed. Its first run always waits for the operator's approval.
- A run with a script, an HTTP request, a file node or a destructive command always asks the operator, whatever the permission level.
- Put an `approval` node before anything intrusive.
- Set `settings.run_timeout`, and keep `settings.on_error:"stop"` unless every failure path is handled.
- File nodes take absolute paths or `~/...`. The app's own data and backup folders are refused.

## Run history
Every run of every chain (real runs and dry runs) is kept in the Run History, newest first, up to 300 runs. Newer LOYA builds add these tools; if they are not in your tool list, ask the operator to look at Chains > Run History instead.
- `chain_runs_list(chain_id, state, trigger, date_from, date_to, query, offset, limit)`: one page of runs with chain name, start time, duration, status (`done`, `failed`, `cancelled`, `timeout`, `running`), node counts, trigger (`manual`, `caller`, `live`, `ai`) and target. Dates are ISO 8601 (for example `2026-11-01T00:00:00Z`).
- `chain_run_get(run_id)`: one run with the per-node timeline: state, branch, visits, duration, exit code, error, resolved commands and an output tail.
- `chain_run_log(run_id, since, limit, level, query)`: the structured log (`info`, `warn`, `error`). Page with `since` (the last `seq` you have). Read the errors first: `level="error"`.
- Output and logs are redacted, but treat them as engagement data: quote only what the operator needs.

When you explain a failure, name the node, its exit code and the error line, then suggest the smallest fix (`chain_update`).

## Export, import and delete
- `chain_history_export(chain_ids | all_chains, run_ids | runs_of_chain | all_runs, include_logs)` returns a versioned bundle: `{"format":"loya-chain-bundle","version":1,"chains":[...],"runs":[...]}`. Bundles over 4 MB are refused: export fewer runs or set `include_logs=false`.
- `chain_history_import(bundle, chains_on_conflict, runs_on_conflict)` asks the operator first.
  - Every diagram is validated.
  - Imported chains are AI-made and unreviewed, so they never run before the operator reviews them.
  - A bundle cannot turn off script sandboxing.
  - Name clashes: `rename` (default), `skip` or `replace`. Run id clashes: `skip` (default), `replace` or `rename`.
  - Imported runs are history only.
- `chain_runs_delete(run_ids | chain_id | all_runs)` needs Chain History > Delete, which is off by default. Deleting a whole chain's history, or everything, always asks the operator. Runs that are still going are never deleted.
- Never delete history to tidy up unless the operator asked for it. Offer an export first.
