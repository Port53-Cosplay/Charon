"""Charon CLI entry point."""

import os
import subprocess
import sys
from pathlib import Path

import click
import yaml
from rich.table import Table

from charon import __version__
from charon.output import (
    console,
    panel,
    print_banner,
    print_error,
    print_info,
    print_score_inverted,
    print_success,
    print_warning,
    section_header,
)
from charon.profile import (
    PROFILE_PATH,
    ProfileError,
    create_default_profile,
    get_profile_display,
    load_profile,
)
from charon.db import clear_history, get_history, save_history, queue_digest, add_watch, remove_watch, get_watchlist
from charon.fetcher import FetchError, fetch_url, read_paste
from charon.ghostbust import analyze_ghostbust
from charon.redflags import analyze_redflags
from charon.dossier import analyze_dossier, save_dossier_markdown
from charon.hunt import run_hunt, run_hunt_recon, run_hunt_dossier
from charon.batch import run_batch
from charon.digest import DigestError, build_digest, send_digest, preview_digest
from charon.ai import AIError
from charon.apply import ApplyError, track_application, update_status, check_ghosted, get_stats, list_applications
from charon.inbox import InboxError
from charon.gather import (
    GatherError,
    DEFAULT_RATE_LIMIT_SECONDS,
    gather_registry,
    list_employers,
    load_registry,
)


@click.group()
@click.version_option(version=__version__, prog_name="charon")
def cli() -> None:
    """Charon - Getting you to the other side.

    A CLI tool for job seekers who are done with ghost jobs,
    toxic workplaces, and corporate doublespeak.
    """
    pass


# ── profile ──────────────────────────────────────────────────────────


@cli.command()
@click.option("--show", is_flag=True, help="Display your current profile.")
@click.option("--edit", is_flag=True, help="Open your profile in $EDITOR.")
@click.option("--reset", is_flag=True, help="Reset profile to defaults. Your soul, wiped clean.")
def profile(show: bool, edit: bool, reset: bool) -> None:
    """Manage your values profile. The ferryman needs to know who you are."""
    if not any([show, edit, reset]):
        show = True  # default action

    if reset:
        create_default_profile()
        print_success(f"Profile reset to defaults at {PROFILE_PATH}")
        print_info("The slate is clean. Configure your values before the next crossing.")
        return

    if not PROFILE_PATH.exists():
        print_warning("No profile found. Creating default profile...")
        create_default_profile()
        print_success(f"Profile created at {PROFILE_PATH}")
        print_info("Edit it with: charon profile --edit")
        return

    if edit:
        editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))
        if not editor:
            # Fallback for Windows
            if sys.platform == "win32":
                editor = "notepad"
            else:
                print_error("No $EDITOR set. Set EDITOR env var or use: charon profile --show")
                return
        try:
            subprocess.run([editor, str(PROFILE_PATH)], check=True)
            # Validate after editing
            try:
                load_profile()
                print_success("Profile saved and validated.")
            except ProfileError as e:
                print_error(f"Profile has errors: {e}")
                print_warning("Fix the issues and try again.")
        except FileNotFoundError:
            print_error(f"Editor '{editor}' not found. Set $EDITOR to your preferred editor.")
        return

    if show:
        try:
            prof = load_profile()
        except ProfileError as e:
            print_error(f"Profile error: {e}")
            return

        print_banner()
        section_header("OPERATIVE PROFILE")

        # Values weights
        safe = get_profile_display(prof)
        values = safe.get("values", {})
        console.print("[header]Values Weights[/header]")
        for dimension, weight in values.items():
            label = dimension.replace("_", " ").title()
            print_score_inverted(f"{label:<28}", weight * 100)
        console.print()

        # Dealbreakers
        console.print("[danger]Dealbreakers[/danger]")
        for item in safe.get("dealbreakers", []):
            console.print(f"  [danger][X][/danger] {item}")
        console.print()

        # Yellow flags
        console.print("[warning]Yellow Flags[/warning]")
        for item in safe.get("yellow_flags", []):
            console.print(f"  [warning][!][/warning] {item}")
        console.print()

        # Green flags
        console.print("[good]Green Flags[/good]")
        for item in safe.get("green_flags", []):
            console.print(f"  [good][+][/good] {item}")
        console.print()

        # Target roles
        console.print("[info]Target Roles[/info]")
        for role in safe.get("target_roles", []):
            console.print(f"  [info][>][/info] {role}")
        console.print()

        # Notifications (sanitized)
        notif = safe.get("notifications", {})
        console.print("[header]Notifications[/header]")
        console.print(f"  Enabled:     {notif.get('enabled', False)}")
        console.print(f"  Mail server: {notif.get('mail_server', 'not set')}")
        console.print(f"  Mail to:     {notif.get('mail_to', 'not set')}")
        console.print()

        # Thresholds
        ghostbust_cfg = safe.get("ghostbust", {})
        console.print("[header]Thresholds[/header]")
        console.print(f"  Ghost disqualify: {ghostbust_cfg.get('disqualify_threshold', 70)}%")
        console.print()


# ── history ──────────────────────────────────────────────────────────


@cli.command()
@click.option("--list", "list_history", is_flag=True, help="Show recent command history.")
@click.option("--clear", is_flag=True, help="Clear all history. What's done is done.")
@click.option("--limit", default=20, help="Number of entries to show.")
def history(list_history: bool, clear: bool, limit: int) -> None:
    """View past crossings. The ferryman remembers all."""
    if clear:
        count = clear_history()
        if count:
            print_success(f"Cleared {count} entries. The river forgets.")
        else:
            print_info("History is already empty. Nothing to forget.")
        return

    # Default to list
    entries = get_history(limit=limit)
    if not entries:
        print_info("No history yet. The ledger is blank.")
        print_info("Run a command to begin: charon ghostbust --url <url>")
        return

    table = Table(title="Crossing Ledger", border_style="dim", header_style="bold white")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Time", width=20)
    table.add_column("Command", style="info", width=12)
    table.add_column("Input", max_width=40)
    table.add_column("Score", width=8, justify="right")
    table.add_column("Company", max_width=20)

    for entry in entries:
        score = f"{entry['score']:.0f}" if entry.get("score") is not None else "-"
        # Truncate input for display
        input_val = entry.get("input_value", "")
        if len(input_val) > 40:
            input_val = input_val[:37] + "..."

        timestamp = entry.get("timestamp", "")[:19].replace("T", " ")

        table.add_row(
            str(entry["id"]),
            timestamp,
            entry.get("command", ""),
            input_val,
            score,
            entry.get("company") or "-",
        )

    console.print(table)


# ── placeholder commands (to be implemented in later phases) ─────────


@cli.command()
@click.option("--url", help="URL of the job posting to analyze.")
@click.option("--paste", is_flag=True, help="Paste job posting text from stdin.")
def ghostbust(url: str | None, paste: bool) -> None:
    """Detect ghost jobs. Are they even hiring, or is this a mirage?"""
    if not url and not paste:
        print_error("Provide --url <url> or --paste. The ferryman needs something to judge.")
        return

    if url and paste:
        print_error("Pick one: --url or --paste. Not both.")
        return

    # Get the posting text
    try:
        if url:
            print_info(f"Fetching: {url}")
            posting_text = fetch_url(url)
            input_type, input_value = "url", url
        else:
            posting_text = read_paste()
            input_type, input_value = "paste", posting_text[:200]
    except FetchError as e:
        print_error(str(e))
        return

    print_info(f"Extracted {len(posting_text)} chars. Sending to the oracle...")
    console.print()

    # Run analysis
    try:
        result = analyze_ghostbust(posting_text)
    except AIError as e:
        print_error(str(e))
        return

    # Display results
    _display_ghostbust(result)

    # Save to history
    save_history("ghostbust", input_type, input_value, result["ghost_score"], result)
    queue_digest("ghostbust", f"Ghost score: {result['ghost_score']}% - {input_value[:80]}", result)


def _display_ghostbust(result: dict) -> None:
    """Render ghostbust results to the console."""
    from charon.output import print_score, make_flag_table

    score = result["ghost_score"]
    confidence = result["confidence"]

    print_banner()
    section_header("GHOST JOB ANALYSIS")

    # Score
    console.print("[header]Ghost Likelihood[/header]")
    print_score("Score", score)
    console.print(f"  Confidence: [info]{confidence.upper()}[/info]")
    console.print()

    # Verdict line
    if score >= 76:
        console.print("[danger]VERDICT: Almost certainly a ghost job. Save your time.[/danger]")
    elif score >= 51:
        console.print("[warning]VERDICT: Suspicious. Multiple ghost indicators detected.[/warning]")
    elif score >= 26:
        console.print("[warning]VERDICT: Some concerns, but could be legitimate.[/warning]")
    else:
        console.print("[good]VERDICT: Likely a real posting. Signals look genuine.[/good]")
    console.print()

    # Signals table
    signals = result.get("signals", [])
    if signals:
        table = make_flag_table("Ghost Signals")
        severity_style = {"red": "danger", "yellow": "warning", "green": "good"}
        severity_label = {"red": "RED", "yellow": "YLW", "green": "GRN"}

        for signal in signals:
            sev = signal["severity"]
            style = severity_style.get(sev, "dim")
            label = severity_label.get(sev, "???")
            table.add_row(
                f"[{style}]{label}[/{style}]",
                signal["category"],
                signal["finding"],
            )
        console.print(table)
        console.print()

    # Summary
    panel("Assessment", result.get("summary", "No summary available."), "info")


@cli.command()
@click.option("--url", help="URL of the job posting to analyze.")
@click.option("--paste", is_flag=True, help="Paste job posting text from stdin.")
def redflags(url: str | None, paste: bool) -> None:
    """Scan for toxic workplace signals. The dead know the signs."""
    if not url and not paste:
        print_error("Provide --url <url> or --paste. The ferryman needs something to judge.")
        return

    if url and paste:
        print_error("Pick one: --url or --paste. Not both.")
        return

    # Load profile for dealbreakers/flags
    try:
        prof = load_profile()
    except ProfileError as e:
        print_error(f"Profile error: {e}")
        return

    # Get the posting text
    try:
        if url:
            print_info(f"Fetching: {url}")
            posting_text = fetch_url(url)
            input_type, input_value = "url", url
        else:
            posting_text = read_paste()
            input_type, input_value = "paste", posting_text[:200]
    except FetchError as e:
        print_error(str(e))
        return

    print_info(f"Extracted {len(posting_text)} chars. Scanning for red flags...")
    console.print()

    # Run analysis
    try:
        result = analyze_redflags(posting_text, prof)
    except AIError as e:
        print_error(str(e))
        return

    # Display results
    _display_redflags(result)

    # Save to history
    save_history("redflags", input_type, input_value, result["redflag_score"], result)
    queue_digest("redflags", f"Red flag score: {result['redflag_score']}% - {input_value[:80]}", result)


def _display_redflags(result: dict) -> None:
    """Render redflags results to the console."""
    from charon.output import print_score

    score = result["redflag_score"]
    confidence = result["confidence"]

    print_banner()
    section_header("RED FLAG ANALYSIS")

    # Score
    console.print("[header]Red Flag Score[/header]")
    print_score("Score", score)
    console.print(f"  Confidence: [info]{confidence.upper()}[/info]")
    console.print()

    # Verdict
    if score >= 76:
        console.print("[danger]VERDICT: Major red flags detected. The dead advise against this one.[/danger]")
    elif score >= 51:
        console.print("[warning]VERDICT: Significant concerns. Proceed with caution.[/warning]")
    elif score >= 26:
        console.print("[warning]VERDICT: Some yellow flags. Investigate further before applying.[/warning]")
    else:
        console.print("[good]VERDICT: Looks clean. The ferryman approves... cautiously.[/good]")
    console.print()

    # Dealbreakers
    dealbreakers = result.get("dealbreakers_found", [])
    if dealbreakers:
        section_header("DEALBREAKERS")
        for item in dealbreakers:
            console.print(f"  [danger][X] {item['flag']}[/danger]")
            if item.get("evidence"):
                console.print(f"      Evidence: [dim]{item['evidence']}[/dim]")
            if item.get("interpretation"):
                console.print(f"      Meaning:  {item['interpretation']}")
            console.print()

    # Yellow flags
    yellows = result.get("yellow_flags_found", [])
    if yellows:
        section_header("YELLOW FLAGS")
        for item in yellows:
            console.print(f"  [warning][!] {item['flag']}[/warning]")
            if item.get("evidence"):
                console.print(f"      Evidence: [dim]{item['evidence']}[/dim]")
            if item.get("interpretation"):
                console.print(f"      Meaning:  {item['interpretation']}")
            console.print()

    # Green flags
    greens = result.get("green_flags_found", [])
    if greens:
        section_header("GREEN FLAGS")
        for item in greens:
            console.print(f"  [good][+] {item['flag']}[/good]")
            if item.get("evidence"):
                console.print(f"      Evidence: [dim]{item['evidence']}[/dim]")
            console.print()

    # No flags at all
    if not dealbreakers and not yellows and not greens:
        print_info("No flags detected. The posting is either clean or too vague to analyze.")
        console.print()

    # Summary
    panel("Assessment", result.get("summary", "No summary available."), "info")


@cli.command()
@click.option("--company", required=True, help="Company name to research.")
@click.option("--save", is_flag=True, help="Save dossier to file.")
def dossier(company: str, save: bool) -> None:
    """Build a company dossier. Know thy employer before they own thy soul."""
    # Load profile for values weights
    try:
        prof = load_profile()
    except ProfileError as e:
        print_error(f"Profile error: {e}")
        return

    print_info(f"Researching: {company}")
    print_info("The ferryman is consulting the oracle and scouring the web...")
    console.print()

    # Run analysis
    try:
        result = analyze_dossier(company, prof)
    except AIError as e:
        print_error(str(e))
        return

    # Display results
    _display_dossier(result, prof)

    # Save to file if requested
    if save:
        save_path = prof.get("dossier", {}).get("save_path", "~/.charon/dossiers/")
        try:
            filepath = save_dossier_markdown(result, save_path)
            print_success(f"Dossier saved to {filepath}")
        except OSError as e:
            print_error(f"Failed to save dossier: {e}")

    # Save to history
    save_history("dossier", "company", company, result.get("weighted_score"), result, company=company)
    queue_digest("dossier", f"Dossier: {company} - Score: {result.get('weighted_score')}/100", result)

    # Stamp dossier_at on tracked application if one exists
    from charon.db import find_application_by_company, update_application_dossier
    app = find_application_by_company(company)
    if app:
        update_application_dossier(app["id"])
        print_info(f"Dossier linked to application #{app['id']} ({app['role']})")


def _display_dossier(result: dict, prof: dict) -> None:
    """Render dossier results to the console."""
    from charon.output import print_score_inverted

    print_banner()
    section_header(f"DOSSIER: {result.get('company', 'UNKNOWN').upper()}")

    # Weighted score
    weighted = result.get("weighted_score", 0)
    raw = result.get("overall_score", 0)
    console.print("[header]Values Alignment Score[/header]")
    print_score_inverted("Weighted", weighted)
    print_score_inverted("Raw Avg ", raw)
    console.print()

    # Verdict line
    if weighted >= 76:
        console.print("[good]VERDICT: Strong alignment with your values. Worth pursuing.[/good]")
    elif weighted >= 51:
        console.print("[warning]VERDICT: Decent alignment, but investigate the weak dimensions.[/warning]")
    elif weighted >= 26:
        console.print("[warning]VERDICT: Below average alignment. Significant concerns in key areas.[/warning]")
    else:
        console.print("[danger]VERDICT: Poor alignment. The ferryman advises against this crossing.[/danger]")
    console.print()

    # Dimension breakdown
    dims = result.get("dimensions", {})
    values = prof.get("values", {})

    # Stock data summary (if available)
    stock = result.get("stock")
    if stock:
        section_header("STOCK DATA")
        price = stock.get("current_price", 0)
        currency = stock.get("currency", "$")
        console.print(f"  Ticker: [info]{stock.get('ticker', '?')}[/info]  Price: {currency}{price:.2f}")
        off_high = stock.get("off_high_pct", 0)
        if off_high <= -30:
            style = "danger"
        elif off_high <= -15:
            style = "warning"
        else:
            style = "good"
        console.print(f"  52wk High: {currency}{stock.get('week_52_high', 0):.2f}  Low: {currency}{stock.get('week_52_low', 0):.2f}  [{style}]Off High: {off_high:+.1f}%[/{style}]")
        chg_6m = stock.get("change_6m_pct")
        chg_1y = stock.get("change_1y_pct")
        parts = []
        if chg_6m is not None:
            s = "good" if chg_6m >= 0 else "danger"
            parts.append(f"6mo: [{s}]{chg_6m:+.1f}%[/{s}]")
        if chg_1y is not None:
            s = "good" if chg_1y >= 0 else "danger"
            parts.append(f"1yr: [{s}]{chg_1y:+.1f}%[/{s}]")
        if parts:
            console.print(f"  Trend: {' | '.join(parts)}")
        console.print()

    all_dims = ("security_culture", "people_treatment", "leadership_transparency", "work_life_balance", "compensation", "financial_health")

    for dim_name in all_dims:
        dim = dims.get(dim_name, {})
        label = dim_name.replace("_", " ").title()
        weight = values.get(dim_name, 0)

        if weight > 0:
            section_header(f"{label} (weight: {weight:.0%})")
        else:
            section_header(label)
        print_score_inverted("Score", dim.get("score", 0))
        console.print()

        assessment = dim.get("assessment", "")
        if assessment:
            console.print(f"  {assessment}")
            console.print()

        evidence = dim.get("evidence", [])
        if evidence:
            console.print("  [dim]Evidence:[/dim]")
            for e in evidence:
                console.print(f"    [dim]- {e}[/dim]")
            console.print()

    # Summary and verdict
    panel("Summary", result.get("summary", "No summary available."), "info")
    console.print()
    panel("Verdict", result.get("verdict", "No verdict available."), "header")

    # Contacts
    contacts_data = result.get("contacts", {})
    contacts_list = contacts_data.get("contacts", []) if isinstance(contacts_data, dict) else []
    if contacts_list:
        console.print()
        section_header("POTENTIAL CONTACTS")
        category_styles = {
            "recruiter": ("good", "Recruiter"),
            "hiring_manager": ("warning", "Hiring Mgr"),
            "team_member": ("info", "Team Member"),
        }
        for contact in contacts_list:
            cat = contact.get("category", "team_member")
            style, label = category_styles.get(cat, ("info", cat.title()))
            name = contact.get("name", "Unknown")
            title = contact.get("title", "")
            url_str = contact.get("linkedin_url", "")
            relevance = contact.get("relevance", "")
            console.print(f"  [{style}][{label}][/{style}]  {name} — {title}")
            if url_str:
                console.print(f"             [dim]{url_str}[/dim]")
            if relevance:
                console.print(f"             [dim]{relevance}[/dim]")
        search_notes = contacts_data.get("search_notes", "")
        if search_notes:
            console.print()
            console.print(f"  [dim]{search_notes}[/dim]")


@cli.command()
@click.option("--url", help="URL of the job posting to analyze.")
@click.option("--paste", is_flag=True, help="Paste job posting text from stdin.")
@click.option("--full", is_flag=True, help="Run all phases without confirmation.")
def hunt(url: str | None, paste: bool, full: bool) -> None:
    """Full pipeline: ghostbust > redflags > dossier. The complete crossing."""
    if not url and not paste:
        print_error("Provide --url <url> or --paste. The ferryman needs something to judge.")
        return

    if url and paste:
        print_error("Pick one: --url or --paste. Not both.")
        return

    # Load profile
    try:
        prof = load_profile()
    except ProfileError as e:
        print_error(f"Profile error: {e}")
        return

    print_banner()
    section_header("FULL HUNT")
    print_info("Running recon: ghostbust + redflags...")
    console.print()

    # Phase 1+2: Ghostbust + Redflags
    try:
        result, posting_text = run_hunt_recon(url, paste, prof, on_status=lambda msg: print_info(msg))
    except AIError as e:
        if "spoke in tongues" in str(e):
            print_error(str(e))
            print_warning("The AI returned malformed data. Try running again — it's usually intermittent.")
            if url and sys.stdout.isatty():
                paste_path = Path.home() / ".charon" / "job_posting.txt"
                if click.confirm("  Open job_posting.txt to paste the posting manually?", default=True):
                    paste_path.write_text("", encoding="utf-8")
                    click.launch(str(paste_path))
                    print_info(f"Paste the job posting into {paste_path}, save it, then run:")
                    print_info(f"  Get-Content \"{paste_path}\" | charon hunt --paste")
        else:
            print_error(str(e))
        return
    except FetchError as e:
        print_error(str(e))
        if url and sys.stdout.isatty():
            paste_path = Path.home() / ".charon" / "job_posting.txt"
            if click.confirm("  Open job_posting.txt to paste the posting manually?", default=True):
                paste_path.write_text("", encoding="utf-8")
                click.launch(str(paste_path))
                print_info(f"Paste the job posting into {paste_path}, save it, then run:")
                print_info(f"  Get-Content \"{paste_path}\" | charon hunt --paste")
        return

    console.print()

    # Display ghostbust results
    ghost = result.get("ghostbust")
    if ghost:
        section_header("1. GHOST JOB ANALYSIS")
        _display_ghostbust_summary(ghost)

    # Early exit on ghost threshold?
    if result.get("stopped_early"):
        console.print()
        panel(
            "Hunt Aborted",
            f"[danger]{result['stop_reason']}[/danger]\n\n"
            "The ferryman refuses to cross. This posting is not worth your time.",
            "danger",
        )
        score = ghost["ghost_score"] if ghost else None
        save_history("hunt", "url" if url else "paste", url or "(paste)", score, result)
        queue_digest("hunt", f"Hunt aborted - ghost score {score}%", result)
        return

    # Display redflags results
    redflag = result.get("redflags")
    if redflag:
        section_header("2. RED FLAG ANALYSIS")
        _display_redflags_summary(redflag)

    # Display role alignment
    role_align = result.get("role_alignment")
    if role_align:
        section_header("3. ROLE ALIGNMENT")
        _display_role_alignment_summary(role_align)

    # Ask before running dossier (unless --full)
    run_dossier = full
    if not full:
        company = result.get("company")
        if company:
            console.print()
            console.print(f"  [header]Company detected:[/header] {company}")
            run_dossier = click.confirm("  Run dossier on this company?", default=True)
        else:
            console.print()
            company_input = click.prompt(
                "  Enter company name for dossier (or press Enter to skip)",
                default="",
                show_default=False,
            )
            if company_input.strip():
                result["company"] = company_input.strip()
                run_dossier = True

    if run_dossier:
        console.print()
        try:
            result = run_hunt_dossier(
                result, posting_text, prof,
                company=result.get("company"),
                on_status=lambda msg: print_info(msg),
            )
        except AIError as e:
            print_error(str(e))

        dossier_result = result.get("dossier")
        if dossier_result:
            section_header("4. COMPANY DOSSIER")
            _display_dossier_summary(dossier_result, prof)

            # Stamp dossier_at on tracked application if one exists
            from charon.db import find_application_by_company, update_application_dossier
            dossier_company = dossier_result.get("company") or result.get("company")
            if dossier_company:
                app = find_application_by_company(dossier_company)
                if app:
                    update_application_dossier(app["id"])
                    print_info(f"Dossier linked to application #{app['id']}")
    else:
        console.print()
        print_info("Dossier skipped. Run 'charon dossier --company <name>' later if needed.")

    # Combined verdict
    console.print()
    _display_hunt_verdict(result)

    # Interactive drill-down (unless --full / non-interactive)
    if not full and sys.stdout.isatty():
        _display_hunt_detail(result, prof)

    # Save to history
    combined_score = _compute_hunt_score(result)
    save_history(
        "hunt",
        "url" if url else "paste",
        url or "(paste)",
        combined_score,
        result,
        company=result.get("company"),
    )
    queue_digest(
        "hunt",
        f"Hunt: {result.get('company', 'unknown')} - Score: {combined_score}/100",
        result,
    )

    # Append to hunt log
    _append_hunt_log(result, url, combined_score)


def _append_hunt_log(result: dict, url: str | None, score: float) -> None:
    """Append an entry to ~/.charon/hunt_log.txt."""
    from datetime import datetime, timezone
    log_path = Path.home() / ".charon" / "hunt_log.txt"
    source = url or "(paste)"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    ghost = (result.get("ghostbust") or {}).get("ghost_score", "-")
    redflag = (result.get("redflags") or {}).get("redflag_score", "-")
    role_align = (result.get("role_alignment") or {}).get("alignment_score", "-")
    dossier = (result.get("dossier") or {}).get("weighted_score", "-")

    entry = f"{timestamp} | {score:5.1f} | G:{ghost:<4} R:{redflag:<4} A:{role_align:<4} D:{dossier:<4} | {source}\n"

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        pass


# ── batch ────────────────────────────────────────────────────────────


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--threshold", default=75, type=int, help="Min overall score for detailed output (default: 75).")
def batch(file: str, threshold: int) -> None:
    """Batch recon: scan a file of URLs and output a scores table.

    FILE should contain one job posting URL per line.
    Lines starting with # are ignored.

    Outputs {stem}_results.txt (scores table) and
    {stem}_results_top.txt (details for postings scoring above threshold).
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

    try:
        prof = load_profile()
    except ProfileError as e:
        print_error(f"Profile error: {e}")
        return

    print_banner()
    section_header("BATCH RECON")

    # Count URLs for progress display
    input_path = Path(file)
    url_lines = [
        line.strip()
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    total = len(url_lines)

    if total == 0:
        print_error("No URLs found in file.")
        return

    print_info(f"Loaded {total} URLs from {input_path.name}")
    print_info(f"Threshold for detailed output: {threshold}")
    console.print()

    # Progress tracking
    current_url = ""

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning...", total=total)

        def on_progress(current, count, url, status):
            nonlocal current_url
            current_url = url
            short_url = url if len(url) <= 50 else url[:47] + "..."
            if status == "scanning":
                progress.update(task, description=f"[{current}/{count}] {short_url}")
            elif status == "done":
                progress.update(task, advance=1)

        summary = run_batch(str(input_path), threshold, prof, on_progress=on_progress)

    console.print()

    # Display summary
    above = summary["above_threshold"]
    errors = summary["errors"]

    print_success(f"Scanned {summary['total']} postings.")
    if above > 0:
        print_success(f"{above} scored above {threshold} - details in {Path(summary['top_path']).name}")
    else:
        print_info(f"No postings scored above {threshold}.")
    if errors > 0:
        print_warning(f"{errors} URL(s) failed - see results table for details.")

    print_info(f"Results: {summary['results_path']}")
    if summary.get("top_path"):
        print_info(f"Top picks: {summary['top_path']}")


def _display_ghostbust_summary(ghost: dict) -> None:
    """Compact ghostbust display for the hunt pipeline."""
    from charon.output import print_score

    score = ghost["ghost_score"]
    console.print("[header]Ghost Likelihood[/header]")
    print_score("Score", score)
    console.print(f"  Confidence: [info]{ghost['confidence'].upper()}[/info]")

    # Show all signals grouped by severity
    signals = ghost.get("signals", [])
    reds = [s for s in signals if s["severity"] == "red"]
    yellows = [s for s in signals if s["severity"] == "yellow"]
    greens = [s for s in signals if s["severity"] == "green"]
    if reds:
        console.print()
        for s in reds:
            console.print(f"  [danger][X][/danger] {s['category']}: {s['finding']}")
    if yellows:
        console.print()
        for s in yellows:
            console.print(f"  [warning][!][/warning] {s['category']}: {s['finding']}")
    if greens:
        console.print()
        for s in greens:
            console.print(f"  [good][+][/good] {s['category']}: {s['finding']}")
    console.print()


def _display_redflags_summary(redflag: dict) -> None:
    """Compact redflags display for the hunt pipeline."""
    from charon.output import print_score

    score = redflag["redflag_score"]
    console.print("[header]Red Flag Score[/header]")
    print_score("Score", score)

    # Dealbreakers - show each one
    dealbreakers = redflag.get("dealbreakers_found", [])
    if dealbreakers:
        console.print()
        for d in dealbreakers:
            console.print(f"  [danger][X] {d['flag']}[/danger]")
            if d.get("evidence"):
                console.print(f"      [dim]\"{d['evidence']}\"[/dim]")
            if d.get("interpretation"):
                console.print(f"      [italic]→ {d['interpretation']}[/italic]")

    # Yellow flags - show each one
    yellows = redflag.get("yellow_flags_found", [])
    if yellows:
        console.print()
        for y in yellows:
            console.print(f"  [warning][!] {y['flag']}[/warning]")
            if y.get("evidence"):
                console.print(f"      [dim]\"{y['evidence']}\"[/dim]")
            if y.get("interpretation"):
                console.print(f"      [italic]→ {y['interpretation']}[/italic]")

    # Green flags - show each one
    greens = redflag.get("green_flags_found", [])
    if greens:
        console.print()
        for g in greens:
            console.print(f"  [good][+] {g['flag']}[/good]")
            if g.get("evidence"):
                console.print(f"      [dim]\"{g['evidence']}\"[/dim]")

    if not dealbreakers and not yellows and not greens:
        console.print()
        print_info("No flags detected.")
    console.print()


def _display_dossier_summary(dossier_result: dict, prof: dict) -> None:
    """Compact dossier display for the hunt pipeline."""
    from charon.output import print_score_inverted

    company = dossier_result.get("company", "Unknown")
    weighted = dossier_result.get("weighted_score", 0)

    console.print(f"[header]{company}[/header]")
    print_score_inverted("Values Alignment", weighted)
    console.print()

    # Dimension scores with assessment
    dims = dossier_result.get("dimensions", {})
    for dim_name in ("security_culture", "people_treatment", "leadership_transparency", "work_life_balance", "compensation", "financial_health"):
        dim = dims.get(dim_name, {})
        label = dim_name.replace("_", " ").title()
        score = dim.get("score", 0)
        if score >= 70:
            style = "good"
        elif score >= 40:
            style = "warning"
        else:
            style = "danger"
        console.print(f"    [{style}]{label:<28} {score:.0f}/100[/{style}]")
        assessment = dim.get("assessment", "")
        if assessment:
            console.print(f"      [dim]{assessment}[/dim]")
    console.print()


def _display_role_alignment_summary(role_align: dict) -> None:
    """Display role alignment results in the hunt pipeline."""
    from charon.output import print_score_inverted

    score = role_align.get("alignment_score", 0)
    closest = role_align.get("closest_target")

    console.print("[header]Role Alignment[/header]")
    print_score_inverted("Match", score)
    if closest:
        console.print(f"  Closest target: [info]{closest}[/info]")
    console.print()

    # Overlapping skills
    overlap = role_align.get("overlap", [])
    if overlap:
        console.print("  [good]Overlap with your targets:[/good]")
        for item in overlap:
            console.print(f"    [good][+][/good] {item}")
        console.print()

    # Gaps
    gaps = role_align.get("gaps", [])
    if gaps:
        console.print("  [warning]Missing from your targets:[/warning]")
        for item in gaps:
            console.print(f"    [warning][-][/warning] {item}")
        console.print()

    # Stepping stone?
    stepping = role_align.get("stepping_stone", False)
    if stepping:
        console.print("  [info]Stepping stone: Yes - could lead toward your target roles[/info]")
    else:
        console.print("  [warning]Stepping stone: No - unlikely to move you toward your targets[/warning]")
    console.print()

    # Assessment
    assessment = role_align.get("assessment", "")
    if assessment:
        panel("Role Fit", assessment, "info")
        console.print()


def _display_hunt_detail(result: dict, prof: dict) -> None:
    """Interactive drill-down into hunt results."""
    while True:
        console.print()
        parts = []
        if result.get("ghostbust"):
            parts.append("(g)host signals")
        if result.get("redflags"):
            parts.append("(r)ed flags")
        if result.get("role_alignment"):
            parts.append("ro(l)e alignment")
        if result.get("dossier"):
            parts.append("(d)ossier evidence")
        parts.append("(q)uit")

        prompt_text = f"  View details: {' / '.join(parts)}"
        console.print(prompt_text)
        choice = click.getchar()
        console.print()

        if choice in ("g", "G") and result.get("ghostbust"):
            _display_ghostbust(result["ghostbust"])
        elif choice in ("r", "R") and result.get("redflags"):
            _display_redflags(result["redflags"])
        elif choice in ("l", "L") and result.get("role_alignment"):
            _display_role_alignment_summary(result["role_alignment"])
        elif choice in ("d", "D") and result.get("dossier"):
            _display_dossier(result["dossier"], prof)
        elif choice in ("q", "Q", "\r", "\n"):
            break
        else:
            continue


def _compute_hunt_score(result: dict) -> float:
    """Compute a combined hunt score (0-100, higher is better)."""
    scores = []

    ghost = result.get("ghostbust")
    if ghost:
        # Invert ghost score (low ghost = good)
        scores.append(100 - ghost["ghost_score"])

    redflag = result.get("redflags")
    if redflag:
        # Invert redflag score (low flags = good)
        scores.append(100 - redflag["redflag_score"])

    role_align = result.get("role_alignment")
    if role_align:
        scores.append(role_align.get("alignment_score", 50))

    dossier_result = result.get("dossier")
    if dossier_result:
        scores.append(dossier_result.get("weighted_score", 50))

    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 1)


def _display_hunt_verdict(result: dict) -> None:
    """Display the combined hunt verdict."""
    score = _compute_hunt_score(result)

    section_header("COMBINED VERDICT")

    from charon.output import print_score_inverted
    console.print("[header]Worth Applying?[/header]")
    print_score_inverted("Score", score)
    console.print()

    ghost = result.get("ghostbust", {})
    redflag = result.get("redflags", {})
    dossier_result = result.get("dossier")

    # Build verdict text
    parts = []

    ghost_score = ghost.get("ghost_score", 0)
    if ghost_score <= 25:
        parts.append("Posting appears genuine.")
    elif ghost_score <= 50:
        parts.append("Some ghost job concerns, but likely real.")
    else:
        parts.append(f"Ghost risk is elevated ({ghost_score}%).")

    dealbreakers = redflag.get("dealbreakers_found", [])
    if dealbreakers:
        parts.append(f"{len(dealbreakers)} dealbreaker(s) detected.")
    elif redflag.get("redflag_score", 0) <= 25:
        parts.append("No major red flags.")

    role_align = result.get("role_alignment")
    if role_align:
        role_score = role_align.get("alignment_score", 0)
        closest = role_align.get("closest_target")
        stepping = role_align.get("stepping_stone", False)
        if role_score >= 70:
            parts.append(f"Strong role alignment ({role_score}%).")
        elif role_score >= 40:
            if stepping:
                parts.append(f"Partial role fit ({role_score}%), but could be a stepping stone.")
            else:
                parts.append(f"Partial role fit ({role_score}%) - not your target, and may not lead there.")
        else:
            if stepping:
                parts.append(f"Weak role fit ({role_score}%), though it could still open doors.")
            else:
                parts.append(f"Poor role fit ({role_score}%) - this won't move you toward your goals.")

    if dossier_result:
        weighted = dossier_result.get("weighted_score", 0)
        company = dossier_result.get("company", "The company")
        if weighted >= 70:
            parts.append(f"{company} aligns well with your values ({weighted}/100).")
        elif weighted >= 40:
            parts.append(f"{company} has mixed alignment ({weighted}/100).")
        else:
            parts.append(f"{company} scores poorly on your values ({weighted}/100).")

    verdict_text = " ".join(parts)

    if score >= 70:
        style = "good"
        recommendation = "Worth applying. The ferryman gives his blessing."
    elif score >= 45:
        style = "warning"
        recommendation = "Proceed with caution. Research further before committing."
    else:
        style = "danger"
        recommendation = "The ferryman advises against this crossing."

    panel("Assessment", f"{verdict_text}\n\n[{style}]{recommendation}[/{style}]", style)


@cli.command()
@click.option("--add", help="Add a company to your watchlist.")
@click.option("--list", "list_watch", is_flag=True, help="Show your watchlist.")
@click.option("--remove", help="Remove a company from your watchlist.")
def watch(add: str | None, list_watch: bool, remove: str | None) -> None:
    """Watch companies for new postings. Patience is a virtue of the dead."""
    if not any([add, list_watch, remove]):
        list_watch = True  # default action

    if add:
        add_watch(add)
        print_success(f"Added '{add}' to watchlist. The ferryman is watching.")
        return

    if remove:
        if remove_watch(remove):
            print_success(f"Removed '{remove}' from watchlist.")
        else:
            print_warning(f"'{remove}' was not on the watchlist.")
        return

    if list_watch:
        companies = get_watchlist()
        if not companies:
            print_info("Watchlist is empty. Add companies with: charon watch --add <name>")
            return

        table = Table(title="Watchlist", border_style="dim", header_style="bold white")
        table.add_column("Company", style="info", min_width=20)
        table.add_column("Added", width=20)
        table.add_column("Notes", max_width=30)

        for entry in companies:
            added = entry.get("added_at", "")[:10]
            table.add_row(
                entry["company"],
                added,
                entry.get("notes") or "-",
            )

        console.print(table)
        console.print(f"\n  [dim]{len(companies)} companies watched[/dim]")


@cli.command()
@click.option("--open", "open_file", is_flag=True, help="Open the log in your default text editor.")
@click.option("--sort", "sort_by", type=click.Choice(["score", "date"]), default="date", help="Sort entries.")
@click.option("--days", type=int, default=None, help="Only show entries from the last N days.")
def toll(open_file: bool, sort_by: str, days: int | None) -> None:
    """View the hunt log. Every crossing has a price."""
    log_path = Path.home() / ".charon" / "hunt_log.txt"
    if not log_path.exists():
        print_info("No tolls collected yet. Run 'charon hunt' to start.")
        return

    content = log_path.read_text(encoding="utf-8")
    if not content.strip():
        print_info("The toll ledger is empty. No crossings recorded.")
        return

    if open_file:
        click.launch(str(log_path))
        print_info(f"Opened: {log_path}")
        return

    # Parse entries (each entry is 2 lines: data + url)
    lines = content.strip().split("\n")
    entries = []
    i = 0
    while i < len(lines):
        data_line = lines[i]
        url_line = lines[i + 1] if i + 1 < len(lines) else ""
        i += 2

        # Parse: "2026-03-10 02:01 | 78.3 | G:15   R:35   A:85   D:-"
        parts = data_line.split("|")
        if len(parts) < 2:
            continue
        timestamp = parts[0].strip()
        try:
            score = float(parts[1].strip())
        except (ValueError, IndexError):
            score = 0.0
        scores_part = parts[2].strip() if len(parts) > 2 else ""

        entries.append({
            "timestamp": timestamp,
            "score": score,
            "scores": scores_part,
            "url": url_line.strip(),
        })

    # Filter by days
    if days is not None:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M")
        entries = [e for e in entries if e["timestamp"] >= cutoff_str]

    if not entries:
        print_info(f"No entries in the last {days} day(s).")
        return

    # Sort
    if sort_by == "score":
        entries.sort(key=lambda e: e["score"], reverse=True)

    print_banner()
    label = f"THE TOLL"
    if days:
        label += f" (last {days} day{'s' if days != 1 else ''})"
    if sort_by == "score":
        label += " — sorted by score"
    section_header(label)

    for e in entries:
        score = e["score"]
        if score >= 70:
            style = "good"
        elif score >= 40:
            style = "warning"
        else:
            style = "danger"
        console.print(f"  [{style}]{e['timestamp']} | {score:5.1f}[/{style}] | {e['scores']}")
        console.print(f"    [dim]{e['url']}[/dim]")

    console.print()
    console.print(f"  [dim]{len(entries)} entries | Log: {log_path}[/dim]")


@cli.command()
@click.option("--send", is_flag=True, help="Send the daily digest now.")
@click.option("--preview", is_flag=True, help="Preview digest without sending.")
def digest(send: bool, preview: bool) -> None:
    """Daily email digest. The ferryman's morning report."""
    if not any([send, preview]):
        preview = True  # default action

    if preview:
        body = preview_digest()
        if not body:
            print_info("Nothing to report. The river is quiet today.")
            return
        console.print()
        console.print(body)
        return

    if send:
        try:
            prof = load_profile()
        except ProfileError as e:
            print_error(f"Profile error: {e}")
            return

        # Check if there's anything to send
        body = preview_digest()
        if not body:
            print_info("Nothing to report. No digest sent.")
            return

        try:
            sent = send_digest(prof)
            if sent:
                print_success("Digest sent. The ferryman's report is delivered.")
            else:
                print_info("Nothing to send.")
        except DigestError as e:
            print_error(str(e))


@cli.command("apply")
@click.option("--add", is_flag=True, help="Track a new application.")
@click.option("--company", help="Company name.")
@click.option("--role", help="Role/position title.")
@click.option("--url", "app_url", help="Job posting URL.")
@click.option("--notes", help="Notes about the application.")
@click.option("--list", "list_apps", is_flag=True, help="List tracked applications.")
@click.option("--status", help="Filter by status or update status (with --id).")
@click.option("--id", "app_id", type=int, help="Application ID for status update.")
@click.option("--remove", "remove_id", type=int, help="Remove an application by ID.")
@click.option("--ghost-check", is_flag=True, help="Check for ghosted applications.")
@click.option("--stats", is_flag=True, help="Show application statistics.")
def apply_cmd(
    add: bool,
    company: str | None,
    role: str | None,
    app_url: str | None,
    notes: str | None,
    list_apps: bool,
    status: str | None,
    app_id: int | None,
    remove_id: int | None,
    ghost_check: bool,
    stats: bool,
) -> None:
    """Track job applications. The ferryman keeps a ledger."""
    # Determine action
    if not any([add, list_apps, ghost_check, stats, app_id, remove_id]):
        list_apps = True

    if remove_id:
        from charon.db import delete_application, get_application
        app = get_application(remove_id)
        if not app:
            print_error(f"No application with ID {remove_id}.")
            return
        if delete_application(remove_id):
            print_success(f"Removed #{remove_id}: {app['company']} - {app['role']}")
        else:
            print_error(f"Failed to remove application #{remove_id}.")
        return

    if add:
        if not company:
            print_error("--company is required when adding an application.")
            return
        if not role:
            print_error("--role is required when adding an application.")
            return

        try:
            app = track_application(company, role, url=app_url, notes=notes)
        except ApplyError as e:
            print_error(str(e))
            return

        print_success(f"Application #{app['id']} tracked: {company} - {role}")
        if app.get("email_domain"):
            print_info(f"Email domain detected: {app['email_domain']}")
        return

    if app_id and status:
        try:
            app = update_status(app_id, status)
        except ApplyError as e:
            print_error(str(e))
            return

        if app:
            print_success(f"Application #{app_id} updated: {app['company']} -> {status}")
            if status == "interviewing" and not app.get("dossier_at"):
                print_warning(
                    f"No dossier on file for {app['company']}. "
                    f"Run: charon dossier --company \"{app['company']}\""
                )
        else:
            print_error(f"Application #{app_id} not found.")
        return

    if ghost_check:
        try:
            prof = load_profile()
        except ProfileError as e:
            print_error(f"Profile error: {e}")
            return

        days = prof.get("applications", {}).get("ghosted_after_days", 21)
        ghosted = check_ghosted(days)

        if ghosted:
            print_warning(f"Marked {len(ghosted)} application(s) as ghosted ({days}+ days):")
            for app in ghosted:
                console.print(f"  [danger][X][/danger] {app['company']} - {app['role']} (applied {app['applied_at'][:10]})")
        else:
            print_info("No ghosted applications detected. Patience, mortal.")
        return

    if stats:
        stat_data = get_stats()
        if not stat_data:
            print_info("No applications tracked yet.")
            return

        section_header("APPLICATION STATS")
        total = sum(stat_data.values())
        for s, count in sorted(stat_data.items()):
            style = {
                "applied": "info",
                "responded": "good",
                "interviewing": "good",
                "offered": "good",
                "rejected": "danger",
                "ghosted": "warning",
            }.get(s, "dim")
            console.print(f"  [{style}]{s:<15} {count}[/{style}]")
        console.print(f"  [header]{'total':<15} {total}[/header]")
        return

    if list_apps:
        try:
            apps = list_applications(status)
        except ApplyError as e:
            print_error(str(e))
            return

        if not apps:
            if status:
                print_info(f"No applications with status '{status}'.")
            else:
                print_info("No applications tracked yet. Add one with: charon apply --add --company <name> --role <role>")
            return

        table = Table(title="Applications", border_style="dim", header_style="bold white")
        table.add_column("ID", style="dim", width=4)
        table.add_column("Company", style="info", min_width=15)
        table.add_column("Role", min_width=20)
        table.add_column("Status", width=12)
        table.add_column("D", width=1, justify="center")
        table.add_column("Applied", width=12)
        table.add_column("Updated", width=12)
        table.add_column("Notes", max_width=20)

        status_style = {
            "applied": "info",
            "responded": "good",
            "interviewing": "good",
            "offered": "good",
            "rejected": "danger",
            "ghosted": "warning",
        }

        for app in apps:
            s = app.get("status", "applied")
            style = status_style.get(s, "dim")
            dossier_marker = "[good]D[/good]" if app.get("dossier_at") else "[dim]-[/dim]"
            table.add_row(
                str(app["id"]),
                app["company"],
                app["role"],
                f"[{style}]{s}[/{style}]",
                dossier_marker,
                app.get("applied_at", "")[:10],
                app.get("updated_at", "")[:10],
                app.get("notes") or "-",
            )

        console.print(table)
        console.print(f"\n  [dim]{len(apps)} application(s)[/dim]")


@cli.command("inbox")
@click.option("--scan", is_flag=True, help="Scan inbox for application responses.")
@click.option("--setup", is_flag=True, help="Show IMAP setup instructions.")
@click.option("--status", "show_status", is_flag=True, help="Show inbox connection status.")
@click.option("--days", default=7, help="How many days back to scan.")
def inbox_cmd(scan: bool, setup: bool, show_status: bool, days: int) -> None:
    """Monitor your inbox for application responses. The dead check their email."""
    from charon.inbox import scan_inbox, CLASSIFICATION_TO_STATUS

    if not any([scan, setup, show_status]):
        scan = True

    if setup:
        section_header("INBOX SETUP")
        console.print("  Charon monitors your email via IMAP for application responses.")
        console.print()
        console.print("  [header]1. Add accounts to ~/.charon/profile.yaml:[/header]")
        console.print()
        console.print("     inbox:")
        console.print("       accounts:")
        console.print("         - name: gmail")
        console.print("           imap_server: imap.gmail.com")
        console.print("           imap_user: you@gmail.com")
        console.print()
        console.print("  [header]2. Store passwords in Vault or env vars:[/header]")
        console.print()
        console.print("     Vault: secret/<prefix>/imap-gmail  key: password")
        console.print("     Env:   CHARON_IMAP_PASS_GMAIL")
        console.print()
        console.print("  [header]3. For Gmail, generate an App Password:[/header]")
        console.print()
        console.print("     https://myaccount.google.com/apppasswords")
        console.print("     (requires 2FA enabled)")
        console.print()
        console.print("  [header]4. Test connection:[/header]")
        console.print()
        console.print("     charon inbox --status")
        return

    try:
        prof = load_profile()
    except ProfileError as e:
        print_error(f"Profile error: {e}")
        return

    if show_status:
        from charon.inbox import _connect_imap
        from charon.db import get_applications

        inbox_config = prof.get("inbox", {})
        accounts = inbox_config.get("accounts", [])

        if not accounts:
            print_warning("No inbox accounts configured. Run: charon inbox --setup")
            return

        section_header("INBOX STATUS")

        for account in accounts:
            name = account.get("name", "unknown")
            user = account.get("imap_user", "?")
            server = account.get("imap_server", "?")
            console.print(f"  [header]{name}[/header] ({user} @ {server})")

            try:
                conn = _connect_imap(account, prof)
                conn.select("INBOX", readonly=True)
                status, data = conn.search(None, "ALL")
                count = len(data[0].split()) if status == "OK" and data[0] else 0
                conn.logout()
                print_success(f"    Connected. {count} messages in inbox.")
            except Exception as e:
                print_error(f"    Connection failed: {e}")
            console.print()

        # Show active application count
        active = 0
        for s in ["applied", "responded", "interviewing"]:
            active += len(get_applications(s))
        console.print(f"  [info]Active applications being monitored: {active}[/info]")
        return

    if scan:
        print_info(f"Scanning inbox (last {days} days)...")
        try:
            results = scan_inbox(prof, days=days)
        except InboxError as e:
            print_error(str(e))
            return

        if not results:
            print_info("No application responses found. Silence from the living.")
            return

        section_header("RESPONSES FOUND")
        for result in results:
            cls = result["classification"]
            eml = result["email"]
            cls_type = cls.get("classification", "other")

            type_style = {
                "interview": "good",
                "offer": "good",
                "rejection": "danger",
                "acknowledgment": "info",
            }.get(cls_type, "dim")

            company = cls.get("company_match") or "Unknown"
            account = eml.get("account", "")
            acct_tag = f" [{account}]" if account else ""

            # Show auto-status update if it happened
            new_status = CLASSIFICATION_TO_STATUS.get(cls_type)
            status_note = f" -> auto-updated to {new_status}" if new_status else ""

            console.print(
                f"  [{type_style}][{cls_type.upper()}][/{type_style}] "
                f"{company}: {cls.get('summary', eml['subject'])}{acct_tag}"
            )
            if status_note:
                console.print(f"    [dim]{status_note}[/dim]")
            console.print(f"    [dim]From: {eml['from']}[/dim]")
            console.print(f"    [dim]Date: {eml['date']}[/dim]")
            console.print()

        print_success(f"Found {len(results)} response(s). Queued for digest.")


@cli.command("gather")
@click.option("--ats", help="Limit to one ATS (e.g. greenhouse, lever, ashby, workday).")
@click.option("--slug", help="Limit to one employer slug from companies.yaml.")
@click.option("--list", "list_employers_flag", is_flag=True, help="List configured employers grouped by ATS.")
@click.option("--dry-run", is_flag=True, help="Preview what would be discovered without writing to DB.")
@click.option("--rate-limit", type=float, default=DEFAULT_RATE_LIMIT_SECONDS,
              help=f"Seconds between employer fetches (default: {DEFAULT_RATE_LIMIT_SECONDS}).")
def gather_cmd(
    ats: str | None,
    slug: str | None,
    list_employers_flag: bool,
    dry_run: bool,
    rate_limit: float,
) -> None:
    """Gather job postings from configured employers. Souls at the riverbank."""
    try:
        registry = load_registry()
    except GatherError as e:
        print_error(str(e))
        return

    if list_employers_flag:
        section_header("CONFIGURED EMPLOYERS")
        for ats_name, entries in registry.items():
            if not isinstance(entries, list) or not entries:
                continue
            console.print(f"\n  [header]{ats_name}[/header] ({len(entries)} employers)")
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                tier = entry.get("tier", "")
                category = entry.get("category", "")
                tag = f"[dim]{tier}/{category}[/dim]" if tier or category else ""
                console.print(f"    [info]{entry.get('slug', '?'):<24}[/info] {entry.get('name', '?'):<28} {tag}")
        total = sum(len(v) for v in registry.values() if isinstance(v, list))
        console.print(f"\n  [dim]{total} total employers across {len(registry)} ATS platforms[/dim]")
        return

    pairs = list_employers(registry, ats=ats)
    if slug:
        pairs = [(a, e) for a, e in pairs if e.get("slug") == slug]

    if not pairs:
        scope = []
        if ats:
            scope.append(f"ats={ats}")
        if slug:
            scope.append(f"slug={slug}")
        if scope:
            print_error(f"No employers in registry match {' '.join(scope)}.")
        else:
            print_error("Registry is empty.")
        return

    print_banner()
    section_header("GATHER")
    label = "DRY RUN" if dry_run else "LIVE"
    print_info(f"[{label}] Polling {len(pairs)} employer(s)...")
    if rate_limit > 0:
        print_info(f"Rate limit: {rate_limit}s between employers")
    console.print()

    summaries: list[dict] = []

    def on_progress(summary: dict) -> None:
        summaries.append(summary)
        slug_disp = summary["slug"]
        name = summary["name"]
        ats_name = summary["ats"]

        if summary.get("error"):
            console.print(f"  [danger][X][/danger] {ats_name}/{slug_disp:<22} {name}")
            console.print(f"      [dim]{summary['error']}[/dim]")
            return

        if summary.get("skipped") == -1:
            console.print(f"  [dim][~] {ats_name}/{slug_disp:<22} {name} (in applications, skipped)[/dim]")
            return

        new = summary["new"]
        dupes = summary["dupes"]
        fetched = summary["fetched"]
        skipped = max(0, summary.get("skipped", 0))

        if new > 0:
            style = "good"
            marker = "[+]"
        elif fetched == 0:
            style = "dim"
            marker = "[ ]"
        else:
            style = "info"
            marker = "[=]"

        line = (
            f"  [{style}]{marker}[/{style}] {ats_name}/{slug_disp:<22} "
            f"{name:<28} "
            f"[good]+{new}[/good] new / "
            f"[dim]{dupes} dupes[/dim] / "
            f"{fetched} total"
        )
        if skipped:
            line += f" [warning]({skipped} skipped)[/warning]"
        console.print(line)

    try:
        gather_registry(
            ats=ats,
            slug=slug,
            dry_run=dry_run,
            rate_limit_seconds=rate_limit,
            on_progress=on_progress,
        )
    except GatherError as e:
        print_error(str(e))
        return
    except KeyboardInterrupt:
        print_warning("Interrupted. Partial results may have been written.")
        return

    console.print()
    section_header("GATHER SUMMARY")
    total_fetched = sum(s["fetched"] for s in summaries)
    total_new = sum(s["new"] for s in summaries)
    total_dupes = sum(s["dupes"] for s in summaries)
    errors = sum(1 for s in summaries if s.get("error"))
    employer_skips = sum(1 for s in summaries if s.get("skipped") == -1)

    console.print(f"  [good]New discoveries:[/good]  {total_new}")
    console.print(f"  [info]Already known:[/info]    {total_dupes}")
    console.print(f"  [dim]Total fetched:[/dim]    {total_fetched}")
    if employer_skips:
        console.print(f"  [warning]Employers skipped:[/warning] {employer_skips} (in applications)")
    if errors:
        console.print(f"  [danger]Errors:[/danger]           {errors}")

    if dry_run:
        console.print()
        print_info("Dry run - no rows were written to the discoveries table.")


@cli.command("daily")
@click.option("--dry-run", is_flag=True, help="Preview what would happen without sending.")
def daily(dry_run: bool) -> None:
    """Run the daily routine: scan inbox, check ghosts, send digest."""
    from charon.inbox import scan_inbox

    try:
        prof = load_profile()
    except ProfileError as e:
        print_error(f"Profile error: {e}")
        return

    section_header("DAILY ROUTINE")

    # Step 1: Inbox scan
    inbox_config = prof.get("inbox", {})
    accounts = inbox_config.get("accounts", [])
    if accounts:
        print_info("Step 1/3: Scanning inbox...")
        try:
            results = scan_inbox(prof, days=7)
            if results:
                print_success(f"  Found {len(results)} response(s).")
                for r in results:
                    cls = r["classification"]
                    cls_type = cls.get("classification", "other")
                    company = cls.get("company_match") or "Unknown"
                    console.print(f"    [{cls_type.upper()}] {company}: {cls.get('summary', '?')}")
            else:
                print_info("  No responses found.")
        except InboxError as e:
            print_warning(f"  Inbox scan failed: {e}")
    else:
        print_info("Step 1/3: Inbox scan skipped (no accounts configured).")

    # Step 2: Ghost check
    print_info("Step 2/3: Checking for ghosted applications...")
    days_threshold = prof.get("applications", {}).get("ghosted_after_days", 21)
    try:
        ghosted = check_ghosted(days_threshold)
        if ghosted:
            print_warning(f"  Marked {len(ghosted)} application(s) as ghosted:")
            for app in ghosted:
                console.print(f"    [danger][X][/danger] {app['company']} - {app['role']}")
        else:
            print_info("  No ghosted applications.")
    except ApplyError as e:
        print_warning(f"  Ghost check failed: {e}")

    # Step 3: Digest
    if dry_run:
        print_info("Step 3/3: Digest preview (dry run):")
        body = preview_digest()
        if body:
            console.print()
            console.print(body)
        else:
            print_info("  Nothing to report.")
    else:
        print_info("Step 3/3: Sending digest...")
        notif = prof.get("notifications", {})
        if not notif.get("enabled", False):
            print_info("  Digest not sent (notifications disabled in profile).")
        else:
            try:
                sent = send_digest(prof)
                if sent:
                    print_success("  Digest sent.")
                else:
                    print_info("  Nothing to report. No digest sent.")
            except DigestError as e:
                print_warning(f"  Digest send failed: {e}")

    console.print()
    print_success("Daily routine complete.")


if __name__ == "__main__":
    cli()
