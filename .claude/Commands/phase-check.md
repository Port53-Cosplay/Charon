---
description: Verify a build phase is complete and ready for the next one
---

Check the completion status of Charon build phase: $ARGUMENTS

Read REQUIREMENTS.md and verify every deliverable for the specified phase is implemented, functional, and tested.

**For each deliverable, report:**
- DONE: Implemented and working
- PARTIAL: Started but incomplete — describe what's missing
- MISSING: Not yet implemented

**Then check:**
1. All new code has corresponding tests in `tests/`
2. No regressions in previously completed phases (run `pytest` if tests exist)
3. CLI commands from this phase work end-to-end
4. Security review passes (check CLAUDE.md security requirements)

**Verdict:** READY to proceed to next phase, or BLOCKED with list of remaining items.
