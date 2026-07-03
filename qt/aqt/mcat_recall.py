# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Recall study-order upgrades — the layer on top of the points-at-stake engine.

Two program-phase-aware nudges to *how* the deck is studied (the engine already
ranks *what* is weak in ``mcat_weak_topics``):

1. A phase-aware new-card cap. Weeks 1-3 (Encode / Consolidate) hold new-card
   intake low so review load stays sane while topics are being built; week 4
   (Recall) lifts the cap so the remaining new cards get burned down. This is a
   normal, reversible deck-option write (the deck's per-deck ``newLimit``
   override), so it never risks the collection.

2. An interleaved Focus session. Instead of blocking one topic, gather the
   current deck's due MCAT cards into a filtered deck in *random* order so topics
   mix — the lazy interleave. Built through the exact same documented
   ``FilteredDeckForUpdate`` API the Create-Filtered-Deck dialog uses.

The phase is read from ``mcat_today`` (single source of truth for the calendar).
The cap policy (``cap_for_phase``) is pure and unit-tested; run this file
directly for the assert-based self-check.
"""

from __future__ import annotations

# Phase names mirror mcat_today's constants. Duplicated (not imported) so the
# pure ``cap_for_phase`` self-test can run standalone with `python3
# mcat_recall.py` — importing aqt.mcat_today would pull in the whole aqt/anki
# package. The collection-bound code below reads the live phase from mcat_today,
# so these strings only anchor the pure policy + its self-test.
PHASE_ENCODE = "Encode"
PHASE_RECALL = "Recall"
PHASE_CONSOLIDATE = "Consolidate"

# New-cards/day caps. Low during Encode/Consolidate (weeks 1-3): new material
# should arrive from Build overflow, not a firehose of new cards. Lifted during
# Recall (week 4) to drain whatever new cards remain before the exam.
CAP_LOW = 5
CAP_LIFTED = 9999

# The interleaved Focus filtered deck. Reused across sessions (looked up by name)
# so we rebuild one deck instead of piling up duplicates.
FOCUS_DECK_NAME = "MCAT Focus (interleaved)"
# Matches Anki's own default filtered-deck gather limit (see rslib new_filtered).
FOCUS_LIMIT = 100


# --- pure cap policy (no Qt, no collection) ---------------------------------


def cap_for_phase(phase: str) -> int:
    """New-cards/day cap for a program phase.

    Recall lifts the cap; every other phase (Encode, Consolidate, or anything
    unrecognised) stays conservatively low."""
    return CAP_LIFTED if phase == PHASE_RECALL else CAP_LOW


# --- phase lookup (collection-bound, via mcat_today) ------------------------


def _current_phase(col) -> str:  # type: ignore[no-untyped-def]
    """Today's program phase, straight from the mcat_today calendar."""
    from datetime import date  # noqa: PLC0415

    from aqt import mcat_today  # noqa: PLC0415

    cal = mcat_today.get_cal(col)
    di = mcat_today.day_index(cal["start_date"], date.today().isoformat())
    return mcat_today.phase_for(di, cal["horizon_days"])


# --- phase-aware new-card cap (safe, reversible deck-config write) -----------


def apply_phase_cap(col, deck) -> int:  # type: ignore[no-untyped-def]
    """Set ``deck``'s per-deck new-cards/day limit to the current phase's cap.

    Writes the legacy deck dict's ``newLimit`` override (a per-deck limit that
    the v3 scheduler honours) rather than the shared preset, so other decks are
    untouched and the change is fully reversible from Deck Options. Returns the
    cap applied.

    ponytail: per-deck ``newLimit`` is the lazy, non-destructive knob — it's the
    same value the Deck Options "New cards/day" limit writes. Ceiling: we don't
    stash the previous value to auto-restore; the user (or the next phase run)
    just overwrites it."""
    cap = cap_for_phase(_current_phase(col))
    deck["newLimit"] = cap
    col.decks.update_dict(deck)
    return cap


def apply_cap(mw) -> None:  # type: ignore[no-untyped-def]
    """Menu action: cap the current deck's new-card intake for today's phase."""
    from aqt.utils import showWarning, tooltip  # noqa: PLC0415

    col = mw.col
    deck = col.decks.current()
    if col.decks.is_filtered(deck["id"]):
        showWarning(
            "Select your normal MCAT deck (not a filtered deck) to cap new cards.",
            parent=mw,
        )
        return

    phase = _current_phase(col)
    cap = apply_phase_cap(col, deck)
    cap_text = "lifted" if cap >= CAP_LIFTED else str(cap)
    mw.reset()  # recompute today's new-card counts under the new limit
    tooltip(
        f"{phase} phase \u2192 new cards/day {cap_text} for \u201c{deck['name']}\u201d.",
        parent=mw,
    )


# --- interleaved Focus session (documented FilteredDeckForUpdate API) --------


def start_focus_session(mw, deck) -> None:  # type: ignore[no-untyped-def]
    """Build/rebuild the interleaved Focus filtered deck over ``deck``'s due MCAT
    cards and drop into its overview to study.

    Uses the exact proto the Create-Filtered-Deck dialog uses (see
    ``aqt/filtered_deck.py``): ``get_or_create_filtered_deck`` ->
    set ``config.reschedule`` + one ``FilteredDeckConfig.SearchTerm`` (search,
    limit, order) -> ``add_or_update_filtered_deck``.

    ponytail: RANDOM order *is* the interleave — a random draw across the due
    pool mixes topics for free (it's also Anki's own default filtered-deck
    order). Ceiling: this is shuffle-interleaving, not a strict round-robin of
    one-card-per-topic; true round-robin would need engine work. reschedule=True
    keeps FSRS scheduling valid. Needs a running Anki / demo to confirm the deck
    builds and study starts."""
    from anki.collection import SearchNode  # noqa: PLC0415
    from anki.decks import DeckId, FilteredDeckConfig  # noqa: PLC0415
    from aqt.operations.scheduling import add_or_update_filtered_deck  # noqa: PLC0415
    from aqt.utils import tooltip  # noqa: PLC0415

    col = mw.col

    # Only the deck name needs escaping (spaces / specials) — SearchNode handles
    # that; the rest is standard search syntax. Filtered decks already exclude
    # suspended/buried, but we keep -is:suspended to mirror the intended filter.
    search = col.build_search_string(
        SearchNode(deck=deck["name"]),
        "is:due -is:suspended tag:MCAT::*",
    )

    # Reuse the existing Focus deck if it's ours (a filtered deck); otherwise let
    # the backend create a fresh one from id 0.
    existing = col.decks.id_for_name(FOCUS_DECK_NAME)
    if existing is not None and not col.decks.is_filtered(existing):
        existing = None
    filtered = col.sched.get_or_create_filtered_deck(deck_id=existing or DeckId(0))
    filtered.name = FOCUS_DECK_NAME
    filtered.allow_empty = True  # don't hard-error when nothing is due yet

    config = filtered.config
    config.reschedule = True
    del config.search_terms[:]
    config.search_terms.append(
        FilteredDeckConfig.SearchTerm(
            search=search,
            limit=FOCUS_LIMIT,
            order=FilteredDeckConfig.SearchTerm.RANDOM,
        )
    )

    def on_success(out) -> None:  # type: ignore[no-untyped-def]
        col.decks.set_current(out.id)
        mw.moveToState("overview")
        tooltip("Focus session ready \u2014 topics interleaved (random order).", parent=mw)

    add_or_update_filtered_deck(parent=mw, deck=filtered).success(
        on_success
    ).run_in_background()


def start_focus(mw) -> None:  # type: ignore[no-untyped-def]
    """Menu action: start the interleaved Focus session on the current deck."""
    from aqt.utils import showWarning  # noqa: PLC0415

    col = mw.col
    deck = col.decks.current()
    if col.decks.is_filtered(deck["id"]):
        showWarning(
            "Open your normal MCAT deck first, then start the Focus session.",
            parent=mw,
        )
        return
    start_focus_session(mw, deck)


# --- self-test (pure policy; no Qt, no collection) --------------------------


def _self_test() -> None:
    # Recall lifts the cap; every other phase stays low.
    assert cap_for_phase(PHASE_RECALL) == CAP_LIFTED
    assert cap_for_phase(PHASE_ENCODE) == CAP_LOW
    assert cap_for_phase(PHASE_CONSOLIDATE) == CAP_LOW
    # unknown/garbage phase is conservative (low), never accidentally lifted.
    assert cap_for_phase("") == CAP_LOW
    assert cap_for_phase("whatever") == CAP_LOW
    # the whole point: weeks 1-3 intake < week 4 intake.
    assert cap_for_phase(PHASE_ENCODE) < cap_for_phase(PHASE_RECALL)
    assert cap_for_phase(PHASE_CONSOLIDATE) < cap_for_phase(PHASE_RECALL)

    print("mcat_recall self-test: OK")
    print(
        f"  Encode/Consolidate cap {CAP_LOW} new cards/day; "
        f"Recall lifts to {CAP_LIFTED}"
    )


if __name__ == "__main__":
    _self_test()
