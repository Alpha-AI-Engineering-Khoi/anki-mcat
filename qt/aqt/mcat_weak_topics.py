# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Desktop "Focus Weak Topics" read-out — the user-facing surface for the Rust
points-at-stake engine change. Ranks MCAT review topics weakest-first (weakness =
1 − average FSRS recall) across a learner-chosen SET of decks (picked via the same
inline checklist as Coverage/Readiness; the ranking combines them) using the
shared engine RPC ``SchedulerService.GetPointsAtStakeQueue``. Read-only; computes
off the UI thread. Mirrors the iOS WeakTopicsView read-out."""

from __future__ import annotations

from aqt import mcat_models as m
from aqt import mcat_ui as ui

TOPIC_PREFIX = "MCAT::"


def show(mw) -> None:  # type: ignore[no-untyped-def]
    decks = m.scorable_decks(mw.col)
    ui.deck_scoped_panel(
        mw,
        "Focus Weak Topics",
        decks,
        compute=_gather,
        render=_render,
    )


def _gather(col, selected):  # type: ignore[no-untyped-def]
    """Rank MCAT topics weakest-first across the SELECTED decks. The engine RPC
    scopes to the current deck, so we run it per selected deck and merge topics
    (card-weighted weakness + recall), restoring the original current deck."""
    orig = col.decks.current()["id"]
    merged: dict = {}
    try:
        for name in selected:
            did = col.decks.id(name)
            if did is None:
                continue
            col.decks.set_current(did)
            queue = col._backend.get_points_at_stake_queue(
                topic_tag_prefix=TOPIC_PREFIX, weight_by_topic_size=False
            )
            for t in queue.topics:
                e = merged.setdefault(
                    t.topic, {"cards": 0, "wsum": 0.0, "rsum": 0.0, "rn": 0}
                )
                e["cards"] += t.card_count
                e["wsum"] += float(t.weakness) * t.card_count
                if t.HasField("mean_retrievability"):
                    e["rsum"] += t.mean_retrievability * t.card_count
                    e["rn"] += t.card_count
    finally:
        col.decks.set_current(orig)
    out = []
    for topic, e in merged.items():
        cards = e["cards"] or 1
        out.append(
            {
                "topic": topic,
                "cards": e["cards"],
                "weakness": e["wsum"] / cards,
                "retr": (e["rsum"] / e["rn"]) if e["rn"] else None,
            }
        )
    out.sort(key=lambda x: x["weakness"], reverse=True)
    return out


def _weakness_color(weakness: float) -> str:
    if weakness >= 0.40:
        return ui.BAD
    if weakness >= 0.15:
        return ui.WARN
    return ui.GOOD


def _render(selected, topics) -> str:  # type: ignore[no-untyped-def]
    n = len(selected)
    scope = f"{n} deck{'s' if n != 1 else ''}: <b>{ui.esc(', '.join(selected))}</b>"
    head = "<h2>Focus Weak Topics</h2>"
    if not topics:
        return (
            head
            + f"<p style='color:{ui.MUTED}'>Across {scope}.</p>"
            + "<p>No due, MCAT-tagged review cards in the selected deck(s) yet. "
            "Points-at-stake ranks topics by FSRS recall on cards that are due for "
            "review — once these decks have due, <code>MCAT::</code>-tagged review "
            "cards, their weakest topics rank here.</p>"
        )
    total = sum(t["cards"] for t in topics)
    parts = [
        head,
        f"<p style='color:{ui.MUTED}'>Across {scope}. Your due review cards, ranked "
        "weakest-topic-first by the engine’s points-at-stake score. Weakness = 1 − "
        f"average FSRS recall, computed on-device. {total} due cards across "
        f"{len(topics)} topics.</p>",
    ]
    for i, t in enumerate(topics, 1):
        weakness = float(t["weakness"])
        color = _weakness_color(weakness)
        retr = (
            f"{t['retr'] * 100:.0f}% avg recall"
            if t["retr"] is not None
            else "no memory state"
        )
        noun = "card" if t["cards"] == 1 else "cards"
        parts.append(
            f"<h3>{i}. {ui.esc(t['topic'])} "
            f"<span style='color:{color}'>{weakness * 100:.0f}% weak</span></h3>"
        )
        parts.append(ui.bar(weakness, color))
        parts.append(
            f"<p style='color:{ui.MUTED}'>{t['cards']} due {noun} &middot; {retr}</p>"
        )
    parts.append(
        f"<p style='color:{ui.MUTED}'>Study these top-down — the engine surfaces the "
        "weakest topics first.</p>"
    )
    return "".join(parts)
