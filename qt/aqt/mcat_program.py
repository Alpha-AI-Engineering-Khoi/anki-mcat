# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pure logic for the MCAT "encode front-half" program (Prime -> Connect ->
Build).

Holds three kinds of pure, unit-testable logic so the Qt panels in
``mcat_encode`` stay thin:

- topic identity / slug mapping, built on the shared ``mcat_models`` outline;
- the per-topic program state (primed / connected / built), stored in the
  collection config so it SYNCS with the rest of the collection;
- the "2-4 linter" that flags a concept map that is over- or under-chunked.

The state helpers come in two layers: pure ``*_in(state, ...)`` functions that
transform a plain dict (so the self-test needs no collection), and thin
collection-bound wrappers that load/mutate/save that dict via ``col`` config.

Run this file directly for an assert-based self-check of the linter + state.
"""

from __future__ import annotations

from dataclasses import dataclass

# ponytail: state lives in collection config (col.get_config/set_config), not on
# a per-topic sidecar note. Config already syncs and holds arbitrary JSON, so
# this is the lazy path that "persists and syncs". Ceiling: the primed flag is
# NOT an Anki tag, so it is not searchable in the browser; primed_tag() below is
# provided for a future review-lock that wants the tag form.
PROGRAM_KEY = "mcat_program"

# A well-chunked group holds 2-4 items (working-memory friendly). The linter
# warns outside that band; it never blocks.
MIN_CHUNK = 2
MAX_CHUNK = 4


# --- topic identity ---------------------------------------------------------


@dataclass
class Topic:
    section_token: str  # e.g. "BioBiochem"
    section: str  # short display, e.g. "Bio/Biochem"
    token: str  # topic token, globally unique, e.g. "Enzymes"
    name: str  # display, e.g. "Enzyme structure & kinetics"
    tag: str  # coverage tag, e.g. "MCAT::BioBiochem::Enzymes"
    slug: str  # stable id for config keys / tags


def _slug(section_token: str, token: str) -> str:
    return f"{section_token}.{token}"


def all_topics() -> list[Topic]:
    """The 50 MCAT topics, from the shared outline. Imported lazily so this
    module can still be run standalone for its self-test."""
    from aqt import mcat_models as models  # noqa: PLC0415

    out: list[Topic] = []
    for section_token, section, _full, topics in models.OUTLINE:
        for token, name in topics:
            out.append(
                Topic(
                    section_token=section_token,
                    section=section,
                    token=token,
                    name=name,
                    tag=f"{models.TAG_ROOT}::{section_token}::{token}",
                    slug=_slug(section_token, token),
                )
            )
    return out


def topic_for_slug(slug: str) -> Topic | None:
    return next((t for t in all_topics() if t.slug == slug), None)


def _slug_of(topic: Topic | str) -> str:
    return topic.slug if isinstance(topic, Topic) else str(topic)


def primed_tag(topic: Topic | str) -> str:
    """The tag form of the primed flag, for a future tag-based review-lock."""
    return f"mcat::primed::{_slug_of(topic).lower()}"


# --- per-topic state (pure dict transforms) ---------------------------------


def _default_record() -> dict:
    return {"primed": False, "hypotheses": "", "connect": [], "concepts": [], "links": []}


def record_in(state: dict, slug: str) -> dict:
    """The record for a slug, or a fresh default (does not mutate ``state``)."""
    return state.get(slug) or _default_record()


def set_primed_in(state: dict, slug: str, hypotheses: str) -> dict:
    rec = state.setdefault(slug, _default_record())
    rec["primed"] = True
    rec["hypotheses"] = hypotheses
    return state


def set_connect_in(state: dict, slug: str, questions: list[str]) -> dict:
    rec = state.setdefault(slug, _default_record())
    rec["connect"] = list(questions)
    return state


def set_build_in(state: dict, slug: str, concepts: list[dict], links: list[dict]) -> dict:
    rec = state.setdefault(slug, _default_record())
    rec["concepts"] = concepts
    rec["links"] = links
    return state


def is_primed_in(state: dict, slug: str) -> bool:
    return bool(record_in(state, slug).get("primed"))


def is_connected_in(state: dict, slug: str) -> bool:
    return any((q or "").strip() for q in record_in(state, slug).get("connect", []))


def is_built_in(state: dict, slug: str) -> bool:
    return len(record_in(state, slug).get("concepts", [])) > 0


# --- per-topic state (collection-bound wrappers) ----------------------------


def _load(col) -> dict:  # type: ignore[no-untyped-def]
    return col.get_config(PROGRAM_KEY, {}) or {}


def get_record(col, topic: Topic | str) -> dict:  # type: ignore[no-untyped-def]
    return record_in(_load(col), _slug_of(topic))


def is_primed(col, topic: Topic | str) -> bool:  # type: ignore[no-untyped-def]
    return is_primed_in(_load(col), _slug_of(topic))


def is_connected(col, topic: Topic | str) -> bool:  # type: ignore[no-untyped-def]
    return is_connected_in(_load(col), _slug_of(topic))


def is_built(col, topic: Topic | str) -> bool:  # type: ignore[no-untyped-def]
    return is_built_in(_load(col), _slug_of(topic))


def mark_primed(col, topic: Topic | str, hypotheses: str):  # type: ignore[no-untyped-def]
    state = set_primed_in(_load(col), _slug_of(topic), hypotheses)
    return col.set_config(PROGRAM_KEY, state)


def save_connect(col, topic: Topic | str, questions: list[str]):  # type: ignore[no-untyped-def]
    state = set_connect_in(_load(col), _slug_of(topic), questions)
    return col.set_config(PROGRAM_KEY, state)


def save_build(col, topic: Topic | str, concepts: list[dict], links: list[dict]):  # type: ignore[no-untyped-def]
    state = set_build_in(_load(col), _slug_of(topic), concepts, links)
    return col.set_config(PROGRAM_KEY, state)


# --- the 2-4 concept-map linter (pure) --------------------------------------


def lint_concepts(concepts: list[dict], links: list[dict]) -> list[str]:
    """Live, non-blocking warnings for a concept map.

    ``concepts`` are ``{"id", "parent", "label"}`` outline nodes; ``links`` are
    ``{"src", "dst", "label"}`` labeled edges between concept ids. Two rules:

    - a node with more than MAX_CHUNK children -> "group into sub-chunks";
    - a lone one-in / one-out concept (a pass-through in the link graph) ->
      "merge or re-chunk".
    """
    warnings: list[str] = []
    by_id = {c["id"]: c for c in concepts}

    children: dict[int, list[int]] = {}
    for c in concepts:
        parent = c.get("parent")
        if parent is not None:
            children.setdefault(parent, []).append(c["id"])
    for cid, kids in children.items():
        if len(kids) > MAX_CHUNK:
            label = by_id.get(cid, {}).get("label", "?")
            warnings.append(
                f"\u201c{label}\u201d has {len(kids)} sub-concepts \u2014 "
                f"group into sub-chunks (aim {MIN_CHUNK}\u2013{MAX_CHUNK})."
            )

    indeg = {c["id"]: 0 for c in concepts}
    outdeg = {c["id"]: 0 for c in concepts}
    for link in links:
        if link.get("src") in outdeg:
            outdeg[link["src"]] += 1
        if link.get("dst") in indeg:
            indeg[link["dst"]] += 1
    for c in concepts:
        cid = c["id"]
        if indeg.get(cid, 0) == 1 and outdeg.get(cid, 0) == 1:
            warnings.append(
                f"\u201c{c['label']}\u201d is a lone one-in/one-out concept \u2014 "
                "merge or re-chunk."
            )
    return warnings


def _self_test() -> None:
    # Linter: a node with >4 children is flagged to group into sub-chunks.
    over = [{"id": 0, "parent": None, "label": "Backbone"}] + [
        {"id": i, "parent": 0, "label": f"c{i}"} for i in range(1, 6)
    ]
    w = lint_concepts(over, [])
    assert len(w) == 1 and "group into sub-chunks" in w[0], w

    # Linter: a one-in/one-out pass-through is flagged to merge or re-chunk.
    chain = [
        {"id": 1, "parent": None, "label": "A"},
        {"id": 2, "parent": None, "label": "B"},
        {"id": 3, "parent": None, "label": "C"},
    ]
    links = [
        {"src": 1, "dst": 2, "label": "causes"},
        {"src": 2, "dst": 3, "label": "leads to"},
    ]
    w2 = lint_concepts(chain, links)
    assert len(w2) == 1 and "one-in/one-out" in w2[0], w2

    # Linter: a well-chunked map (3 children, no pass-throughs) is clean.
    ok = [{"id": 0, "parent": None, "label": "root"}] + [
        {"id": i, "parent": 0, "label": f"x{i}"} for i in range(1, 4)
    ]
    assert lint_concepts(ok, []) == [], lint_concepts(ok, [])

    # State: primed / connected / built transitions on a plain dict.
    st: dict = {}
    assert not is_primed_in(st, "S")
    set_primed_in(st, "S", "cheaper enzymes lower activation energy")
    assert is_primed_in(st, "S")
    assert record_in(st, "S")["hypotheses"].startswith("cheaper")

    assert not is_connected_in(st, "S")
    set_connect_in(st, "S", ["", "   ", "why do I need this?"])
    assert is_connected_in(st, "S")

    assert not is_built_in(st, "S")
    set_build_in(st, "S", [{"id": 0, "parent": None, "label": "c"}], [])
    assert is_built_in(st, "S")

    # record_in never mutates state for an unknown slug.
    before = len(st)
    _ = record_in(st, "unknown-slug")
    assert len(st) == before

    print("mcat_program self-test: OK")
    print(
        f"  linter rules fire ({MIN_CHUNK}\u2013{MAX_CHUNK} chunk band); "
        "state primed/connected/built OK"
    )


if __name__ == "__main__":
    _self_test()
