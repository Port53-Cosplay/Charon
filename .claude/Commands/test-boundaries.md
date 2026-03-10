---
description: Generate security boundary tests for a Charon module
---

Generate pytest security boundary tests for the Charon module: $ARGUMENTS

Focus on adversarial inputs and edge cases:

### URL Handling (fetcher.py)
- `file:///etc/passwd`, `ftp://evil.com`, `javascript:alert(1)`
- URLs with path traversal: `http://example.com/../../../etc/passwd`
- URLs with embedded credentials: `http://user:pass@host/`
- Extremely long URLs, URLs with null bytes
- Non-resolving domains, localhost/private IP ranges (SSRF prevention)

### SQL Operations (db.py)
- Company names with SQL injection: `'; DROP TABLE history;--`
- Unicode edge cases in stored data
- Extremely long strings for all text fields

### Profile Handling (profile.py)
- YAML with anchors/aliases (YAML bomb)
- Unexpected types (list where string expected, nested objects)
- Missing required fields, extra unknown fields
- Extremely large values files

### File Output (dossier.py --save)
- Path traversal in company names: `../../etc/cron.d/evil`
- Company names with shell metacharacters: `; rm -rf /`
- Null bytes in filenames

### Paste Input
- Extremely large paste input (memory exhaustion)
- Binary/non-UTF8 content
- Content with ANSI escape sequences (terminal injection)

Write tests using pytest with clear test names indicating what attack vector is being tested. Use `test_security_` prefix for all security tests.
