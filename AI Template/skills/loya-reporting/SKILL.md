---
name: loya-reporting
description: Build or extend a penetration-test report in LOYA - sections, findings with CVSS/CWE/CVE, evidence, remediation, versions and schedule - using the CVE and Findings Library tools. Use when asked to write, fill or review a report.
---
<!-- loya-skill-version: 1 -->
# Reports in LOYA

## Find or create the report
- `app_context` shows the open report. Otherwise use `reports_list`.
- New report: `report_templates_list`, then `reports_create(title, template_id, client)`.
- Before large edits, call `report_version_create(report_id, "before AI edit")`. A bad edit can then be undone with `report_version_restore`.

## Findings
Fill each finding with:
- `title`
- `severity`, or better a `cvss_vector` (CVSS:3.1/...): LOYA computes the score and the severity
- `cwe`, and `owasp` where relevant
- `description`, `impact`, `steps` (to reproduce) and `remediation`, written as short HTML paragraphs or lists
- `affected` hosts/URLs and `references` (https URLs)

Ways to start a finding, best first:
1. **From a CVE:** `cve_lookup` or `cve_search` to confirm the id, then `findings_add_from_cve(report_id, cve_id)`. It fills CVSS, CWE, description, remediation and references from LOYA's CVE data. Then use `findings_update` to make `affected`, `impact` and `steps` specific to this engagement.
2. **From the Findings Library:** `findings_library_search`, then `findings_add_from_library`.
3. **From scratch:** `findings_add`.

To reuse a good write-up later, save it with `findings_library_add`.

Rules:
- Do not invent CVEs, versions or CVSS metrics. If the evidence does not show it, say so in the finding.
- Keep the CVE's CVSS vector unless you have evidence that the environment changes it. If it does, explain why in `impact`.
- Status: `open`, `retest`, `fixed` or `accepted`.

## Evidence
- Command output: `report_evidence_add_text(content, title, command)`.
- Screenshots: `report_evidence_add_image(name, data_base64, title)`.
- `evidence_list` / `evidence_get` find what is already captured from the terminal. Reference an evidence item from the finding's steps rather than pasting long output. Secrets are redacted by the evidence store.

## Narrative sections
`reports_get` lists the sections. Fill `executive_summary`, `scope`, `methodology` and `conclusion` with `report_section_update`, based on the findings. Add custom ones with `report_section_add`. Write for the client: plain language in the summary, technical detail in the findings.

## Schedule and delivery
- `report_schedule_get` / `report_schedule_set` handle milestones (kickoff, testing window, draft, final). `reports_deadlines` lists upcoming dates across all reports.
- `report_export(report_id, "markdown")` returns the whole report as text, for a final read-through. Files (PDF/DOCX) are exported by the operator from the Reporting page.
