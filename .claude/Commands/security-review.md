---
description: Security audit of Charon codebase — run after completing each phase
---

Perform a security review of the Charon project at C:\Users\lurka\Projects\Charon.

**Check for these categories of issues:**

### 1. Secrets & Credential Exposure
- Hardcoded API keys, passwords, tokens, or secrets anywhere in source
- Secrets logged, printed, or included in error messages
- Profile SMTP credentials leaking into output or AI prompts

### 2. Injection Vulnerabilities
- SQL injection: any string interpolation in SQLite queries (must use parameterized queries)
- Command injection: any user input reaching `subprocess`, `os.system`, `eval`, or `exec`
- YAML injection: unsafe YAML loading (must use `yaml.safe_load`, never `yaml.load`)
- Path traversal: user-controlled file paths without validation

### 3. Input Validation
- URL scheme validation (only HTTP/HTTPS allowed)
- URL/domain validation before fetching
- Company name sanitization
- Paste input size limits
- HTTP response size limits and timeouts

### 4. API Security
- Claude API key sourced from environment variable, not hardcoded
- AI response validation (structured output parsed defensively)
- Rate limiting and backoff on API calls
- No sensitive user data sent unnecessarily in prompts

### 5. Dependency Security
- Check pyproject.toml for pinned versions
- Flag any known-vulnerable dependencies
- Verify no unnecessary dependencies

### 6. Error Handling
- No bare `except:` clauses
- Stack traces not leaked to user output
- Graceful failure on network errors, API errors, invalid input

**Output format:**
For each finding, report:
- **Severity**: CRITICAL / HIGH / MEDIUM / LOW
- **Location**: file:line
- **Issue**: What's wrong
- **Fix**: How to fix it

If no issues found, confirm the phase passes security review.
