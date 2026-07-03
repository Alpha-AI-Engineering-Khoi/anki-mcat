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


# --- lower-order list generators (scope / keywords / concepts) --------------
# These feed the "encode front-half" panels (Prime / Connect / Build). AI does
# only this lower-order surfacing; the learner supplies the relationships and
# answers. Each has a deterministic offline fallback so it works with AI OFF.


def _terms(spans: list[dict], limit: int = 8) -> list[str]:
    """Salient defined terms from the source (offline), in reading order."""
    out: list[str] = []
    seen: set[str] = set()
    for span in spans:
        for sent in sentences(span["text"]):
            m = _DEFN.match(sent)
            if not m:
                continue
            term = m.group("term").strip().rstrip(",")
            key = term.lower()
            if key in seen or len(term.split()) > 5:
                continue
            seen.add(key)
            out.append(term)
            if len(out) >= limit:
                return out
    return out


def _live_list(kind: str, spans: list[dict], topic_name: str, n: int = 8) -> list[str]:
    """Ask OpenAI for a short list of items grounded in the source."""
    import openai

    client = openai.OpenAI(api_key=api_key())
    asks = {
        "scope": "the big-picture ideas to skim first (not memorizable details)",
        "keywords": "the key terms a learner should connect to their own life",
        "concepts": "the concepts to place in an outline map",
    }
    src = source_text(spans) if spans else topic_name
    prompt = (
        f"For the MCAT topic \u201c{topic_name}\u201d, list about {n} short items: "
        f"{asks.get(kind, 'key points')}. Base them ONLY on the SOURCE. "
        "Return JSON {\"items\":[\"..\"]}. Each item under 12 words.\n\nSOURCE:\n"
        + src
    )
    resp = client.chat.completions.create(
        model=os.environ.get("MCAT_OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    items = json.loads(resp.choices[0].message.content).get("items", [])
    return [str(x).strip() for x in items if str(x).strip()][:n]


def scope_list(spans: list[dict], topic_name: str, live: bool | None = None) -> list[str]:
    """Big-picture 'skim' points for Prime. Offline: the lead clause of each
    source span; with no source, a generic skim scaffold from the topic name."""
    if live is None:
        live = ai_available()
    if live:
        try:
            return _live_list("scope", spans, topic_name)
        except Exception:
            pass
    out: list[str] = []
    for span in spans:
        sents = sentences(span["text"])
        if not sents:
            continue
        lead = re.split(r"(?<=[.;])\s", sents[0])[0].strip().rstrip(".")
        if len(lead) > 8:
            out.append(lead)
    if not out:
        out = [
            f"Skim {topic_name} end-to-end for the big picture.",
            f"See how the parts of {topic_name} fit together.",
            f"Note where {topic_name} shows up on the MCAT.",
            f"List what you do NOT yet understand about {topic_name}.",
        ]
    return out[:8]


def keyword_candidates(
    spans: list[dict], topic_name: str, live: bool | None = None
) -> list[str]:
    """Candidate keywords for Connect. AI-off fallback = the topic name."""
    if live is None:
        live = ai_available()
    if live:
        try:
            return _live_list("keywords", spans, topic_name)
        except Exception:
            pass
    return _terms(spans, limit=8) or [topic_name]


def concept_candidates(
    spans: list[dict], topic_name: str, live: bool | None = None
) -> list[str]:
    """Candidate concepts for Build. AI-off fallback = the topic name."""
    if live is None:
        live = ai_available()
    if live:
        try:
            return _live_list("concepts", spans, topic_name)
        except Exception:
            pass
    return _terms(spans, limit=10) or [topic_name]


def draft_overflow_card(
    detail: str, spans: list[dict], topic: str, live: bool | None = None
) -> dict:
    """Draft ONE flashcard for a detail the learner couldn't relate, linked to
    the best-matching source span (the Build -> Recall overflow bridge).

    ponytail: offline-only draft (the deterministic path). The learner edits the
    draft before it's added, so a bespoke single-card live prompt buys little;
    ceiling: no live drafting for overflow cards."""
    best_sent, best_score, span_id = "", 0.0, ""
    for span in spans:
        for sent in sentences(span["text"]):
            score = jaccard(detail, sent)
            if score > best_score:
                best_sent, best_score, span_id = sent, score, span["id"]
    term = detail.strip()
    verb = "are" if term.lower().endswith("s") else "is"
    back = ""
    if best_sent:
        back = re.split(r"(?<=[.;])\s", best_sent)[0].strip().rstrip(".") + "."
    if not span_id and spans:
        span_id = spans[0]["id"]
    return _card(f"What {verb} {term}?", back, topic, span_id, "overflow")


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

    # encode front-half generators (offline paths).
    scope = scope_list(spans, "Enzymes", live=False)
    assert len(scope) >= 3, scope
    kws = keyword_candidates(spans, "Enzymes", live=False)
    assert kws and all(isinstance(k, str) and k for k in kws), kws
    cons = concept_candidates(spans, "Enzymes", live=False)
    assert cons, cons
    # AI-off fallback with no source is the topic name.
    assert keyword_candidates([], "Kinematics", live=False) == ["Kinematics"]
    overflow = draft_overflow_card("cofactor", spans, topic, live=False)
    assert overflow["front"].lower().startswith("what") and overflow["back"]
    assert overflow["source_span"] in {s["id"] for s in spans}

    print(f"mcat_ai self-test OK: {len(spans)} spans, "
          f"{len(drafted)} drafted, {len(base)} baseline, "
          f"{len(scope)} scope, {len(kws)} keywords, {len(cons)} concepts, "
          f"ai_available={ai_available()}")


if __name__ == "__main__":
    _self_test()
