# MCP coverage

This file maps what a LOYA NG user can do to the MCP tools that an AI client can use. It covers the in-app LOYA AI, the External Agents (Claude Agent, OpenAI Codex), your own Claude Code / Codex CLI connected under Settings > AI > Agents > Connections, and any MCP client you connect with the bearer token.

How the tools are gated:
- Every tool calls `ai_service.authorize` after the lock check.
- Every tool is registered under exactly one AI Roles permission. A tool that is not registered is denied. `tests/test_ai_roles.py` and `tests/test_mcp_app_tools.py` enforce both rules.

Where the tools live:
- The core tools are in `Cores/Bridge/mcp_server.py`.
- The app-wide tools, resources and prompts are in `Cores/Bridge/mcp_app_tools.py`.
- The chain Run History and chain/run bundle tools are in `Cores/Bridge/mcp_chain_history_tools.py`. `tests/test_mcp_chain_history.py` checks their gating.
- The chain diagram building tools (node catalog, validate, node-by-node edits, node output) are in `Cores/Bridge/mcp_flow_tools.py`. `tests/test_flow_nodes.py` checks their gating, redaction and size caps.

Status key:
- **yes**: covered by a tool.
- **new**: added in S31.
- **operator only**: deliberately not exposed. The reason is given in the table.
- **planned (other team)**: another team is adding it.

Coverage, before and after S31:
- MCP tools: **55 → 112**. That is 49 app-wide tools from S31 plus the Chains team's chain-diagram tools.
- After S31: 6 Chain History tools (run history list, run, log, export, import, delete). Total: **118**.
- Chains studio: 7 chain diagram tools (`chain_node_types`, `chain_validate`, `chain_node_add`, `chain_node_set`, `chain_node_delete`, `chain_connect`, `chain_run_output`). Total: **125**. They use the existing Chain Diagrams > Read and Edit permissions; no new AI Roles entity was added.
- MCP resources: 0 → 3.
- MCP prompts: 0 → 2.
- User-facing features covered: about 45% → about 85%. The rest are operator-only by design.

## Feature matrix

| Area | Feature | Tool(s) | Permission key | Status |
|---|---|---|---|---|
| App | What the user is looking at (page, selected note/report, live target) | `app_context`, resource `loya://app/context` | `app_read` | new |
| App | Global search | `app_search` | `app_read` | new |
| App | Dashboard numbers | `dashboard_stats` | `app_read` | new |
| App | Dashboard layout, theme, window, onboarding | - | - | operator only (UI preferences) |
| Notes | List / read / create / append / replace / delete | `notes_list`, `notes_get`, `notes_create`, `notes_append`, `notes_update`, `notes_delete` | `notes_read/add/edit/delete` | yes |
| Notes | Command blocks inside notes | `notes_command_block_html` | `notes_read` | yes |
| Notes | Full-text search | `notes_search` | `notes_read` | new |
| Notes | Groups: list, create, rename, move a note | `notes_groups`, `notes_group_create`, `notes_group_rename`, `notes_move` | `notes_read/add/edit` | new |
| Notes | Pin | `notes_pin` | `notes_edit` | new |
| Notes | History: versions, diff, restore | `notes_versions`, `notes_version_diff`, `notes_restore_version` | `notes_read/edit` | new |
| Notes | Attachments (add) | `notes_attachment_add` (base64 content only) | `notes_edit` | new |
| Notes | Attachments from a file path | - | - | operator only (no disk paths; an agent sends the bytes) |
| Notes | Note templates, drafts, sidebar preferences, editor preferences | - | - | operator only (editor state) |
| Notes | Delete group | - | - | operator only (bulk structure change) |
| Commands | List / create / update / delete | `commands_*` | `commands_*` | yes |
| Commands | Command history, past runs of a command | `commands_history`, `command_runs` | `commands_read` | new |
| Quick Run | List (placeholders filled), run with approval | `quickrun_list`, `quickrun_run` | `quickrun_read`, `quickrun_run` (shell) | yes |
| Quick Run | Favourites: read, pin/unpin | `quickrun_favorites`, `quickrun_favorite_set` | `quickrun_read`, `quickrun_edit` (Ask) | new |
| Targets | List / add / update / delete (secret values masked) | `targets_list`, `targets_add`, `targets_update`, `targets_remove` | `targets_*` | yes (masking new) |
| Targets | Live target: read, set | `targets_live_get`, `targets_set_live`, resource `loya://targets/live` | `targets_read/edit` | new |
| Targets | Engagement status | `targets_set_engagement_status` | `targets_edit` | new |
| Targets | Unmasked secret values | `targets_secret_values` | `targets_secrets` (Deny, sensitive) | new |
| Targets | Profiles: list, create, switch | `target_profiles_list`, `target_profile_create`, `target_profile_switch` | `targets_read/add/edit` | new |
| Targets | Profile rename/delete, CIDR expand, key pattern, bulk rename | - | - | operator only (bulk or destructive) |
| Parameters | List / add / rename / remove | `parameter_*` | `parameter_*` | yes |
| Reports | List / get / create / update / delete | `reports_*` | `reports_*` | yes |
| Reports | Sections add / update | `report_section_add`, `report_section_update` | `reports_add/edit` | yes |
| Reports | Findings add / update / delete / list | `findings_*` | `reports_*` | yes |
| Reports | Finding from CVE | `findings_add_from_cve` | `reports_add` | new |
| Reports | Findings Library: search, add, use | `findings_library_search`, `findings_library_add`, `findings_add_from_library` | `reports_read/add` | new (search existed) |
| Reports | Templates: list, get | `report_templates_list`, `report_template_get` | `reports_read` | new (list existed) |
| Reports | Versions: list, snapshot, restore | `report_versions_list`, `report_version_create`, `report_version_restore` | `reports_read/edit` | new |
| Reports | Schedule / milestones, deadlines | `report_schedule_get`, `report_schedule_set`, `reports_deadlines` | `reports_read/edit` | new |
| Reports | Stats | `reports_stats` | `reports_read` | new |
| Reports | Scope from Targets: available targets, link, unlink, refresh, reorder, targets per finding | `report_targets_available`, `report_targets_list`, `report_target_link`, `report_target_unlink`, `report_target_update`, `report_targets_reorder`, `finding_targets_set` | `reports_read/add/edit` | new (values allowed as secrets are masked) |
| Reports | Copy a secret value into a report scope link, scope undo/restore | - | - | operator only (moves credentials into a report; UI-only undo) |
| Reports | Outline | resource `loya://reports/{report_id}/outline` | `reports_read` | new |
| Reports | Export as text (markdown/html/json/csv/sarif) | `report_export` | `reports_read` | yes |
| Reports | Export to files (PDF/DOCX/XLSX), import, branding/themes | - | - | operator only (writes files to disk / file dialogs) |
| Reports | AI report generation inside Reporting | - | - | operator only (has its own AI flow) |
| Evidence | List / get (redacted) | `evidence_list`, `evidence_get` | `reports_read` | yes |
| Evidence | Add text / image | `report_evidence_add_text`, `report_evidence_add_image` | `reports_add` | new |
| Evidence | Recordings, delete | - | - | operator only |
| CVE | Lookup | `cve_lookup` | `cve_read` | yes (CVE team) |
| CVE | Search the local index, news feed / watchlist | `cve_search`, `cve_feed` | `cve_read` | new |
| CVE | API key, index update, mark read | - | - | operator only (settings / network) |
| Action Chains | List, run with approval, status | `chains_list`, `chains_run`, `chains_status` | `chains_read`, `chains_run` (shell) | yes |
| Chain diagrams | get / templates / create / update / dry run / run / stop | `chain_get`, `chain_templates`, `chain_create`, `chain_update`, `chain_dry_run`, `chain_run`, `chain_run_status`, `chain_run_stop` | `chain_diagrams_*` | yes (Chains team) |
| Chain diagrams | Node catalog: the 39 node types by category (paged, filterable), and one type's parameter schema (ports, defaults, fields, options, presets) | `chain_node_types` | `chain_diagrams_read` | new (Chains studio) |
| Chain diagrams | Validate a graph without saving it | `chain_validate` | `chain_diagrams_read` | new (Chains studio) |
| Chain diagrams | Node-by-node edits: add a node (or a preset) and connect it, change a node's config / title / position, delete a node, connect or disconnect two nodes | `chain_node_add`, `chain_node_set`, `chain_node_delete`, `chain_connect` | `chain_diagrams_edit` | new (Chains studio; the diagram must validate, the chain becomes AI-made and unreviewed) |
| Chain diagrams | Whole-diagram edits with node positions and sticky notes (`comment` nodes) | `chain_create`, `chain_update` | `chain_diagrams_add/edit` | yes |
| Chain diagrams | Run results: the `results` list (Return result nodes), one node's stdout / stderr / parsed value / variables / HTTP status | `chain_run_status` (now with `results`), `chain_run_output` | `chain_diagrams_read` | new (Chains studio; secrets redacted, values under secret-looking keys hidden, size-capped) |
| Chain diagrams | Run gate | `chain_run` | `chain_diagrams_run` (shell) | changed (Chains studio): a chain with an HTTP request node or a file node always asks the operator, like a script node; the prompt lists those actions |
| Chain diagrams | Hot bar pins, canvas layout preferences | - | - | operator only (UI preferences) |
| Chain history | Run History: list with filters (chain, status, trigger, dates, text), one run with its node timeline, the structured log | `chain_runs_list`, `chain_run_get`, `chain_run_log` | `chain_history_read` | new (after S31; output redacted) |
| Chain history | Export chains and runs as a versioned bundle | `chain_history_export` | `chain_history_read` | new (after S31; redacted, 4 MB cap) |
| Chain history | Import a bundle (chains come in AI-made and unreviewed; name and run id collisions: rename, skip or replace) | `chain_history_import` | `chain_history_add` (Ask) | new (after S31) |
| Chain history | Delete one run, several, a chain's whole history or everything | `chain_runs_delete` | `chain_history_delete` (Deny) | new (after S31; a chain's history or everything always asks) |
| Chain history | Export or import bundles as files, clear from the UI | - | - | operator only (file dialogs) |
| Terminal | Sessions, read output, queue a command, status, interrupt | `terminal_*` | `terminal_read/run/kill` (shell, Deny) | yes |
| Terminal | Job history and job output (redacted) | `terminal_jobs_list`, `terminal_job_get` | `terminal_read` (Deny) | new |
| Tags | List / rename / merge / delete | `tags_*` | `tags_*` | yes |
| Recycle Bin | List / restore / purge | `recycle_*` | `recycle_*` | yes |
| Settings | Read the non-secret settings | `settings_get` | `settings_read` | yes |
| Settings | Any write | - | - | operator only (no safe write is scoped yet) |
| Security | Audit log (redacted) | `audit_log_read` | `audit_read` (Deny, sensitive) | new |
| Security | PIN, lock, encryption, AI Roles, keys, backups, updates, import/export | - | - | operator only (security boundary) |

## MCP prompts
- `loya-note-from-output`: turns pasted tool output into a structured LOYA note.
- `loya-finding-from-cve`: adds a finding from a CVE and tailors it to the engagement.

## Every tool with its permission and default

The Default column is the out-of-the-box level for a fresh install. A preset or the operator can change it.

| Tool | Permission key | Entity > Action | Default | Added in S31 |
|---|---|---|---|---|
| `chains_list` | `chains_read` | Action Chains > Read | Allow |  |
| `chains_run` | `chains_run` | Action Chains > Run | Deny |  |
| `chains_status` | `chains_read` | Action Chains > Read | Allow |  |
| `app_context` | `app_read` | App > Read | Allow | yes |
| `app_search` | `app_read` | App > Read | Allow | yes |
| `dashboard_stats` | `app_read` | App > Read | Allow | yes |
| `audit_log_read` | `audit_read` | Audit Log > Read | Deny | yes |
| `cve_feed` | `cve_read` | CVE Intel > Read | Allow | yes |
| `cve_lookup` | `cve_read` | CVE Intel > Read | Allow |  |
| `cve_search` | `cve_read` | CVE Intel > Read | Allow | yes |
| `chain_connect` | `chain_diagrams_edit` | Chain Diagrams > Edit | Allow |  |
| `chain_create` | `chain_diagrams_add` | Chain Diagrams > Add | Allow |  |
| `chain_dry_run` | `chain_diagrams_read` | Chain Diagrams > Read | Allow |  |
| `chain_get` | `chain_diagrams_read` | Chain Diagrams > Read | Allow |  |
| `chain_node_add` | `chain_diagrams_edit` | Chain Diagrams > Edit | Allow |  |
| `chain_node_delete` | `chain_diagrams_edit` | Chain Diagrams > Edit | Allow |  |
| `chain_node_set` | `chain_diagrams_edit` | Chain Diagrams > Edit | Allow |  |
| `chain_node_types` | `chain_diagrams_read` | Chain Diagrams > Read | Allow |  |
| `chain_run` | `chain_diagrams_run` | Chain Diagrams > Run | Deny |  |
| `chain_run_output` | `chain_diagrams_read` | Chain Diagrams > Read | Allow |  |
| `chain_run_status` | `chain_diagrams_read` | Chain Diagrams > Read | Allow |  |
| `chain_run_stop` | `chain_diagrams_run` | Chain Diagrams > Run | Deny |  |
| `chain_templates` | `chain_diagrams_read` | Chain Diagrams > Read | Allow |  |
| `chain_update` | `chain_diagrams_edit` | Chain Diagrams > Edit | Allow |  |
| `chain_validate` | `chain_diagrams_read` | Chain Diagrams > Read | Allow |  |
| `chain_history_export` | `chain_history_read` | Chain History > Read | Allow |  |
| `chain_history_import` | `chain_history_add` | Chain History > Add | Ask |  |
| `chain_run_get` | `chain_history_read` | Chain History > Read | Allow |  |
| `chain_run_log` | `chain_history_read` | Chain History > Read | Allow |  |
| `chain_runs_delete` | `chain_history_delete` | Chain History > Delete | Deny |  |
| `chain_runs_list` | `chain_history_read` | Chain History > Read | Allow |  |
| `command_runs` | `commands_read` | Commands > Read | Allow | yes |
| `commands_create` | `commands_add` | Commands > Add | Allow |  |
| `commands_delete` | `commands_delete` | Commands > Delete | Deny |  |
| `commands_history` | `commands_read` | Commands > Read | Allow | yes |
| `commands_list` | `commands_read` | Commands > Read | Allow |  |
| `commands_update` | `commands_edit` | Commands > Edit | Allow |  |
| `notes_append` | `notes_edit` | Notes > Edit | Allow |  |
| `notes_attachment_add` | `notes_edit` | Notes > Edit | Allow | yes |
| `notes_command_block_html` | `notes_read` | Notes > Read | Allow |  |
| `notes_create` | `notes_add` | Notes > Add | Allow |  |
| `notes_delete` | `notes_delete` | Notes > Delete | Deny |  |
| `notes_get` | `notes_read` | Notes > Read | Allow |  |
| `notes_group_create` | `notes_add` | Notes > Add | Allow | yes |
| `notes_group_rename` | `notes_edit` | Notes > Edit | Allow | yes |
| `notes_groups` | `notes_read` | Notes > Read | Allow | yes |
| `notes_list` | `notes_read` | Notes > Read | Allow |  |
| `notes_move` | `notes_edit` | Notes > Edit | Allow | yes |
| `notes_pin` | `notes_edit` | Notes > Edit | Allow | yes |
| `notes_restore_version` | `notes_edit` | Notes > Edit | Allow | yes |
| `notes_search` | `notes_read` | Notes > Read | Allow | yes |
| `notes_update` | `notes_edit` | Notes > Edit | Allow |  |
| `notes_version_diff` | `notes_read` | Notes > Read | Allow | yes |
| `notes_versions` | `notes_read` | Notes > Read | Allow | yes |
| `parameter_add` | `parameter_add` | Parameter > Add | Allow |  |
| `parameter_list` | `parameter_read` | Parameter > Read | Allow |  |
| `parameter_remove` | `parameter_delete` | Parameter > Delete | Deny |  |
| `parameter_update` | `parameter_edit` | Parameter > Edit | Allow |  |
| `quickrun_favorite_set` | `quickrun_edit` | Quick Run > Edit | Ask | yes |
| `quickrun_favorites` | `quickrun_read` | Quick Run > Read | Allow | yes |
| `quickrun_list` | `quickrun_read` | Quick Run > Read | Allow |  |
| `quickrun_run` | `quickrun_run` | Quick Run > Run | Deny |  |
| `recycle_list` | `recycle_read` | Recycle Bin > Read | Allow |  |
| `recycle_purge` | `recycle_delete` | Recycle Bin > Delete | Deny |  |
| `recycle_restore` | `recycle_restore` | Recycle Bin > Restore | Allow |  |
| `evidence_get` | `reports_read` | Reports > Read | Allow |  |
| `evidence_list` | `reports_read` | Reports > Read | Allow |  |
| `finding_targets_set` | `reports_edit` | Reports > Edit | Allow | yes |
| `findings_add` | `reports_add` | Reports > Add | Allow |  |
| `findings_add_from_cve` | `reports_add` | Reports > Add | Allow | yes |
| `findings_add_from_library` | `reports_add` | Reports > Add | Allow | yes |
| `findings_delete` | `reports_delete` | Reports > Delete | Deny |  |
| `findings_library_add` | `reports_add` | Reports > Add | Allow | yes |
| `findings_library_search` | `reports_read` | Reports > Read | Allow |  |
| `findings_list` | `reports_read` | Reports > Read | Allow |  |
| `findings_update` | `reports_edit` | Reports > Edit | Allow |  |
| `report_evidence_add_image` | `reports_add` | Reports > Add | Allow | yes |
| `report_evidence_add_text` | `reports_add` | Reports > Add | Allow | yes |
| `report_export` | `reports_read` | Reports > Read | Allow |  |
| `report_schedule_get` | `reports_read` | Reports > Read | Allow | yes |
| `report_schedule_set` | `reports_edit` | Reports > Edit | Allow | yes |
| `report_section_add` | `reports_add` | Reports > Add | Allow |  |
| `report_section_update` | `reports_edit` | Reports > Edit | Allow |  |
| `report_target_link` | `reports_add` | Reports > Add | Allow | yes |
| `report_target_unlink` | `reports_edit` | Reports > Edit | Allow | yes |
| `report_target_update` | `reports_edit` | Reports > Edit | Allow | yes |
| `report_targets_available` | `reports_read` | Reports > Read | Allow | yes |
| `report_targets_list` | `reports_read` | Reports > Read | Allow | yes |
| `report_targets_reorder` | `reports_edit` | Reports > Edit | Allow | yes |
| `report_template_get` | `reports_read` | Reports > Read | Allow | yes |
| `report_templates_list` | `reports_read` | Reports > Read | Allow |  |
| `report_version_create` | `reports_edit` | Reports > Edit | Allow | yes |
| `report_version_restore` | `reports_edit` | Reports > Edit | Allow | yes |
| `report_versions_list` | `reports_read` | Reports > Read | Allow | yes |
| `reports_create` | `reports_add` | Reports > Add | Allow |  |
| `reports_deadlines` | `reports_read` | Reports > Read | Allow | yes |
| `reports_delete` | `reports_delete` | Reports > Delete | Deny |  |
| `reports_get` | `reports_read` | Reports > Read | Allow |  |
| `reports_list` | `reports_read` | Reports > Read | Allow |  |
| `reports_stats` | `reports_read` | Reports > Read | Allow | yes |
| `reports_update` | `reports_edit` | Reports > Edit | Allow |  |
| `settings_get` | `settings_read` | Settings > Read | Allow |  |
| `tags_delete` | `tags_delete` | Tags > Delete | Deny |  |
| `tags_list` | `tags_read` | Tags > Read | Allow |  |
| `tags_merge` | `tags_edit` | Tags > Edit | Allow |  |
| `tags_rename` | `tags_edit` | Tags > Edit | Allow |  |
| `target_profile_create` | `targets_add` | Targets > Add | Allow | yes |
| `target_profile_switch` | `targets_edit` | Targets > Edit | Allow | yes |
| `target_profiles_list` | `targets_read` | Targets > Read | Allow | yes |
| `targets_add` | `targets_add` | Targets > Add | Allow |  |
| `targets_list` | `targets_read` | Targets > Read | Allow |  |
| `targets_live_get` | `targets_read` | Targets > Read | Allow | yes |
| `targets_remove` | `targets_delete` | Targets > Delete | Deny |  |
| `targets_secret_values` | `targets_secrets` | Targets > Secrets | Deny | yes |
| `targets_set_engagement_status` | `targets_edit` | Targets > Edit | Allow | yes |
| `targets_set_live` | `targets_edit` | Targets > Edit | Allow | yes |
| `targets_update` | `targets_edit` | Targets > Edit | Allow |  |
| `ai_prompt_template` | `templates_read` | Templates > Read | Allow |  |
| `terminal_job_get` | `terminal_read` | Terminal > Read | Deny | yes |
| `terminal_jobs_list` | `terminal_read` | Terminal > Read | Deny | yes |
| `terminal_kill` | `terminal_kill` | Terminal > Kill | Deny |  |
| `terminal_list_sessions` | `terminal_read` | Terminal > Read | Deny |  |
| `terminal_read` | `terminal_read` | Terminal > Read | Deny |  |
| `terminal_run` | `terminal_run` | Terminal > Run | Deny |  |
| `terminal_run_status` | `terminal_read` | Terminal > Read | Deny |  |
