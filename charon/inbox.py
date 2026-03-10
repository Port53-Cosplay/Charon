"""IMAP inbox monitor for application response detection."""

import email
import email.header
import imaplib
import os
import ssl
from datetime import datetime, timedelta, timezone
from typing import Any

from charon.ai import query_claude_json, AIError
from charon.db import get_applications, queue_digest, update_application_status
from charon.secrets import get_imap_password, SecretsError

# Map AI classification to application status
CLASSIFICATION_TO_STATUS = {
    "interview": "interviewing",
    "offer": "offered",
    "rejection": "rejected",
    "acknowledgment": "responded",
}


CLASSIFY_SYSTEM = """You are an email classifier for a job application tracker.
Given an email subject, sender, and body snippet, determine if it is a response
to a job application. If so, classify it.

Return JSON:
{
    "is_job_response": true/false,
    "company_match": "company name if recognized, else null",
    "classification": "interview|rejection|offer|acknowledgment|other",
    "confidence": "high|medium|low",
    "summary": "one-line summary of the email"
}

Only classify as a job response if the email is clearly from or about an employer
regarding a job application. Marketing emails, newsletters, job board alerts, and
automated "your profile was viewed" messages are NOT job responses.
"""


class InboxError(Exception):
    """Raised when inbox operations fail."""


def _decode_header(raw: str) -> str:
    """Decode an email header value (handles RFC 2047 encoded words)."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _connect_imap(account: dict[str, Any], profile: dict[str, Any]) -> imaplib.IMAP4_SSL:
    """Connect and authenticate to an IMAP server."""
    server = account.get("imap_server", "")
    user = account.get("imap_user", "")
    port = account.get("imap_port", 993)
    name = account.get("name", "unknown")

    if not server or not user:
        raise InboxError(
            f"IMAP not configured for account '{name}'.\n"
            "  Set imap_server and imap_user in profile."
        )

    try:
        password = get_imap_password(profile, name)
    except SecretsError as e:
        raise InboxError(str(e))

    try:
        conn = imaplib.IMAP4_SSL(server, port, timeout=30)
        conn.login(user, password)
        return conn
    except imaplib.IMAP4.error as e:
        raise InboxError(f"IMAP login failed for {user}: {e}")
    except OSError as e:
        raise InboxError(f"Cannot connect to {server}:{port}: {e}")


def _build_imap_search(applications: list[dict[str, Any]], days: int) -> list[str]:
    """Build IMAP SEARCH criteria from tracked applications."""
    # Collect email domains and company names for OR search
    domains = set()
    companies = set()

    for app in applications:
        if app.get("email_domain"):
            domains.add(app["email_domain"])
        if app.get("company"):
            companies.add(app["company"])

    # IMAP date for SINCE criterion
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")

    # Build individual search queries (IMAP OR is awkward, so we search per term)
    queries = []
    for domain in domains:
        safe_domain = domain.replace('"', '').replace('\\', '')
        if safe_domain:
            queries.append(f'(SINCE {since_date} FROM "{safe_domain}")')
    for company in companies:
        safe_company = company.replace('"', '').replace('\\', '')
        if safe_company:
            queries.append(f'(SINCE {since_date} SUBJECT "{safe_company}")')

    return queries


def _extract_email_data(raw_email: bytes) -> dict[str, Any] | None:
    """Parse a raw email into structured data."""
    try:
        msg = email.message_from_bytes(raw_email)
        subject = _decode_header(msg.get("Subject", ""))
        from_addr = _decode_header(msg.get("From", ""))
        date = msg.get("Date", "")

        # Extract body snippet (first 500 chars of plain text)
        snippet = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        snippet = payload.decode("utf-8", errors="replace")[:500]
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                snippet = payload.decode("utf-8", errors="replace")[:500]

        return {
            "subject": subject,
            "from": from_addr,
            "date": date,
            "snippet": snippet,
        }
    except Exception:
        return None


def _scan_account(
    account: dict[str, Any],
    applications: list[dict[str, Any]],
    days: int,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Scan a single IMAP account for application responses."""
    conn = _connect_imap(account, profile)
    results = []

    try:
        conn.select("INBOX", readonly=True)
        queries = _build_imap_search(applications, days)

        seen_ids = set()
        for query in queries:
            try:
                status, data = conn.search(None, query)
                if status != "OK":
                    continue
                msg_ids = data[0].split()
                for mid in msg_ids:
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)

                    status, msg_data = conn.fetch(mid, "(RFC822)")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        continue

                    raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
                    if not raw:
                        continue

                    email_data = _extract_email_data(raw)
                    if email_data:
                        email_data["account"] = account.get("name", "unknown")
                        results.append(email_data)
            except imaplib.IMAP4.error:
                continue
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return results


def scan_inbox(
    profile: dict[str, Any],
    days: int = 7,
) -> list[dict[str, Any]]:
    """Scan configured IMAP accounts for application responses."""
    inbox_config = profile.get("inbox", {})
    accounts = inbox_config.get("accounts", [])

    if not accounts:
        raise InboxError(
            "No inbox accounts configured. Add to profile:\n"
            "  inbox:\n"
            "    accounts:\n"
            "      - name: gmail\n"
            "        imap_server: imap.gmail.com\n"
            "        imap_user: you@gmail.com\n"
            "        imap_pass: \"\"  # or set CHARON_IMAP_PASS_GMAIL env var"
        )

    # Get active applications
    active_statuses = ["applied", "responded", "interviewing"]
    applications = []
    for status in active_statuses:
        applications.extend(get_applications(status))

    if not applications:
        return []

    # Scan each account
    all_emails = []
    errors = []
    for account in accounts:
        try:
            emails = _scan_account(account, applications, days, profile)
            all_emails.extend(emails)
        except InboxError as e:
            errors.append(str(e))

    if not all_emails and errors:
        raise InboxError("All accounts failed:\n  " + "\n  ".join(errors))

    # Classify each email with AI
    app_context = "\n".join(
        f"- {a['company']} ({a['role']})" for a in applications
    )

    classified = []
    for email_data in all_emails:
        try:
            classification = query_claude_json(
                CLASSIFY_SYSTEM,
                f"Active applications:\n{app_context}\n\n"
                f"Email (from {email_data['account']} account):\n"
                f"  From: {email_data['from']}\n"
                f"  Subject: {email_data['subject']}\n"
                f"  Snippet: {email_data['snippet'][:300]}\n"
                f"  Date: {email_data['date']}",
            )
        except AIError:
            continue

        if classification.get("is_job_response"):
            classified.append({
                "email": email_data,
                "classification": classification,
            })

            company = classification.get("company_match", "Unknown")
            cls_type = classification.get("classification", "other")
            summary = classification.get("summary", email_data["subject"])

            # Auto-update application status
            new_status = CLASSIFICATION_TO_STATUS.get(cls_type)
            matched_app = None
            if new_status and company and company != "Unknown":
                for app in applications:
                    if app["company"].lower() == company.lower():
                        matched_app = app
                        break
                if matched_app:
                    update_application_status(matched_app["id"], new_status)

            # Queue for digest
            queue_digest(
                "response",
                f"{company}: {summary} [{cls_type}]",
                {
                    "email_from": email_data["from"],
                    "email_subject": email_data["subject"],
                    "classification": cls_type,
                    "company": company,
                    "account": email_data["account"],
                    "app_id": matched_app["id"] if matched_app else None,
                    "auto_status": new_status if matched_app else None,
                },
            )

    return classified
