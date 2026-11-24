# LOYA Targets AI Template

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
