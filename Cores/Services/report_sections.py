"""Section kinds added after the first reporting release, and the boilerplate a section starts with when it is added on its own
(the same professional text the built-in templates use, see report_templates.py)."""
from Cores.Services import report_templates as _tpl
_p=_tpl._p;_ul=_tpl._ul;_table=_tpl._table
EXTRA_KINDS=("risk_matrix","attack_narrative","project_timeline")
EXTRA_TITLES={"risk_matrix":"Risk Matrix","attack_narrative":"Attack Narrative","project_timeline":"Project Timeline"}
AUTO_KINDS=("findings_summary","findings","remediation_roadmap","risk_matrix","project_timeline","document_control","appendix_commands","appendix_evidence","appendix_timeline")
_RISK_MATRIX=_p("The matrix below places every finding by its likelihood of exploitation and its impact on {{client}}, so that the issues that are both easy to exploit and damaging stand out. Likelihood reflects the skill, access and conditions an attacker needs; impact reflects the effect on the confidentiality, integrity and availability of the affected asset.",
    "Findings in the upper right of the matrix should be remediated first. The severity rating of each finding (see the Findings Summary) takes both dimensions into account.")
def _step(title,guide,*points):
    return f"<h3>{title}</h3>"+_p(guide)+_ul(*points)
_ATTACK_NARRATIVE=_p("This section describes how the findings in this report were combined into a realistic attack against {{client}}, in the order the steps were carried out. It shows what an attacker could achieve in practice, which the individual findings do not show on their own. Technique identifiers refer to MITRE ATT&amp;CK.")+_step(
    "1. Initial access","[Describe how the first foothold was obtained and from where: the exposed service, phishing pretext or supplied account that was used.]",
    "[Entry point and the finding that made it possible, for example F-01.]","[Date and time, source address and the account or host that was compromised.]")+_step(
    "2. Execution","[Describe what was run on the first system and how: the payload, interpreter or legitimate tool that was abused.]",
    "[Commands or tooling used, with a reference to the evidence.]","[Controls that were bypassed, or that blocked earlier attempts.]")+_step(
    "3. Privilege escalation","[Describe how higher privileges were obtained on the host or in the domain, tenant or application.]",
    "[The weakness that was abused: misconfiguration, missing patch, exposed credentials.]","[The level of access reached, for example local administrator or Domain Admin.]")+_step(
    "4. Lateral movement","[Describe how access spread to other systems and which credentials or trust relationships made that possible.]",
    "[Systems reached, in order, and the technique used for each hop.]","[Network segmentation or monitoring that should have stopped the movement.]")+_step(
    "5. Objectives","[Describe what was achieved against the goals agreed for the engagement, and what a real attacker could have done next.]",
    "[Data, systems or business processes that were reached, with the proof that was collected.]","[Business impact in plain language.]")+"<h4>Detection and response</h4>"+_p(
    "[State which of the steps above were prevented, detected or responded to by {{client}}, and how long each detection took.]")+"<h4>Breaking the chain</h4>"+_p(
    "[Name the one or two fixes that would have stopped this attack path earliest, with references to the findings concerned.]")
_PROJECT_TIMELINE=_p("The table below records the milestones of the engagement, from kick-off to the delivery of this report and the planned retest. Dates were agreed with {{client}}; testing took place between {{start_date}} and {{end_date}}.")
def _map():
    web=("a penetration test of the systems in scope","The objective was to identify vulnerabilities that could be used to compromise the systems, their users or the data they process, and to provide prioritised recommendations to address them.")
    return {"executive_summary":_tpl._exec_summary(*web),"scope":_tpl._scope(),"methodology":_tpl.METHODOLOGY.get("web_app",""),"findings_summary":_tpl._FINDINGS_SUMMARY,"findings":_tpl._FINDINGS,
        "remediation_roadmap":_tpl._ROADMAP,"conclusion":_tpl._CONCLUSION,"document_control":_tpl._DOC_CONTROL,"appendix_tools":_tpl._APP_TOOLS,"appendix_commands":_tpl._APP_COMMANDS,"appendix_evidence":_tpl._APP_EVIDENCE,
        "appendix_timeline":_tpl._APP_TIMELINE,"risk_matrix":_RISK_MATRIX,"attack_narrative":_ATTACK_NARRATIVE,"project_timeline":_PROJECT_TIMELINE,"custom":""}
def boilerplate(kind,template_id=""):
    """Starting text for a section of this kind. The methodology follows the report's template when it is a built-in one."""
    kind=str(kind or "").strip().lower()
    tid={"retest_short":"retest"}.get(template_id,template_id)
    if kind=="methodology" and tid in _tpl.METHODOLOGY:return _tpl.METHODOLOGY[tid]
    return _map().get(kind,"")
