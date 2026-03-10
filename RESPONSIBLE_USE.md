# Responsible Use Policy

## Purpose

Charon is a **personal job search evaluation tool**. It exists to help individual job seekers make informed decisions about where to spend their time and energy applying.

## Intended Use

- Evaluating job postings for ghost job indicators before you invest time applying
- Identifying red flags and toxic workplace signals in job descriptions
- Researching companies against your personal values and priorities
- Tracking companies you're interested in and staying informed about new postings

## Not Intended For

- **Bulk scraping** job boards or company career pages at scale
- **Automated mass applications** or application spam
- **Competitive intelligence** gathering for corporate use
- **Defamation** — Charon's analysis is opinion-based and AI-generated, not factual reporting
- **Harassment** of companies, recruiters, or hiring managers based on analysis results
- **Selling or redistributing** company dossiers or analysis reports
- **Circumventing** job board terms of service or rate limits

## Data & Privacy

- Your profile stays local in `~/.charon/profile.yaml` — it is never uploaded or shared
- Job posting text is sent to the Claude API for analysis — review Anthropic's data policies
- Company dossiers are generated from publicly available information only
- History is stored locally in SQLite — you control it and can clear it anytime

## AI Analysis Disclaimer

Charon uses AI (Claude) for analysis. AI output is:

- **Not factual reporting** — it is pattern-based assessment and may be wrong
- **Not legal advice** — do not make legal decisions based on Charon output
- **Not exhaustive** — a clean report does not guarantee a good workplace
- **Potentially biased** — AI models have known biases; treat scores as one input among many

Always do your own research. Talk to actual employees. Trust your instincts.

## Rate Limiting & Respectful Use

- Charon implements rate limiting to be respectful of external services
- Do not modify rate limits to scrape aggressively
- If a company's careers page blocks automated access, respect that boundary

## Reporting Issues

If you believe Charon's analysis has produced harmful, defamatory, or factually dangerous output, please open an issue in the project repository.
