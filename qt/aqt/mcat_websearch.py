# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Live web-search grounding for the MCAT app (challenge 6, live path).

Grounds AI output in real, cited sources at call time via the OpenAI Responses
API ``web_search`` tool - FORCED (``tool_choice``) and domain-filtered to
Wikipedia + LibreTexts. Returns grounded text plus real ``url_citation`` sources
(title, url, char range): the "Check sources" (Perplexity-style) data.

Why forced: with ``tool_choice: auto`` the model may skip the search and
fabricate citations from memory; forcing it guarantees a real search and real
``url_citation`` annotations, which callers must verify rather than trust.

This is the LIVE path only (broad topic coverage + citations). The reproducible
eval (``mcat_eval``) deliberately stays on the fixed curated ``source_*.md``
docs, so this module is never imported there. Needs network + a key; callers
fall back to the offline scope cache when either is missing.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import unicodedata as _ud
import urllib.request as _urlreq
from urllib.parse import quote as _urlquote

# gpt-5.5 is OpenAI's recommended model for the hosted web_search tool (high /
# xhigh reasoning). Override via env; the interactive UI can pick a faster model
# or lower reasoning, while the offline cache build can use xhigh.
DEFAULT_MODEL = "gpt-5.5"
# Ground ONLY in these (subdomains included): open, LLM-permissible, high quality.
ALLOWED_DOMAINS = ["en.wikipedia.org", "libretexts.org"]
API_TIMEOUT = 120  # a forced web search + reasoning can take a while


def model() -> str:
    return (
        os.environ.get("MCAT_OPENAI_MODEL_WEBSEARCH")
        or os.environ.get("MCAT_OPENAI_MODEL")
        or DEFAULT_MODEL
    )


def _api_key() -> str | None:
    try:
        from aqt import mcat_ai  # in-app: reuse the repo-scoped key lookup
        return mcat_ai.api_key()
    except Exception:
        return os.environ.get("OPENAI_API_KEY")


def available() -> bool:
    """True only if a live web search could really run (same kill-switch rules
    as the rest of the AI: MCAT_OFFLINE / MCAT_AI_DISABLED / empty key force off)."""
    if os.environ.get("MCAT_OFFLINE") or os.environ.get("MCAT_AI_DISABLED"):
        return False
    if not ((_api_key() or "").strip()):
        return False
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


def ground(prompt: str, *, reasoning: str | None = "high",
           allowed_domains: list[str] | None = None) -> dict:
    """Force a domain-filtered web search and return grounded text + citations.

    Returns ``{"text", "citations": [{"title","url","start","end"}],
    "sources": [url,...], "searched": bool, "model"}``. Raises on any failure so
    the caller can fall back to the offline cache."""
    import openai

    client = openai.OpenAI(api_key=_api_key(), timeout=API_TIMEOUT)
    tool = {
        "type": "web_search",
        "filters": {"allowed_domains": allowed_domains or ALLOWED_DOMAINS},
    }
    kwargs: dict = dict(
        model=model(),
        input=prompt,
        tools=[tool],
        tool_choice={"type": "web_search"},  # force it; auto can fabricate cites
        include=["web_search_call.action.sources"],
    )
    if reasoning:
        kwargs["reasoning"] = {"effort": reasoning}
    resp = client.responses.create(**kwargs)
    return _parse(resp)


def _parse(resp) -> dict:  # type: ignore[no-untyped-def]
    text = getattr(resp, "output_text", "") or ""
    citations: list[dict] = []
    sources: list[str] = []
    searched = False
    for item in (getattr(resp, "output", None) or []):
        itype = getattr(item, "type", "") or ""
        if "web_search" in itype:
            searched = True
            action = getattr(item, "action", None)
            for s in (getattr(action, "sources", None) or []):
                url = getattr(s, "url", None) or (
                    s.get("url") if isinstance(s, dict) else None
                )
                if url:
                    sources.append(url)
        if itype == "message":
            for part in (getattr(item, "content", None) or []):
                for a in (getattr(part, "annotations", None) or []):
                    if getattr(a, "type", None) == "url_citation":
                        citations.append({
                            "title": getattr(a, "title", "") or "",
                            "url": getattr(a, "url", "") or "",
                            "start": getattr(a, "start_index", None),
                            "end": getattr(a, "end_index", None),
                        })
    return {
        "text": text,
        "citations": citations,
        "sources": sources,
        "searched": searched,
        "model": model(),
    }


def _extract_json_list(text: str) -> list[str]:
    """Best-effort pull of a JSON array of strings from model text."""
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    return [str(x).strip() for x in data if isinstance(x, str) and str(x).strip()]


def ground_scope(topic_name: str, n: int = 8, **kw) -> dict:
    """Grounded Prime scope/skim list for a topic, with citations."""
    prompt = (
        f"For the MCAT topic \u201c{topic_name}\u201d, search Wikipedia and LibreTexts "
        f"and list the {n} biggest-picture ideas a student should skim first (not "
        "memorizable details). Each item is a short noun phrase of 1-5 words, no "
        "trailing punctuation. Return ONLY a JSON array of strings."
    )
    out = ground(prompt, **kw)
    out["items"] = _extract_json_list(out["text"])[:n]
    return out


def _clean_explanation(text: str) -> str:
    """Strip inline markdown citations / bare URLs / LaTeX delimiters the model
    sometimes embeds, leaving clean skim prose (sources go in their own field)."""
    text = re.sub(r"\(?\[[^\]]*\]\(https?://[^)]+\)\)?", "", text)  # [title](url)
    text = re.sub(r"\(\s*https?://[^)\s]+\s*\)", "", text)          # (bare url)
    for d in ("\\(", "\\)", "\\[", "\\]"):
        text = text.replace(d, "")
    return re.sub(r"\s{2,}", " ", text).strip(" ,;")


def ground_scope_explained(topic_name: str, n: int = 8, **kw) -> dict:
    """ONE web-search call returning rich Prime scope items: for each big idea a
    'term', a clean 1-2 sentence 'explanation', and a 'sources' list of
    ``{title, url}`` (numbered Source 1/2/3 in the UI)."""
    prompt = (
        f"For the MCAT topic \u201c{topic_name}\u201d, search Wikipedia and LibreTexts "
        f"and list the {n} biggest-picture ideas a student should skim first (not "
        "memorizable details). For EACH idea return: 'term' (a 1-5 word noun "
        "phrase, no trailing punctuation), 'explanation' (2-4 sentences of PLAIN "
        "prose that actually explain the idea well enough to skim-understand it, "
        "with NO inline citations, URLs, or LaTeX), and 'sources' (a "
        "list of 1-3 objects {\"title\": page title, \"url\": page URL} you used). "
        "Return ONLY a JSON array of "
        "{\"term\":..,\"explanation\":..,\"sources\":[{\"title\":..,\"url\":..}]}."
    )
    out = ground(prompt, **kw)
    consulted = {_norm_url(u) for u in out["sources"]}
    consulted |= {_norm_url(c["url"]) for c in out["citations"]}
    title_by_url = {_norm_url(c["url"]): c.get("title", "")
                    for c in out["citations"] if c.get("url")}

    def _sources_of(d: dict) -> list[dict]:
        srcs: list[dict] = []
        raw = d.get("sources")
        if isinstance(raw, list):
            for s in raw:
                if isinstance(s, dict) and str(s.get("url", "")).strip():
                    u = str(s["url"]).strip()
                    t = (str(s.get("title", "")).strip()
                         or title_by_url.get(_norm_url(u), "") or u)
                    srcs.append({"title": t, "url": u})
        if not srcs:  # fall back to a single model-named source, if any
            u = str(d.get("source_url", "")).strip()
            if u:
                srcs.append({"title": str(d.get("source_title", "")).strip()
                             or title_by_url.get(_norm_url(u), "") or u, "url": u})
        return srcs[:3]

    items: list[dict] = []
    for d in _extract_json_objs(out["text"]):
        term = str(d.get("term", "")).strip().rstrip(" .;:,?!")
        if not term:
            continue
        srcs = _sources_of(d)
        items.append({
            "term": term,
            "explanation": _clean_explanation(str(d.get("explanation", ""))),
            "sources": srcs,
            "grounded": any(_norm_url(s["url"]) in consulted for s in srcs),
        })
    out["items"] = items[:n]
    return out


def explain(topic_name: str, term: str, **kw) -> dict:
    """A concise, web-grounded explanation of one scope idea, for Prime's
    "click a keyword" pane. Returns {"explanation", "sources", "citations"}."""
    prompt = (
        f"For the MCAT topic \u201c{topic_name}\u201d, explain the big idea "
        f"\u201c{term}\u201d in 1-2 concise sentences a student can skim (plain prose, "
        "no preamble). Search Wikipedia and LibreTexts to ground it."
    )
    out = ground(prompt, **kw)
    return {
        "explanation": (out.get("text") or "").strip(),
        "sources": out.get("sources", []),
        "citations": out.get("citations", []),
    }


def _extract_json_objs(text: str) -> list[dict]:
    """Best-effort pull of a JSON array of objects from model text."""
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    return [d for d in data if isinstance(d, dict)]


def _norm_url(u: str) -> str:
    return (u or "").split("?")[0].split("#")[0].rstrip("/").lower()


def _text_fragment(quote: str) -> str:
    """A scroll-to-text URL fragment (``#:~:text=``) that makes a browser jump to
    and highlight ``quote`` on the page. For longer quotes it uses a
    ``textStart,textEnd`` word range so a small mismatch in the middle still
    matches; browsers without text-fragment support simply ignore it and open the
    page normally (no breakage)."""
    words = (quote or "").split()
    if not words:
        return ""

    def enc(s: str) -> str:
        # Percent-encode; text-fragment syntax also needs '-' encoded.
        return _urlquote(s, safe="").replace("-", "%2D")

    if len(words) <= 8:
        return "#:~:text=" + enc(" ".join(words))
    return "#:~:text=" + enc(" ".join(words[:4])) + "," + enc(" ".join(words[-4:]))


_HTTP_UA = "MCAT-StudyApp/1.0 (educational flashcard sourcing)"
_NOISE_CHARS = set("[]{}|")
_MIN_RUN_WORDS = 5  # shortest verbatim run we'll trust as a specific highlight


def _fetch_page_text(url: str, timeout: int = 10) -> str | None:
    """GET a page and return its visible text (tags stripped), or None on any
    failure. Used to VERIFY a highlight quote actually appears on the page before
    we promise to jump to it."""
    if not url.startswith(("http://", "https://")):
        return None
    try:
        req = _urlreq.Request(url, headers={"User-Agent": _HTTP_UA})
        with _urlreq.urlopen(req, timeout=timeout) as r:
            raw = r.read(3_000_000)
        doc = raw.decode("utf-8", "ignore")
    except Exception:
        return None
    doc = re.sub(r"(?is)<(script|style|template)\b[^>]*>.*?</\1>", " ", doc)
    text = re.sub(r"(?s)<[^>]+>", " ", doc)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _normtok(t: str) -> str:
    """Normalize one token for matching: NFKC, unify dashes/quotes, casefold, and
    drop surrounding punctuation (text fragments match case-insensitively)."""
    t = _ud.normalize("NFKC", t)
    for a, b in (("\u2013", "-"), ("\u2014", "-"), ("\u2212", "-"),
                 ("\u2018", "'"), ("\u2019", "'"),
                 ("\u201c", '"'), ("\u201d", '"')):
        t = t.replace(a, b)
    return t.casefold().strip(".,;:!?()[]{}\"'\u00b7")


def _verified_snippet(page_text: str, quote: str) -> str | None:
    """The longest run of words (>= _MIN_RUN_WORDS) that appears VERBATIM in BOTH
    the page and the model's quote, taken from the PAGE's own text and free of
    citation/markup noise - so a text fragment built from it is guaranteed to
    exist on the page. None when there's no solid match (caller skips the jump)."""
    pw = page_text.split()
    qw = quote.split()
    if len(pw) < 2 or len(qw) < 2:
        return None
    pn = [_normtok(w) for w in pw]
    qn = [_normtok(w) for w in qw]
    noisy = [any(ch in _NOISE_CHARS for ch in w) for w in pw]
    # word-level longest common substring (page vs quote), breaking on noise.
    best_len = best_end = 0
    prev = [0] * (len(qn) + 1)
    for i, ptok in enumerate(pn):
        cur = [0] * (len(qn) + 1)
        if ptok and not noisy[i]:
            for j, qtok in enumerate(qn):
                if ptok == qtok:
                    run = prev[j] + 1
                    cur[j + 1] = run
                    if run > best_len:
                        best_len, best_end = run, i
        prev = cur
    if best_len < _MIN_RUN_WORDS:
        return None
    return " ".join(pw[best_end - best_len + 1:best_end + 1])


def _verify_highlights(cards: list[dict]) -> None:
    """Set each card's 'source_highlight_url' to a text fragment ONLY when its
    quote is CONFIRMED to appear on the real page (else the plain page URL). Each
    unique page is fetched once; total fetches are bounded. Only the URL changes -
    never the page or the card's Q/A."""
    page_cache: dict[str, str | None] = {}
    for c in cards:
        su = (c.get("source_url") or "").strip()
        quote = (c.get("source_quote") or "").strip()
        c["source_highlight_url"] = su
        c["highlight_verified"] = False
        if not su or not quote or "#" in su:
            continue
        if su not in page_cache:
            page_cache[su] = (None if len(page_cache) >= 6
                              else _fetch_page_text(su))
        text = page_cache.get(su)
        if not text:
            continue
        snippet = _verified_snippet(text, quote)
        if snippet:
            c["source_highlight_url"] = su + _text_fragment(snippet)
            c["source_quote_confirmed"] = snippet  # the passage confirmed on-page
            c["highlight_verified"] = True


def draft_cards(topic_name: str, n: int = 12, **kw) -> dict:
    """Web-search-grounded flashcard draft: atomic cards, each with the source
    URL the model drew it from, VERIFIED against the pages actually consulted in
    the search (so a card's citation isn't just the model's word).

    Returns ``{"cards": [{"front","back","source_url","grounded"}], "sources",
    "citations", "searched", "model"}``. Ungrounded cards (source not among the
    consulted pages) are flagged, not silently trusted."""
    prompt = (
        f"Generate {n} atomic MCAT flashcards for the topic \u201c{topic_name}\u201d. "
        "SEARCH Wikipedia and LibreTexts and ground EVERY card in what you "
        "actually find there \u2014 invent nothing. Each card tests ONE idea: a short "
        "question in 'front' and a concise one-sentence answer in 'back'. Include "
        "'source_url' = the exact page you drew the fact from, and 'source_quote' "
        "= a SHORT passage (6-15 words) copied VERBATIM from that page (character "
        "for character - no ellipses, no added or changed words) that supports the "
        "answer. Return ONLY a JSON array of objects "
        "{\"front\":..,\"back\":..,\"source_url\":..,\"source_quote\":..}."
    )
    out = ground(prompt, **kw)
    consulted = {_norm_url(u) for u in out["sources"]}
    consulted |= {_norm_url(c["url"]) for c in out["citations"]}
    cards: list[dict] = []
    for d in _extract_json_objs(out["text"]):
        front = str(d.get("front", "")).strip()
        back = str(d.get("back", "")).strip()
        if not front or not back:
            continue
        su = str(d.get("source_url", "")).strip()
        quote = str(d.get("source_quote", "")).strip()
        cards.append({
            "front": front,
            "back": back,
            "source_url": su,
            "source_quote": quote,           # the model's RAW verbatim claim
            "source_quote_confirmed": "",    # page snippet if verified below
            "grounded": bool(su) and _norm_url(su) in consulted,
        })
    out["cards"] = cards[:n]
    # VERIFY each quote against the real page; sets source_highlight_url so
    # "Check source" only jumps to a passage confirmed to exist on the page.
    _verify_highlights(out["cards"])
    return out


def build_scope_cache(path: str = "qt/aqt/mcat_data/scope_cache.json",
                      reasoning: str = "low") -> dict:
    """Precompute a grounded Prime scope list (+ sources) for EVERY MCAT topic and
    save to ``path``. This is the offline / AI-off fallback the app reads when a
    live web search can't run. Re-runnable to refresh."""
    import pathlib
    try:
        import mcat_models as m  # standalone
    except Exception:  # pragma: no cover - in-app path
        from aqt import mcat_models as m
    topics = [
        (f"MCAT::{st}::{tok}", name)
        for st, _sec, _full, tl in m.OUTLINE for tok, name in tl
    ]
    cache: dict = {"_meta": {"model": model(), "reasoning": reasoning,
                             "domains": ALLOWED_DOMAINS}}
    for i, (tag, name) in enumerate(topics, 1):
        try:
            res = ground_scope_explained(name, reasoning=reasoning)
            cache[tag] = {"name": name, "items": res["items"],
                          "sources": res["sources"][:12]}
            print(f"[{i}/{len(topics)}] {tag}: {len(res['items'])} items, "
                  f"{len(res['sources'])} sources", flush=True)
        except Exception as e:  # a topic can fail without killing the batch
            cache[tag] = {"name": name, "items": [], "error": str(e)}
            print(f"[{i}/{len(topics)}] {tag}: ERROR {e}", flush=True)
    pathlib.Path(path).write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for k, v in cache.items() if k != "_meta" and v.get("items"))
    print(f"\nwrote {path}: {ok}/{len(topics)} topics grounded", flush=True)
    return cache


if __name__ == "__main__":
    import sys

    if "--cache" in sys.argv:
        build_scope_cache(reasoning=os.environ.get("MCAT_WEBSEARCH_REASONING", "low"))
        sys.exit(0)

    if "--cards" in sys.argv:
        topic = next((a for a in sys.argv[1:] if not a.startswith("--")), "Glycolysis")
        res = draft_cards(topic, n=8,
                          reasoning=os.environ.get("MCAT_WEBSEARCH_REASONING", "low"))
        g = sum(c["grounded"] for c in res["cards"])
        print(f"searched: {res['searched']}   cards: {len(res['cards'])}   "
              f"grounded to a consulted source: {g}/{len(res['cards'])}")
        for c in res["cards"]:
            v = "verified" if c.get("highlight_verified") else "UNVERIFIED"
            print(f"\n  Q: {c['front']}")
            print(f"  A: {c['back']}")
            print(f"     source:      {c['source_url']}  [grounded={c['grounded']}]")
            if c.get("source_quote"):
                print(f"     model_quote: \u201c{c['source_quote']}\u201d")
            print(f"     confirmed:   \u201c{c.get('source_quote_confirmed') or ''}\u201d  [{v}]")
            if c.get("source_highlight_url", c["source_url"]) != c["source_url"]:
                print(f"     open:        {c['source_highlight_url']}")
        sys.exit(0)

    topic = sys.argv[1] if len(sys.argv) > 1 else "Light & optics"
    reasoning = os.environ.get("MCAT_WEBSEARCH_REASONING", "high")
    print(f"available: {available()}   model: {model()}   reasoning: {reasoning}")
    res = ground_scope(topic, reasoning=reasoning)
    print(
        f"searched: {res['searched']}   items: {len(res['items'])}   "
        f"citations: {len(res['citations'])}   sources: {len(res['sources'])}"
    )
    print("\nscope items:")
    for it in res["items"]:
        print("   -", it)
    print("\ncitations (the 'Check sources' data):")
    shown = res["citations"] or [{"title": "", "url": u} for u in res["sources"]]
    seen = set()
    for c in shown:
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        print(f"   - {c.get('title') or '(source)'} -> {c['url']}")
