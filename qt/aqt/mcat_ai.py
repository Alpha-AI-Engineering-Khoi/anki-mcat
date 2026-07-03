# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""MCAT "Draft" pipeline: the lower-order AI work.

Given a bundled MCAT source document, Draft extracts terms and drafts candidate
flashcards, each linked to the exact source span it came from and tagged to one
of the 50 MCAT topics. This is the only place AI touches card *content*, and by
design it produces *candidates* a human accepts, edits, or rejects; it never
builds the learner's relationship map (see the BrainLift, SPOV 3).

Two modes:
- live: calls OpenAI (key from env or the repo .env) when the SDK + key exist.
- offline: a deterministic definitional extractor, so the pipeline and its eval
  run with AI switched OFF and in re-runnable tests with no network.

Pure logic + file reads only; no Qt here, so it is unit-testable. Run directly
for a self-check.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Iterable

DATA_DIR = pathlib.Path(__file__).parent / "mcat_data"
DEFAULT_SOURCE = DATA_DIR / "source_enzymes.md"

# --- text helpers (shared) --------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def sentences(text: str) -> list[str]:
    # naive but sufficient sentence split; keeps abbreviations like "e.g." intact
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z0-9])", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 15]


# --- source loading ---------------------------------------------------------


def load_source(path: str | os.PathLike | None = None) -> tuple[str, list[dict]]:
    """Return (topic, spans). Each span is {"id": "S1", "text": ...}."""
    p = pathlib.Path(path) if path else DEFAULT_SOURCE
    raw = p.read_text(encoding="utf-8")
    m = re.search(r"topic:\s*(MCAT::[^\s]+)", raw)
    topic = m.group(1) if m else "MCAT"
    body = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    spans: list[dict] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para or para.startswith("#"):
            continue
        spans.append({"id": f"S{len(spans) + 1}", "text": para})
    return topic, spans


def source_text(spans: Iterable[dict]) -> str:
    return "\n".join(s["text"] for s in spans)


# --- OpenAI key / availability ----------------------------------------------


def api_key() -> str | None:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"].strip()
    here = pathlib.Path(__file__).resolve()
    candidates = [par / ".env" for par in here.parents]
    for env in candidates:
        try:
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("OPENAI_API_KEY"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def ai_available() -> bool:
    if api_key() is None:
        return False
    try:
        import openai  # noqa: F401

        return True
    except ImportError:
        return False


# --- card construction ------------------------------------------------------


def _card(front: str, back: str, topic: str, span_id: str, origin: str,
          ctype: str = "basic") -> dict:
    return {
        "front": front.strip(),
        "back": back.strip(),
        "topic": topic,
        "source_span": span_id,
        "ctype": ctype,
        "origin": origin,
    }


# definitional patterns: "X is/are Y", "A/An/The X is Y", appositive "X, the Y,"
_DEFN = re.compile(
    r"^(?:A |An |The )?(?P<term>[A-Za-z][A-Za-z0-9 \-/]{2,40}?)\s+(?:is|are)\s+(?P<defn>.+)$"
)


def _offline_draft(spans: list[dict], topic: str) -> list[dict]:
    """Deterministic definitional extractor (AI-off fallback)."""
    cards: list[dict] = []
    seen: set[str] = set()
    for span in spans:
        for sent in sentences(span["text"]):
            m = _DEFN.match(sent)
            if not m:
                continue
            term = m.group("term").strip().rstrip(",")
            defn = m.group("defn").strip()
            # keep the definition to its first clause for a clean answer
            defn = re.split(r"(?<=[.;])\s", defn)[0].strip().rstrip(".")
            key = term.lower()
            # skip run-on sentences that define a second term (e.g. "X is an
            # apoenzyme, ... is a holoenzyme"), which make muddled cards
            if key in seen or len(term.split()) > 6 or len(defn) < 8 or \
                    re.search(r"\bis (a|an|the)\b", defn):
                continue
            seen.add(key)
            verb = "are" if term.lower().endswith("s") else "is"
            cards.append(_card(f"What {verb} {term}?", defn + ".", topic,
                               span["id"], "offline-draft"))
    return cards


def _live_draft(spans: list[dict], topic: str, n: int) -> list[dict]:
    """Call OpenAI to draft candidate cards, each linked to a source span."""
    import openai

    client = openai.OpenAI(api_key=api_key())
    numbered = "\n".join(f'[{s["id"]}] {s["text"]}' for s in spans)
    prompt = (
        "You draft MCAT flashcards ONLY from the numbered source below. "
        f"Make about {n} atomic cards. Each card tests ONE idea. "
        "Return JSON: {\"cards\":[{\"front\":..,\"back\":..,\"source_span\":\"S#\",\"ctype\":\"basic|cloze\"}]}. "
        "The source_span MUST be the [S#] the fact came from. Do not invent facts "
        "not in the source.\n\nSOURCE:\n" + numbered
    )
    resp = client.chat.completions.create(
        model=os.environ.get("MCAT_OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    data = json.loads(resp.choices[0].message.content)
    out: list[dict] = []
    valid_spans = {s["id"] for s in spans}
    for c in data.get("cards", []):
        span = c.get("source_span", "")
        if span not in valid_spans:
            span = spans[0]["id"]
        out.append(_card(c.get("front", ""), c.get("back", ""), topic, span,
                         "live-draft", c.get("ctype", "basic")))
    return out


def draft_cards(spans: list[dict], topic: str, n: int = 24,
                live: bool | None = None) -> list[dict]:
    """Draft candidate cards. Falls back to offline if AI is unavailable."""
    if live is None:
        live = ai_available()
    if live:
        try:
            return _live_draft(spans, topic, n)
        except Exception:
            pass  # AI-off: degrade gracefully to the deterministic path
    return _offline_draft(spans, topic)


def baseline_cards(spans: list[dict], topic: str) -> list[dict]:
    """A deliberately simpler generator (the baseline Draft must beat).

    Naive cloze: blank the longest word in each sentence and put the whole
    verbatim sentence on the back. Tends to make wordy, low-teaching cards.
    """
    cards: list[dict] = []
    for span in spans:
        for sent in sentences(span["text"]):
            words = re.findall(r"[A-Za-z][A-Za-z\-]{4,}", sent)
            if not words:
                continue
            target = max(words, key=len)
            front = "Fill in the blank: " + sent.replace(target, "_____", 1)
            cards.append(_card(front, sent, topic, span["id"], "baseline",
                               "cloze"))
    return cards


def _self_test() -> None:
    topic, spans = load_source()
    assert topic == "MCAT::BioBiochem::Enzymes", topic
    assert len(spans) >= 9, len(spans)
    drafted = draft_cards(spans, topic, live=False)
    assert len(drafted) >= 5, len(drafted)
    for c in drafted:
        assert c["source_span"] in {s["id"] for s in spans}
        assert c["topic"] == topic
    base = baseline_cards(spans, topic)
    assert len(base) >= 8
    print(f"mcat_ai self-test OK: {len(spans)} spans, "
          f"{len(drafted)} drafted, {len(base)} baseline, "
          f"ai_available={ai_available()}")


if __name__ == "__main__":
    _self_test()
