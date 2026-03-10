---
description: Analyze a job posting URL or pasted text through the full Charon lens (for development/testing reference)
---

This is a development reference command. Analyze the following job posting and provide what Charon's output SHOULD look like, so we can validate our implementation matches expectations.

Input: $ARGUMENTS

Perform the analysis as Charon would:

1. **Ghostbust Analysis** — Score 0-100% ghost likelihood with signals:
   - Posting age / staleness indicators
   - Vagueness (missing team, manager, project details)
   - Salary transparency
   - Repeated/recycled posting patterns
   - Language patterns common in ghost postings

2. **Red Flag Analysis** — Three-tier flag report:
   - DEALBREAKERS (red): Check against standard dealbreakers (RTO, shift work, no salary, rigid hours)
   - YELLOW FLAGS: Meeting culture, hustle language, "like a family", unlimited PTO
   - GREEN FLAGS: Async-first, flexible schedule, salary posted, real remote culture
   - Detect obfuscated/euphemistic versions of all flags

3. **Overall Verdict** — Worth applying? Confidence level?

Format output in the Charon aesthetic: structured, color-coded tiers, scores with breakdowns, plain-English summary. This helps us validate that our AI prompts produce the right kind of analysis.
