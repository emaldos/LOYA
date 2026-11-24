# LOYA Target Values AI Template

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
