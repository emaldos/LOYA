import json,zipfile,os
def _json_template(obj):return json.dumps(obj,ensure_ascii=False,indent=2)+"\n"
def _ai_template_root():
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..","AI Template"))
_AI_TEMPLATE_FILES={
    "notes":"LOYA_Notes_AI_Template.md",
    "commands":"LOYA_Commands_AI_Template.md",
    "targets":"LOYA_Targets_AI_Template.md",
    "target_values":"LOYA_TargetValues_AI_Template.md",
}
def _read_ai_template_file(kind):
    name=_AI_TEMPLATE_FILES.get(kind)
    if not name:return ""
    path=os.path.join(_ai_template_root(),name)
    try:
        with open(path,"r",encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""
def _command_tags(dbp):
    from Cores import common_db as _common_db
    from Cores.Services import commands_service as _cmds_svc
    seen={};out=[]
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            cur=con.cursor()
            for tbl in ("CommandsNotes","Commands"):
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(tbl,))
                if not cur.fetchone():continue
                cur.execute(f"SELECT tags FROM {tbl} WHERE tags IS NOT NULL AND TRIM(tags)<>''")
                for (raw,) in cur.fetchall():
                    for tag in _cmds_svc._split_tags(raw):
                        k=tag.lower()
                        if k in seen:continue
                        seen[k]=True;out.append(tag)
    except Exception:pass
    return out
def _ai_knowledge_block():
    cats,submap=[],{}
    tags=[]
    keys=[]
    try:
        from Cores.Services import notes_service as _notes_svc
        dbp=_notes_svc._db_path()
        cats,submap=_notes_svc._cmd_meta(dbp)
        note_tags=[t["tag"] for t in _notes_svc.all_tags()]
        cmd_tags=_command_tags(dbp)
        seen={t.lower() for t in note_tags}
        tags=note_tags+[t for t in cmd_tags if t.lower() not in seen]
    except Exception:
        pass
    try:
        from Cores.Services import targets_service as _targets_svc
        keys=_targets_svc.Store().ordered_keys()
    except Exception:
        pass
    if not (cats or tags or keys):return ""
    lines=["Prefer these existing names over inventing new ones. Only create a new category, sub category, tag, or target key if nothing below reasonably fits."]
    if cats:
        cat_lines=[c+(" ("+", ".join(submap.get(c) or [])+")" if submap.get(c) else "") for c in cats]
        lines.append("Existing categories (with sub categories): "+"; ".join(cat_lines)+".")
    if tags:
        lines.append("Existing tags: "+", ".join(tags)+".")
    if keys:
        lines.append("Existing target parameter keys: "+", ".join(keys)+". In example/generated commands, replace literal IP addresses, hostnames, URLs, ports, usernames, and similar values with a matching {key} placeholder from this list (e.g. write \"nmap {IP}\" instead of \"nmap 192.168.1.5\") whenever the value clearly corresponds to one of these keys.")
    return " ".join(lines)
def _inject_knowledge(text,knowledge):
    if not knowledge:return text
    marker="## 2. Exact Import Format"
    block="\n### Your Existing Data\n"+knowledge+"\n"
    idx=text.find(marker)
    if idx==-1:return text.rstrip("\n")+"\n"+block
    return text[:idx]+block+text[idx:]
def human_notes_markdown():
    return """# LOYA Note Import Template

This file is a testing template to show how to format Markdown for LOYA Note.

How to use:
- Command boxes: use <C [Command Note Tittle:..., Category:..., Sub Category:..., Tags:..., Description:...] >
  The command goes between the tags.
- Note references: use -Notename-My Note- to link to a note named "My Note".
- Separator line: type --- on its own line to insert a line in the editor.

## Command Box Example
<C [Command Note Tittle: Ping Host, Category: Recon, Sub Category: ICMP, Tags: ping, Description: basic ping] >
ping {IP}
</C>

## Note Reference Example
See -Notename-Aleaice- for details.

---
"""
def human_notes_json():
    return _json_template({"Notes":[{"note_name":"Example Note","group_name":"Examples","content":"<h1>Example Note</h1><p>Write note content here.</p><p><strong>Bold</strong>, <em>italic</em>, <u>underline</u>.</p><p><C [Command Note Tittle: Example Command, Category: General, Sub Category: Shell, Tags: demo, Description: example command] ></p><pre>echo hello</pre><p></C></p>","created_at":"","updated_at":""}],"CommandsNotes":[{"note_name":"Example Note","category":"General","sub_category":"Shell","command":"echo hello","tags":"demo","description":"Example command","created_at":"","updated_at":""}],"Commands":[]})
def human_commands_markdown():
    return """# Commands Notes

## Example Command
- Category: General
- Sub Category: Shell
- Tags: demo
- Description: Example command

```bash
echo hello
```
"""
def human_commands_json():
    return _json_template({"CommandsNotes":[{"note_name":"Example Note","category":"General","sub_category":"Shell","command":"echo hello","tags":"demo","description":"Example command","created_at":"","updated_at":""}]})
def human_targets_json():
    return _json_template([{"id":"example_target","name":"Example Target","status":"not_used","values":{"URL":"https://example.com","IP":"127.0.0.1"},"created":"","updated":""}])
def human_targets_csv():
    return "id,name,status,created,updated,URL,IP\nexample_target,Example Target,not_used,,,https://example.com,127.0.0.1\n"
def human_target_values_json():
    return _json_template({"URL":{"priority":0},"IP":{"priority":10}})
def human_target_values_csv():
    return "key,priority\nURL,0\nIP,10\n"
def ai_notes_template():
    return """# LOYA Notes AI Template

## 1. Prompt For AI
Rewrite the user's note into LOYA Note structured markdown.
Return only the import content from section 2.
Use one H1 line for the note name.
Use an optional Group line directly after the H1.
Keep commands inside LOYA command blocks exactly.
Available note features: Note Name, Group, normal text, command block, bold, italic, underline, font size, text color, reference color, left or center alignment, bullet list, numbered list, and table.
Markdown can represent bold, italic, lists, tables, headings, and links.
For LOYA command blocks, use this exact wrapper:
<C [Command Note Tittle: ..., Category: ..., Sub Category: ..., Tags: ..., Description: ...] >
command text here
</C>

## 2. Exact Import Format
```markdown
# Example Note
Group: Examples

This is normal note text.

**Bold text**
*Italic text*
<u>Underlined text</u>
<span style="font-size:18px;color:#ffffff;background-color:#333333">Styled text</span>

- Bullet item
- Bullet item

| Name | Value |
| --- | --- |
| URL | https://example.com |

<C [Command Note Tittle: Example Command, Category: General, Sub Category: Shell, Tags: demo, Description: example command] >
echo hello
</C>
```
"""
def ai_commands_template():
    return """# LOYA Commands AI Template

## 1. Prompt For AI
Rewrite the user's command list into LOYA Commands Notes markdown.
Return only the import content from section 2.
Each command must be under a level 2 heading.
Use Category, Sub Category, Tags, and Description metadata when available.
Put the command body inside one fenced code block.
Do not add explanations outside the format.

## 2. Exact Import Format
````markdown
# Commands Notes

## Example Command
- Category: General
- Sub Category: Shell
- Tags: demo
- Description: Example command

```bash
echo hello
```
````
"""
def ai_targets_template():
    return """# LOYA Targets AI Template

## 1. Prompt For AI
Rewrite the user's targets into LOYA Targets JSON.
Return only the JSON array from section 2.
Each target needs name, status, and values.
Status must be not_used or live.
Use values for target elements such as URL, IP, HOST, PORT, USERNAME, or any custom element name.
Keep JSON valid with double quotes.

## 2. Exact Import Format
```json
[
  {
    "id": "example_target",
    "name": "Example Target",
    "status": "not_used",
    "values": {
      "URL": "https://example.com",
      "IP": "127.0.0.1"
    },
    "created": "",
    "updated": ""
  }
]
```
"""
def ai_target_values_template():
    return """# LOYA Target Values AI Template

## 1. Prompt For AI
Rewrite the user's target element names into LOYA Target Values JSON.
Return only the JSON object from section 2.
Each key is an element name.
Priority is a number from 0 to 65535.
Use manual true only when the value should stay manually controlled.
Keep JSON valid with double quotes.

## 2. Exact Import Format
```json
{
  "URL": {
    "priority": 0
  },
  "IP": {
    "priority": 10,
    "manual": true
  }
}
```
"""
_HUMAN_TEMPLATES={
"notes":{"md":human_notes_markdown,"json":human_notes_json},
"commands":{"md":human_commands_markdown,"json":human_commands_json},
"target_values":{"json":human_target_values_json,"csv":human_target_values_csv},
"targets":{"json":human_targets_json,"csv":human_targets_csv},
}
_AI_TEMPLATES={
"notes":ai_notes_template,
"commands":ai_commands_template,
"target_values":ai_target_values_template,
"targets":ai_targets_template,
}
def human_template_text(kind,fmt):
    fns=_HUMAN_TEMPLATES.get(kind)
    if not fns:return ""
    fn=fns.get(fmt)
    return fn() if fn else ""
def ai_template_text(kind):
    text=_read_ai_template_file(kind)
    if not text:
        fn=_AI_TEMPLATES.get(kind)
        text=fn() if fn else ""
    if text and kind in ("notes","commands"):
        text=_inject_knowledge(text,_ai_knowledge_block())
    return text
def write_human_bundle(out_path):
    entries=[
        ("Notes_Template.json",human_notes_json()),
        ("Commands_Template.json",human_commands_json()),
        ("Targets_Template.json",human_targets_json()),
        ("Targets_Template.csv",human_targets_csv()),
        ("TargetValues_Template.json",human_target_values_json()),
        ("TargetValues_Template.csv",human_target_values_csv()),
    ]
    with zipfile.ZipFile(out_path,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name,text in entries:z.writestr(name,(text if text.endswith("\n") else text+"\n").encode("utf-8"))
def write_ai_bundle(out_path):
    entries=[
        ("Notes_AI_Template.md",ai_template_text("notes")),
        ("Commands_AI_Template.md",ai_template_text("commands")),
        ("Targets_AI_Template.md",ai_template_text("targets")),
        ("TargetValues_AI_Template.md",ai_template_text("target_values")),
    ]
    with zipfile.ZipFile(out_path,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name,text in entries:z.writestr(name,(text if text.endswith("\n") else text+"\n").encode("utf-8"))
