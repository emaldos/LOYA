---
name: loya-notes
description: Write and organise structured penetration-test notes in LOYA - layout, runnable command blocks, finding and credential callouts, groups, attachments and history. Use when creating or extending notes.
---
<!-- loya-skill-version: 1 -->
# Pentest notes in LOYA

## Before writing
- `app_context` gives the selected note and the live target. `notes_search` finds an existing note on the same host or topic: extend it rather than starting a duplicate.
- Notes are HTML. `notes_create` makes a note; `notes_append` adds to the end and keeps everything already there. `notes_update` replaces the whole note, so use it only when you have the full current content from `notes_get`.

## A good note
One note per host, service or phase. For example "web01 - 443 HTTPS" in the group "ACME / External".
1. `<h2>Summary</h2>`: two or three lines on what was found and why it matters.
2. `<h2>Enumeration</h2>`: each step as a short paragraph followed by the command that was run.
3. `<h2>Findings</h2>`: one finding callout per issue.
4. `<h2>Next steps</h2>`: a `<ul>` of what to try next.

## Command blocks (runnable from the note)
Never hand-write command block markup. For each command, call `notes_command_block_html` with `command`, `cmd_note_title`, `category`, `sub_category`, `tags` and `description`, then paste the returned HTML into the note. Use `{Placeholder}` names that `parameter_list` already has, such as `{IPv4}`, `{Port}`, `{URL}` or `{Domain}`. Add a new placeholder with `parameter_add` only when none fits.

## Callouts
- Finding:
  `<div class="note-callout note-finding" data-callout="finding" data-sev="high"><h3>Title</h3><p>What, where, impact, evidence.</p></div>`
  `data-sev` is one of critical, high, medium, low or info. Reporting can turn these into report findings.
- Credential: `<div class="note-callout" data-callout="credential"><p>Service: SMB on 10.0.0.5<br>User: svc_backup<br>Password: <span class="note-secret">[ask the operator]</span></p></div>`.
  Never write real secrets yourself. If the operator gives you one, keep it inside `<span class="note-secret">...</span>`, which LOYA masks on screen and redacts before it reaches an AI.
- Other kinds: `data-callout="info"`, `"warning"`, `"evidence"`.

## Tidy up
- Groups: `notes_groups`, `notes_group_create`, `notes_group_rename`, `notes_move`. Pin the main note of an engagement with `notes_pin`.
- Attach a screenshot or file with `notes_attachment_add` (base64 content, up to 5 MB). Paths on disk are never read.
- Every save keeps a version. `notes_versions` and `notes_version_diff` show the history; `notes_restore_version` undoes a bad edit.
