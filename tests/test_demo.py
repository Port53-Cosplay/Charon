"""The public demo (demo/): it builds, it answers every API the page calls,
and nothing personal reaches it."""

import base64
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "demo"
MANIFEST = REPO / "charon" / "templates" / "manifest.html"

sys.path.insert(0, str(DEMO))

import build_demo  # noqa: E402


def _routes() -> list[tuple[str, str]]:
    shim = (DEMO / "shim.js").read_text(encoding="utf-8")
    return re.findall(r'\["(GET|POST) (/api/[^"]*)"', shim)


def _page_paths() -> set[str]:
    """Every /api path the page names, cut off where a template value starts."""
    html = MANIFEST.read_text(encoding="utf-8")
    return set(re.findall(r"['\"`](/api/[A-Za-z0-9_/.-]*)", html))


def _covered(path: str, routes: list[tuple[str, str]]) -> bool:
    for _, pattern in routes:
        static = pattern.split(":", 1)[0]
        if pattern == path or (path.endswith("/") and static.startswith(path) and ":" in pattern):
            return True
    return False


def test_shim_answers_every_api_the_page_calls():
    routes = _routes()
    assert routes, "no ROUTES found in shim.js"
    missing = sorted(p for p in _page_paths() if not _covered(p, routes))
    assert not missing, f"demo/shim.js has no route for: {missing}"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo") / "charon-demo.html"
    summary = build_demo.build(out, resize_images=False)
    html = out.read_text(encoding="utf-8")
    m = re.search(r"window\.__CHARON_DEMO__ = (\{.*?\});</script>", html, re.S)
    assert m, "embedded demo data not found"
    return summary, html, json.loads(m.group(1).replace("<\\/", "</"))


def test_build_produces_the_opening_state(built):
    summary, _, data = built
    assert summary["ready"] == 6
    ready = data["opening"]["ready"]
    # Shapes come from the real payload builder.
    assert {"letter_file", "prep_building", "company_contacts", "dossier"} <= set(ready[0])
    prepped = [d for d in ready if d["has_letter"]]
    assert [d["company"] for d in prepped] == ["Aegis Cloud Security"]
    assert prepped[0]["letter_file"] == "cover_letter.docx"
    assert data["opening"]["archived_hidden"] == 3


def test_every_card_without_a_letter_can_be_prepped(built):
    _, _, data = built
    waiting = [d for d in data["opening"]["ready"] if not d["has_letter"]]
    waiting += data["reveal"]["judged_ready"]
    for d in waiting:
        assert str(d["id"]) in data["reveal"]["prep"]
        assert str(d["id"]) in data["letters"]
    greetings = {d["company"]: data["reveal"]["prep"][str(d["id"])]["greeting"] for d in waiting}
    assert greetings["Halcyon Grid"] == "Dear Quinn Albright,"  # from the demo's contacts search
    assert greetings["Lanternfish Security"] == "Dear Lanternfish Security Team,"


def test_letters_are_real_docx_for_the_sample_applicant(built):
    _, _, data = built
    for letter in data["letters"].values():
        raw = base64.b64decode(letter["b64"])
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            body = z.read("word/document.xml").decode("utf-8")
            meta = z.read("docProps/core.xml").decode("utf-8")
        assert "Sample Applicant" in body
        for token in build_demo.FORBIDDEN:
            assert token not in (body + meta).lower()
        assert letter["filename"].startswith("Sample Applicant - ")


def test_nothing_personal_reaches_the_page(built):
    _, html, _ = built
    lowered = html.lower()
    for token in build_demo.FORBIDDEN:
        assert token not in lowered, token
    # Temp paths (which carry the builder's username) were rewritten.
    assert "/demo/offerings/" in html
    assert "appdata" not in lowered and "/tmp/" not in lowered


def test_stats_overrides_name_real_keys(built):
    _, _, data = built
    stats = data["opening"]["stats"]
    assert stats["gathered"] == 18412
    assert {s["key"] for s in stats["funnel"]} >= {"gathered", "judged", "ready"}
