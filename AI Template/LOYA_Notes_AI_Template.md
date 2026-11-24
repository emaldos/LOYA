# LOYA Notes AI Template

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
