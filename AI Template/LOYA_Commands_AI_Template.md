# LOYA Commands AI Template

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
