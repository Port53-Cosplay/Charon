"""The demo's fake world: companies, postings, research, applications.

Everything here is invented. Company names are made up; people's links point
at example.com/example.org (reserved domains, so no real person is named or
linked). Times are offsets from the moment the demo is built; the page shifts
them forward again when it's viewed, so the demo never looks abandoned.

The build seeds a throwaway database from this and asks the real dashboard
code for its payloads, so the shapes here are the database's, not the page's.
"""

from __future__ import annotations

from typing import Any

CANDIDATE = {
    "name": "Sample Applicant",
    "headline": "Security Analyst  |  SOC & GRC",
    "contact": "sample.applicant@example.com  ·  (555) 010-0199  ·  Remote, US",
    "summary": "Four years across security operations, incident response and audit prep.",
}


def desc(role: str, company: str, extra: str = "") -> str:
    return (
        f"About the role\n\n{company} is hiring a {role} to join the security team. "
        "You'll work alongside detection engineering, GRC and incident response to keep "
        "the platform and its customers safe.\n\n"
        "What you'll do\n"
        "- Triage alerts and investigate incidents across cloud and endpoint\n"
        "- Tune detections and cut down false positives\n"
        "- Partner with engineering on remediation\n"
        "- Write up findings and keep the runbooks current\n\n"
        "What we're looking for\n"
        "- 2+ years in a security operations or analyst role\n"
        "- Comfort with a SIEM, log analysis and at least one cloud provider\n"
        "- Clear written communication\n\n"
        f"{extra}"
    ).strip()


def flags(*items: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"flag": f, "evidence": e, "interpretation": i} for f, e, i in items]


def detail(
    *,
    ghost: tuple[str, list[tuple[str, str, str]]],
    red: tuple[str, list, list, list],
    align: dict[str, Any],
    resume: dict[str, Any],
    mono: dict[str, Any],
) -> dict[str, Any]:
    """judgement_detail in the analyzers' own shape (see dashboard._digest_judgement)."""
    ghost_summary, ghost_signals = ghost
    red_summary, deal, yellow, green = red
    return {
        "ghostbust": {
            "summary": ghost_summary,
            "signals": [
                {"severity": s, "category": c, "finding": f} for s, c, f in ghost_signals
            ],
        },
        "redflags": {
            "summary": red_summary,
            "dealbreakers_found": flags(*deal),
            "yellow_flags_found": flags(*yellow),
            "green_flags_found": flags(*green),
        },
        "role_alignment": align,
        "resume_match": resume,
        "screening_monoculture": mono,
    }


# ── Ready: judged and worth applying to ─────────────────────────────────
# `state` drives what the build sets up around each card:
#   prepped       the letter template already exists
#   dossier       "fresh" | "stale" | None
#   contacts      a contacts search is on file for the company
#   salary        salary intel already pulled

READY: list[dict[str, Any]] = [
    {
        "key": "aegis-soc",
        "company": "Aegis Cloud Security", "role": "Senior SOC Analyst",
        "location": "Remote (US)", "ats": "greenhouse", "tier": "tier_1", "category": "cloud_security",
        "scores": dict(combined=86.2, alignment=90, ghost=8, redflag=14, resume_match=84, monoculture=22),
        "judged_days_ago": 3,
        "reason": "Strong defensive-security fit, remote, salary posted, concrete stack.",
        "extra": "Salary listed. Remote-first and async-friendly. The security team reports to the CISO.",
        "state": {"prepped": True, "dossier": "fresh", "contacts": True, "salary": True},
        "detail": detail(
            ghost=("No ghost signals: posted salary, a named team, a recent repost.",
                   [("info", "salary", "Salary band present")]),
            red=("One green flag, no dealbreakers.", [], [],
                 [("Mentorship", '"pair with senior analysts"', "Growth-oriented team.")]),
            align={"closest_target": "SOC Analyst", "assessment": "Direct match to the SOC roles on the profile.",
                   "overlap": ["SIEM", "incident response", "log analysis"], "gaps": ["cloud IR at scale"],
                   "stepping_stone": None},
            resume={"match_type": "direct", "summary": "Four years matching the core asks.",
                    "overlap": ["Splunk", "triage", "runbooks"], "gaps": ["Sentinel"],
                    "transferable": ["ticketing workflows"]},
            mono={"summary": "Low screening risk. Plain-language posting at a mid-size company.",
                  "monoculture_score": 22, "ats_risk": "low", "size_risk": "low", "jd_pattern_risk": "low",
                  "signals": [{"category": "screening_phrase", "evidence": "nice to have", "risk": 5}]},
        ),
    },
    {
        "key": "verity-grc",
        "company": "Verity Trust", "role": "GRC Analyst (SOC 2 / ISO 27001)",
        "location": "Remote (US)", "ats": "workday", "tier": "tier_1", "category": "grc",
        "scores": dict(combined=78.5, alignment=82, ghost=15, redflag=24, resume_match=88, monoculture=30),
        "judged_days_ago": 5,
        "reason": "Excellent resume match to the GRC and audit background; clear compliance scope.",
        "extra": "Own evidence collection for SOC 2 Type II and ISO 27001 audits. Cross-functional with engineering.",
        "state": {"prepped": False, "dossier": "fresh", "contacts": True, "salary": True},
        "detail": detail(
            ghost=("Low ghost risk. Specific audit frameworks named.", []),
            red=("One yellow flag, no dealbreakers.", [],
                 [('"Wear many hats"', '"comfortable wearing many hats"', "Possible scope creep at a small company.")],
                 [("Documented process", '"established audit calendar"', "Mature compliance function.")]),
            align={"closest_target": "GRC / Compliance Analyst", "assessment": "Squarely in the GRC wheelhouse.",
                   "overlap": ["SOC 2", "ISO 27001", "evidence collection", "policy"], "gaps": ["FedRAMP"],
                   "stepping_stone": None},
            resume={"match_type": "direct", "summary": "Very close. The audit prep experience maps one to one.",
                    "overlap": ["SOC 2 Type II", "risk register", "vendor reviews"], "gaps": ["HITRUST"],
                    "transferable": ["stakeholder comms"]},
            mono={"summary": "Moderate keyword screening risk.", "monoculture_score": 30,
                  "ats_risk": "medium", "size_risk": "low", "jd_pattern_risk": "medium",
                  "signals": [{"category": "screening_phrase", "evidence": "must have", "risk": 12}]},
        ),
    },
    {
        "key": "meridian-cti",
        "company": "Meridian Defense Labs", "role": "Threat Intelligence Analyst",
        "location": "Remote (US)", "ats": "workday", "tier": "tier_2", "category": "ai_research",
        "scores": dict(combined=80.1, alignment=85, ghost=12, redflag=20, resume_match=76, monoculture=55),
        "judged_days_ago": 2,
        "reason": "Solid fit, but flagged for high screening-monoculture risk. Resume keywords matter here.",
        "extra": "Track threat actors, produce finished intel and brief stakeholders.",
        "state": {"prepped": False, "dossier": None, "contacts": True, "salary": False},
        "detail": detail(
            ghost=("Low ghost risk.", []),
            red=("No dealbreakers, one yellow.", [],
                 [("Rotating on-call", '"participate in on-call rotation"', "After-hours expectation.")], []),
            align={"closest_target": "Threat Intel Analyst", "assessment": "Strong analytical match to the CTI interest.",
                   "overlap": ["OSINT", "reporting", "MITRE ATT&CK"], "gaps": ["malware RE"],
                   "stepping_stone": None},
            resume={"match_type": "direct", "summary": "Good. Analytical and reporting strengths line up.",
                    "overlap": ["intel writing", "briefing"], "gaps": ["threat hunting tooling"],
                    "transferable": ["research methodology"]},
            mono={"summary": "High screening risk: a long, rigid keyword list and exact-match phrasing.",
                  "monoculture_score": 55, "ats_risk": "high", "size_risk": "medium", "jd_pattern_risk": "high",
                  "signals": [{"category": "screening_phrase", "evidence": "must have exactly", "risk": 20},
                              {"category": "screening_phrase", "evidence": "5-7 years required", "risk": 15},
                              {"category": "vendor_mention", "evidence": "three named intel platforms", "risk": 12}]},
        ),
    },
    {
        "key": "northbeacon-appsec",
        "company": "NorthBeacon Labs", "role": "Application Security Engineer",
        "location": "Remote (US)", "ats": "ashby", "tier": "tier_2", "category": "security_product_general",
        "scores": dict(combined=74.8, alignment=70, ghost=10, redflag=18, resume_match=62, monoculture=28),
        "judged_days_ago": 9,
        "reason": "A reach. AppSec depth is a stretch, but the security fundamentals transfer.",
        "extra": "Shift-left AppSec: threat modeling, SAST/DAST, secure code review, developer enablement.",
        "state": {"prepped": False, "dossier": "stale", "contacts": True, "salary": True},
        "detail": detail(
            ghost=("No ghost signals.", []),
            red=("Clean posting.", [], [],
                 [("Learning budget", '"annual training stipend"', "Invests in growth.")]),
            align={"closest_target": "Application Security Engineer", "assessment": "Stretch role; AppSec is a growth direction.",
                   "overlap": ["secure SDLC concepts", "risk assessment"],
                   "gaps": ["hands-on SAST/DAST", "code review at depth"],
                   "stepping_stone": "A strong stepping stone toward AppSec."},
            resume={"match_type": "transferable", "summary": "Fundamentals transfer; tooling depth is the gap.",
                    "overlap": ["OWASP Top 10", "threat modeling basics"],
                    "gaps": ["Burp Suite depth", "language-specific review"],
                    "transferable": ["security awareness training"]},
            mono={"summary": "Low to moderate screening risk.", "monoculture_score": 28,
                  "ats_risk": "low", "size_risk": "medium", "jd_pattern_risk": "medium", "signals": []},
        ),
    },
    {
        "key": "halcyon-dre",
        "company": "Halcyon Grid", "role": "Detection & Response Engineer",
        "location": "Remote (US)", "ats": "lever", "tier": "tier_3", "category": "endpoint",
        "scores": dict(combined=71.0, alignment=74, ghost=18, redflag=36, resume_match=66, monoculture=40),
        "judged_days_ago": 1,
        "reason": "Good technical fit with a churn signal worth asking about.",
        "extra": "Fast-paced, high-growth environment. Detection-as-code in a modern stack.",
        "state": {"prepped": False, "dossier": None, "contacts": False, "salary": False},
        "detail": detail(
            ghost=("Some ghost risk. The role was reposted 4 times in 6 months.",
                   [("warn", "repost", "Reposted repeatedly")]),
            red=("A churn signal, no dealbreakers.", [],
                 [("Fast-paced", '"thrive in ambiguity"', "Possible burnout or unclear priorities.")], []),
            align={"closest_target": "Detection Engineer", "assessment": "Adjacent to SOC; a stretch on engineering depth.",
                   "overlap": ["detection tuning", "SIEM"], "gaps": ["Python at scale", "cloud IR"],
                   "stepping_stone": "Could bridge from analyst to engineer."},
            resume={"match_type": "transferable", "summary": "Partial. Detection concepts overlap; tooling is the gap.",
                    "overlap": ["alert triage", "MITRE ATT&CK"], "gaps": ["Terraform", "Go"],
                    "transferable": ["incident documentation"]},
            mono={"summary": "Elevated screening risk from a rigid keyword list.", "monoculture_score": 40,
                  "ats_risk": "medium", "size_risk": "medium", "jd_pattern_risk": "high",
                  "signals": [{"category": "screening_phrase", "evidence": "exactly 5 years", "risk": 18},
                              {"category": "vendor_mention", "evidence": "three named EDR/SIEM vendors", "risk": 10}]},
        ),
    },
    {
        "key": "quillon-iam",
        "company": "Quillon Identity", "role": "IAM Analyst",
        "location": "Remote (US)", "ats": "smartrecruiters", "tier": "tier_2", "category": "identity",
        "scores": dict(combined=66.4, alignment=68, ghost=22, redflag=26, resume_match=64, monoculture=34),
        "judged_days_ago": 41,
        "reason": "Decent identity fit; judged a while ago and still listed.",
        "extra": "Access reviews, joiner/mover/leaver automation and SSO onboarding.",
        "state": {"prepped": False, "dossier": None, "contacts": False, "salary": False},
        "detail": detail(
            ghost=("Moderate ghost risk. Listed for 6+ weeks.",
                   [("warn", "age", "Posting has been open a long time")]),
            red=("No dealbreakers.", [], [], []),
            align={"closest_target": "IAM Analyst", "assessment": "Adjacent. Access reviews overlap with audit work.",
                   "overlap": ["access reviews", "SOX ITGCs"], "gaps": ["Okta admin depth"], "stepping_stone": None},
            resume={"match_type": "transferable", "summary": "Audit-side identity experience transfers.",
                    "overlap": ["user access reviews"], "gaps": ["SCIM provisioning"], "transferable": ["control testing"]},
            mono={"summary": "Moderate.", "monoculture_score": 34, "ats_risk": "medium", "size_risk": "low",
                  "jd_pattern_risk": "medium", "signals": []},
        ),
    },
]

# Held back until a visitor runs the paid judge in the demo, then they land in Ready.
RESERVE_READY: list[dict[str, Any]] = [
    {
        "key": "cobalt-cloudsec",
        "company": "Cobalt Harbor", "role": "Cloud Security Analyst",
        "location": "Remote (US)", "ats": "greenhouse", "tier": "tier_1", "category": "cloud_security",
        "scores": dict(combined=82.7, alignment=86, ghost=9, redflag=16, resume_match=79, monoculture=24),
        "judged_days_ago": 0,
        "reason": "Fresh from the judge: cloud posture work with a clear analyst track.",
        "extra": "CSPM triage, IAM reviews and guardrails across AWS and GCP.",
        "state": {"prepped": False, "dossier": None, "contacts": False, "salary": False},
        "detail": detail(
            ghost=("No ghost signals.", []),
            red=("One green flag.", [], [],
                 [("Clear ladder", '"defined analyst to engineer path"', "Growth is spelled out.")]),
            align={"closest_target": "Cloud Security Analyst", "assessment": "Good fit for cloud-leaning SOC work.",
                   "overlap": ["AWS", "IAM reviews"], "gaps": ["GCP"], "stepping_stone": None},
            resume={"match_type": "direct", "summary": "Cloud log analysis lines up.",
                    "overlap": ["CloudTrail", "GuardDuty"], "gaps": ["Terraform"], "transferable": ["control testing"]},
            mono={"summary": "Low.", "monoculture_score": 24, "ats_risk": "low", "size_risk": "low",
                  "jd_pattern_risk": "low", "signals": []},
        ),
    },
    {
        "key": "lanternfish-vm",
        "company": "Lanternfish Security", "role": "Vulnerability Management Analyst",
        "location": "Remote (US)", "ats": "lever", "tier": "tier_2", "category": "endpoint",
        "scores": dict(combined=69.3, alignment=72, ghost=14, redflag=22, resume_match=70, monoculture=31),
        "judged_days_ago": 0,
        "reason": "Fresh from the judge: solid vuln-management scope, modest pay band.",
        "extra": "Own the scan cadence, risk-rank findings, and chase remediation with owners.",
        "state": {"prepped": False, "dossier": None, "contacts": False, "salary": False},
        "detail": detail(
            ghost=("Low ghost risk.", []),
            red=("No dealbreakers.", [], [], []),
            align={"closest_target": "Vulnerability Analyst", "assessment": "Reasonable fit.",
                   "overlap": ["risk ranking", "remediation tracking"], "gaps": ["scanner admin"], "stepping_stone": None},
            resume={"match_type": "transferable", "summary": "Risk register work transfers.",
                    "overlap": ["risk register"], "gaps": ["Tenable"], "transferable": ["stakeholder follow-up"]},
            mono={"summary": "Moderate.", "monoculture_score": 31, "ats_risk": "medium", "size_risk": "low",
                  "jd_pattern_risk": "medium", "signals": []},
        ),
    },
]

# ── Awaiting: harvested, not judged yet ─────────────────────────────────

GATHERED: list[dict[str, Any]] = [
    {"company": "Aegis Cloud Security", "role": "Security Engineer II", "ats": "greenhouse", "tier": "tier_1", "category": "cloud_security", "enrichment_tier": "jsonld", "hours_ago": 3},
    {"company": "Verity Trust", "role": "Senior GRC Manager", "ats": "workday", "tier": "tier_1", "category": "grc", "enrichment_tier": "workday_cxs", "hours_ago": 3},
    {"company": "Halcyon Grid", "role": "Incident Response Consultant", "ats": "lever", "tier": "tier_3", "category": "endpoint", "enrichment_tier": None, "hours_ago": 4},
    {"company": "NorthBeacon Labs", "role": "Product Security Lead", "ats": "ashby", "tier": "tier_2", "category": "security_product_general", "enrichment_tier": None, "hours_ago": 4},
    {"company": "Meridian Defense Labs", "role": "SOC Manager", "ats": "workday", "tier": "tier_2", "category": "ai_research", "enrichment_tier": "ai_fallback", "hours_ago": 5},
    {"company": "Cobalt Harbor", "role": "Sales Engineer, Security", "ats": "greenhouse", "tier": "tier_1", "category": "security_product_general", "enrichment_tier": "jsonld", "hours_ago": 6},
    {"company": "Quillon Identity", "role": "Identity Engineer", "ats": "smartrecruiters", "tier": "tier_2", "category": "identity", "enrichment_tier": "jsonld", "hours_ago": 7},
    {"company": "Brightwater Health", "role": "Third-Party Risk Analyst", "ats": "workday", "tier": "tier_3", "category": "tprm", "enrichment_tier": None, "hours_ago": 8},
]

# ── Refused: the judge (or the cheap cull) said no ──────────────────────

REFUSED: list[dict[str, Any]] = [
    {"company": "Globex Manufacturing", "role": "IT Help Desk Technician", "ats": "successfactors", "tier": None,
     "reason": "[cull] Not a security role.", "combined": None, "judged_days_ago": 2, "detail": None},
    {"company": "Initech", "role": "Salesforce Administrator", "ats": "greenhouse", "tier": None,
     "reason": "[cull] Not a security role.", "combined": None, "judged_days_ago": 4, "detail": None},
    {"company": "Umbrella Retail", "role": "Junior Penetration Tester", "ats": "lever", "tier": "tier_3",
     "location": "On-site, New York", "reason": "On-site required and below-market pay; alignment floor not met.",
     "combined": 41.0, "judged_days_ago": 6,
     "extra": "On-site in New York five days a week. No remote.",
     "detail": detail(
         ghost=("Some ghost risk.", []),
         red=("On-site dealbreaker.",
              [("On-site required", '"in office 5 days"', "No remote.")], [], []),
         align={"closest_target": "Pen Tester", "assessment": "Junior offensive role, off the target list.",
                "overlap": ["security fundamentals"], "gaps": ["hands-on exploitation"], "stepping_stone": None},
         resume={"match_type": "weak", "summary": "Limited overlap.", "overlap": [], "gaps": ["OSCP"],
                 "transferable": ["reporting"]},
         mono={"summary": "Moderate.", "monoculture_score": 33, "ats_risk": "medium", "size_risk": "low",
               "jd_pattern_risk": "medium", "signals": []})},
    {"company": "Hooli Cloud", "role": "Customer Delivery Architect", "ats": "workday", "tier": None,
     "reason": "Not a security role on a closer read; customer-success adjacent.", "combined": 38.0,
     "judged_days_ago": 11, "extra": "Customer-facing delivery.",
     "detail": detail(
         ghost=("No ghost signals.", []),
         red=("None.", [], [], []),
         align={"closest_target": "(none)", "assessment": "Not security-aligned.", "overlap": [],
                "gaps": ["security scope"], "stepping_stone": None},
         resume={"match_type": "weak", "summary": "Low.", "overlap": [], "gaps": [], "transferable": []},
         mono={"summary": "Low.", "monoculture_score": 15, "ats_risk": "low", "size_risk": "low",
               "jd_pattern_risk": "low", "signals": []})},
    {"company": "Vandelay Industries", "role": "Security Analyst (Rockstar)", "ats": "smartrecruiters", "tier": "tier_3",
     "reason": "Two dealbreakers: unpaid take-home project and \"like family\" culture language.", "combined": 33.5,
     "judged_days_ago": 19, "extra": "We're looking for a rockstar who treats the team like family.",
     "detail": detail(
         ghost=("Moderate ghost risk.", [("warn", "vague", "No team or manager named")]),
         red=("Two dealbreakers.",
              [("Unpaid assessment", '"8-hour take-home project"', "Free labor before an offer."),
               ("\"Like family\"", '"we\'re a family here"', "Often means blurred boundaries.")], [], []),
         align={"closest_target": "SOC Analyst", "assessment": "On paper a fit; the culture signals sink it.",
                "overlap": ["triage"], "gaps": [], "stepping_stone": None},
         resume={"match_type": "direct", "summary": "Fine match.", "overlap": ["triage"], "gaps": [],
                 "transferable": []},
         mono={"summary": "Moderate.", "monoculture_score": 36, "ats_risk": "medium", "size_risk": "medium",
               "jd_pattern_risk": "medium", "signals": []})},
    {"company": "Soylent Logistics", "role": "Senior Security Architect", "ats": "workday", "tier": "tier_3",
     "reason": "Seniority well above the profile; 12+ years required.", "combined": 44.2, "judged_days_ago": 63,
     "extra": "12+ years of architecture experience required.",
     "detail": None},
    {"company": "Wonka Confections", "role": "Physical Security Officer", "ats": "successfactors", "tier": None,
     "reason": "[cull] Physical security, not information security.", "combined": None, "judged_days_ago": 120,
     "detail": None},
]

# Ready rows archived by "Archive stale" before the demo starts (shown as a footnote).
EXPIRED: list[dict[str, Any]] = [
    {"company": "Pied Piper", "role": "Security Operations Analyst", "ats": "ashby", "judged_days_ago": 70},
    {"company": "Cyberdyne Analytics", "role": "Detection Analyst", "ats": "greenhouse", "judged_days_ago": 66},
]

# ── Applications ────────────────────────────────────────────────────────
# `from_ready` links an application to a judged posting (so its dossier,
# letter and salary stay readable after applying).

APPLICATIONS: list[dict[str, Any]] = [
    {"company": "Sentinel Ridge", "role": "Security Analyst", "status": "interviewing", "applied_days_ago": 12,
     "updated_days_ago": 2, "notes": "Recruiter screen went well; technical round next.",
     "from_ready": {"ats": "greenhouse", "tier": "tier_1", "category": "cloud_security",
                    "dossier": "fresh", "contacts": True, "salary": True, "prepped": True}},
    {"company": "Ostrander Bank", "role": "IT Audit Analyst", "status": "responded", "applied_days_ago": 9,
     "updated_days_ago": 3, "notes": None,
     "from_ready": {"ats": "workday", "tier": "tier_2", "category": "grc",
                    "dossier": "fresh", "contacts": True, "salary": False, "prepped": True}},
    {"company": "Pinnacle Health Systems", "role": "Compliance Specialist", "status": "acknowledged",
     "applied_days_ago": 7, "updated_days_ago": 6, "notes": "Auto-acknowledgement email received."},
    {"company": "Tidewater Insurance", "role": "SOC Analyst", "status": "applied", "applied_days_ago": 4,
     "updated_days_ago": 4, "notes": None},
    {"company": "Ironleaf Software", "role": "Security Engineer I", "status": "applied", "applied_days_ago": 24,
     "updated_days_ago": 24, "notes": None},
    {"company": "Drayton Systems", "role": "SOC Analyst I", "status": "ghosted", "applied_days_ago": 35,
     "updated_days_ago": 10, "notes": "No reply in 3 weeks."},
    {"company": "Lumen Grove", "role": "Threat Intel Analyst", "status": "rejected", "applied_days_ago": 22,
     "updated_days_ago": 11, "notes": "Went with an internal candidate."},
    {"company": "Harbor & Finch", "role": "Risk Analyst", "status": "offered", "applied_days_ago": 30,
     "updated_days_ago": 5, "notes": "Offer in hand; comparing."},
    # Terminal and older than 45 days: archived out of the default view.
    {"company": "Brockton Freight", "role": "Security Coordinator", "status": "ghosted", "applied_days_ago": 80,
     "updated_days_ago": 58, "notes": None},
    {"company": "Elmstead College", "role": "Information Security Analyst", "status": "rejected",
     "applied_days_ago": 95, "updated_days_ago": 70, "notes": None},
    {"company": "Corvid Telecom", "role": "SOC Analyst II", "status": "ghosted", "applied_days_ago": 75,
     "updated_days_ago": 50, "notes": None},
]

# ── Per-company research ────────────────────────────────────────────────

DIMENSION_KEYS = (
    "security_culture", "people_treatment", "leadership_transparency",
    "work_life_balance", "compensation", "financial_health",
)


def dossier(company: str, scores: tuple[int, ...], summary: str, verdict: str,
            notes: dict[str, tuple[str, list[str]]] | None = None) -> dict[str, Any]:
    notes = notes or {}
    dims = {}
    for key, score in zip(DIMENSION_KEYS, scores):
        assessment, evidence = notes.get(key, ("", []))
        dims[key] = {"score": score, "assessment": assessment, "evidence": evidence}
    weighted = round(sum(scores) / len(scores) + 2.5, 1)
    return {
        "company": company,
        "summary": summary,
        "overall_score": round(sum(scores) / len(scores), 1),
        "weighted_score": weighted,
        "dimensions": dims,
        "verdict": verdict,
    }


DOSSIERS: dict[str, dict[str, Any]] = {
    "Aegis Cloud Security": dossier(
        "Aegis Cloud Security", (88, 79, 74, 81, 77, 72),
        "Mid-size cloud security vendor with a public security program and a steady hiring pace.",
        "A good bet. Ask how on-call is staffed and whether the SOC is growing or backfilling.",
        {"security_culture": ("Publishes a security whitepaper and runs a bug bounty.",
                              ["Public bug bounty program (sample source)", "Annual transparency report (sample source)"]),
         "people_treatment": ("Reviews mention supportive managers, some on-call fatigue.",
                              ["Employee review site, 4.1 average (sample source)"]),
         "work_life_balance": ("Remote-first with core hours.", ["Careers page (sample source)"])},
    ),
    "Verity Trust": dossier(
        "Verity Trust", (76, 71, 69, 84, 66, 70),
        "Trust and compliance platform; mature audit calendar and a small, stable GRC team.",
        "Solid. Compensation trails the market a little, so negotiate.",
        {"compensation": ("Posted band sits slightly under market midpoints.", ["Salary survey (sample source)"])},
    ),
    "NorthBeacon Labs": dossier(
        "NorthBeacon Labs", (82, 68, 61, 70, 80, 58),
        "Developer-tools company with a strong AppSec reputation and a recent leadership change.",
        "Worth it for the learning. Ask about runway; funding news is older than a year.",
        {"financial_health": ("Last raise was over a year ago.", ["Funding announcement (sample source)"])},
    ),
    "Sentinel Ridge": dossier(
        "Sentinel Ridge", (84, 80, 77, 75, 73, 76),
        "Managed detection provider with low turnover and a visible conference presence.",
        "Strong. Matches the values profile on most dimensions.",
    ),
    "Ostrander Bank": dossier(
        "Ostrander Bank", (72, 70, 64, 79, 74, 86),
        "Regional bank with a conservative, well-documented IT audit function.",
        "Stable and predictable. Slower pace than a vendor.",
    ),
}

# Built when a visitor clicks "Build dossier" in the demo.
PENDING_DOSSIERS: dict[str, dict[str, Any]] = {
    "Halcyon Grid": dossier(
        "Halcyon Grid", (77, 58, 55, 52, 81, 69),
        "Fast-growing endpoint startup. Strong engineering, frequent reorganizations.",
        "Go in with eyes open: ask about the repost history and team turnover.",
        {"people_treatment": ("Reviews mention reorgs every few quarters.", ["Employee review site (sample source)"]),
         "work_life_balance": ("Several reviews describe long weeks near launches.", ["Employee review site (sample source)"])},
    ),
    "Meridian Defense Labs": dossier(
        "Meridian Defense Labs", (80, 72, 66, 74, 70, 77),
        "Threat research shop with public reports and a steady customer base.",
        "Good fit for CTI work; the ATS screening is the main hurdle.",
    ),
    "Quillon Identity": dossier(
        "Quillon Identity", (73, 69, 67, 78, 68, 71),
        "Identity vendor; mid-size, stable, unremarkable in either direction.",
        "Fine. Nothing alarming, nothing exceptional.",
    ),
    "Cobalt Harbor": dossier(
        "Cobalt Harbor", (79, 76, 72, 80, 75, 74),
        "Cloud infrastructure company with a growing security org.",
        "Promising. The analyst-to-engineer ladder is real per employee posts.",
    ),
    "Lanternfish Security": dossier(
        "Lanternfish Security", (75, 73, 70, 77, 62, 68),
        "Small vulnerability-management vendor with a friendly culture.",
        "Nice team, modest pay. Negotiate.",
    ),
}


def person(name: str, title: str, category: str, source: str, relevance: str,
           route: str | None = None, date: str | None = None) -> dict[str, Any]:
    slug = name.lower().replace(" ", "-")
    return {"name": name, "title": title, "category": category, "source_type": source,
            "url": f"https://example.org/people/{slug}", "contact_route": route,
            "source_date": date, "relevance": relevance}


CONTACTS: dict[str, dict[str, Any]] = {
    "Aegis Cloud Security": {"contacts": [
        person("Morgan Vale", "Director of Security Operations", "security_leadership", "conference",
               "Spoke on SOC automation at a regional security conference.", "Email on the company site", "2026"),
        person("Priya Okafor", "Technical Recruiter", "recruiter", "company_site",
               "Listed as the recruiting contact for security roles.", "careers@example.com"),
        person("Sam Ortiz", "Senior Detection Engineer", "practitioner", "github",
               "Maintains the company's open detection rules repo."),
    ], "search_notes": "Sample data. Every link points at example.org."},
    "Verity Trust": {"contacts": [
        person("Dana Whitfield", "Head of GRC", "security_leadership", "press",
               "Quoted in a trade article on SOC 2 automation."),
        person("Jordan Lee", "Talent Partner", "recruiter", "company_site",
               "Recruiting contact on the careers page."),
    ], "search_notes": "Sample data. Every link points at example.org."},
    "Meridian Defense Labs": {"contacts": [
        person("Riley Chen", "Recruiting Lead", "recruiter", "social",
               "Posts security openings on a fediverse account.", "DMs open on infosec.exchange (sample)"),
        person("Alex Romero", "Principal Threat Researcher", "practitioner", "personal_site",
               "Writes the company's public threat reports."),
    ], "search_notes": "Sample data. No security leader turned up; the recruiter is the best route."},
    "NorthBeacon Labs": {"contacts": [
        person("Casey Brandt", "VP, Product Security", "security_leadership", "conference",
               "Gave a talk on developer-first AppSec.", None, "2025"),
        person("Taylor Nguyen", "AppSec Engineer", "practitioner", "advisory",
               "Credited on a published advisory."),
    ], "search_notes": "Sample data. Every link points at example.org."},
    "Sentinel Ridge": {"contacts": [
        person("Avery Brooks", "SOC Manager", "security_leadership", "chapter",
               "Organizes a local security meetup."),
        person("Jamie Patel", "Recruiter", "recruiter", "company_site", "Recruiting contact."),
    ], "search_notes": "Sample data."},
    "Ostrander Bank": {"contacts": [
        person("Robin Clarke", "IT Audit Manager", "security_leadership", "press", "Quoted in a banking trade piece."),
    ], "search_notes": "Sample data."},
}

# What a demo contacts search "finds".
PENDING_CONTACTS: dict[str, dict[str, Any]] = {
    "Halcyon Grid": {"contacts": [
        person("Quinn Albright", "Head of Detection & Response", "security_leadership", "conference",
               "Presented on detection-as-code at a security conference.", None, "2026"),
        person("Harper Moss", "Recruiter, Security", "recruiter", "company_site", "Recruiting contact for security roles."),
        person("Devon Park", "Detection Engineer", "practitioner", "github", "Commits to the public detections repo."),
    ], "search_notes": "Sample data. Every link points at example.org."},
    "Quillon Identity": {"contacts": [
        person("Skyler Reyes", "Talent Acquisition", "recruiter", "company_site", "Recruiting contact."),
    ], "search_notes": "Sample data. No security leader turned up."},
    "Cobalt Harbor": {"contacts": [
        person("Emerson Hale", "CISO", "security_leadership", "press", "Interviewed about cloud guardrails."),
    ], "search_notes": "Sample data."},
    "Lanternfish Security": {"contacts": [], "search_notes": "Sample data. Nobody turned up outside LinkedIn, so the letter goes to the team."},
}


def salary(low: int, mid: int, high: int, confidence: str, posted: str | None) -> dict[str, Any]:
    return {"currency": "USD", "low": low, "mid": mid, "high": high,
            "confidence": confidence, "posted_range": posted}


SALARIES: dict[str, dict[str, Any]] = {
    "aegis-soc": salary(115000, 132000, 150000, "high", "$120K–$150K"),
    "verity-grc": salary(95000, 108000, 120000, "medium", "$95K–$120K"),
    "northbeacon-appsec": salary(140000, 160000, 185000, "medium", "$140K–$185K"),
    "app:Sentinel Ridge": salary(98000, 112000, 126000, "medium", None),
}

# What "Salary intel" returns for a card that hasn't pulled it yet.
PENDING_SALARY = salary(104000, 121000, 138000, "medium", None)


def salary_md(company: str, role: str, s: dict[str, Any]) -> str:
    posted = s.get("posted_range") or "not listed"
    return (
        f"# Salary intel: {role}, {company}\n\n"
        f"**Suggested range:** ${s['low']:,} to ${s['high']:,}\n"
        f"**Target ask:** ${s['mid']:,}\n"
        f"**Posted range:** {posted}\n"
        f"**Confidence:** {s['confidence']}\n\n"
        "## How this was worked out\n\n"
        "- Sample market data for similar titles at similar-size companies\n"
        "- Remote US roles, adjusted for the posting's seniority\n"
        "- The candidate's years of directly relevant experience\n\n"
        "---\n\n"
        "This is demo data. Nothing here came from a real lookup."
    )


# ── Pipeline-scale numbers ──────────────────────────────────────────────
# The seeded database holds a few dozen rows; a real pipeline holds tens of
# thousands. These replace the headline counters only. Every key must exist
# in the real /api/stats payload, which the build checks.

STATS_OVERRIDES: dict[str, int] = {
    "gathered": 18412,
    "judged": 17327,
    "culled": 15012,
    "judged_sonnet": 2315,
    "unjudged": 430,
    "judgeable": 64,
    "awaiting_enrich": 23,
    "cullable": 212,
    "refused": 17196,
}
GATHERED_TOTAL = 412
REFUSED_TOTALS = {30: 1284, 90: 3921, None: 17196}
FERRY_EMPLOYERS = 1130
