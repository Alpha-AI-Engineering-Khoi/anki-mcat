# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""MCAT "paraphrase test" (challenge 7d): measure Performance for real.

Performance is meant to answer a different question than Memory. Memory asks
"can you recall this card?"; Performance asks "can you answer a *reworded*,
exam-style version of it?". Until now Performance was a fake \u2014 Memory times a
fixed transfer constant \u2014 so it just tracked Memory. This module makes it a
measurement:

- ``mcat_ai.paraphrase_questions`` rewrites a card into 2 exam-style questions;
- the learner answers them and self-grades (the Qt panel below);
- results are stored per source card in the synced collection config;
- ``paraphrase_accuracy`` turns correct/attempts into a proportion with a Wilson
  confidence interval (a ``mcat_models.ScoreRange``), and abstains below a stated
  minimum \u2014 no measured Performance until there is enough evidence;
- ``memory_performance_gap`` reports recall minus measured accuracy, the number
  this whole challenge exists to surface.

The pure ``*_in`` transforms + accuracy math need no collection and no Qt, so
they run in the assert-based self-test (run this file directly). Everything works
with AI switched OFF.
"""

from __future__ import annotations

import math

# ScoreRange lives in the shared score model. Import via the package at runtime;
# fall back to the sibling module when this file is run directly for its
# self-test (python mcat_paraphrase.py), mirroring mcat_eval's standalone path.
try:
    from aqt import mcat_models as _models
except Exception:  # pragma: no cover - standalone self-test path
    import mcat_models as _models  # type: ignore

# ponytail: results live in collection config (col.get_config/set_config), keyed
# by source card id, exactly like mcat_program's state. Config already syncs and
# holds arbitrary JSON, so this is the lazy "persists and syncs" path. Ceiling:
# the tally is collection-wide, not deck-scoped, so measured Performance is a
# global transfer signal applied to each deck's assessment.
PARAPHRASE_KEY = "mcat_paraphrase"

# Honesty gate: no measured Performance until the learner has answered at least
# this many reworded questions. Below it, paraphrase_accuracy returns None and
# the assessment keeps the provisional Performance blend.
MIN_PARAPHRASE_ATTEMPTS = 10

_ACCURACY_CI_Z = 1.96  # 95% interval, matching memory_score

# A small SEEDED demonstration so the self-test is real and offline: strong
# recall (memory \u2248 90%) but weaker transfer (paraphrase accuracy \u2248 65%), i.e.
# Performance \u2260 Memory \u2014 a memory\u2192performance gap of about 25 points.
SEEDED_MEMORY_POINT = 0.90


# --- results storage (pure dict transforms) ---------------------------------


def _default_result() -> dict:
    return {"correct": 0, "attempts": 0}


def record_result_in(state: dict, card_id, correct: bool) -> dict:  # type: ignore[no-untyped-def]
    """Record one answer for a source card. Mutates and returns ``state``."""
    rec = state.setdefault(str(card_id), _default_result())
    rec["attempts"] = int(rec.get("attempts", 0)) + 1
    if correct:
        rec["correct"] = int(rec.get("correct", 0)) + 1
    return state


def summary_in(state: dict) -> tuple[int, int]:
    """Collection-wide (correct, attempts) across every source card."""
    correct = sum(int(r.get("correct", 0)) for r in state.values())
    attempts = sum(int(r.get("attempts", 0)) for r in state.values())
    return correct, attempts


# --- measured accuracy + the gap (pure) -------------------------------------


def paraphrase_accuracy(correct: int, attempts: int):  # -> ScoreRange | None
    """Proportion correct with a Wilson score 95% interval, as a ScoreRange.

    Returns ``None`` below ``MIN_PARAPHRASE_ATTEMPTS`` \u2014 honesty: we do not claim
    a measured Performance until there is enough evidence to bound it."""
    if attempts <= 0 or attempts < MIN_PARAPHRASE_ATTEMPTS:
        return None
    p = min(1.0, max(0.0, correct / attempts))
    z, n = _ACCURACY_CI_Z, attempts
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    # point is the raw proportion; Wilson bounds the interval. ScoreRange.make
    # clamps to [0,1] and guarantees low <= point <= high.
    return _models.ScoreRange.make(center - half, p, center + half)


def memory_performance_gap(memory_point: float, paraphrase_point: float) -> float:
    """Recall minus measured transfer: how much Performance trails Memory."""
    return memory_point - paraphrase_point


def seeded_demo_state() -> dict:
    """An offline demonstration set: 20 answers across 4 source cards, 13 right
    (65%), against a seeded memory of 90% \u2014 a ~25-point memory\u2192performance gap."""
    return {
        "1001": {"correct": 4, "attempts": 5},
        "1002": {"correct": 3, "attempts": 5},
        "1003": {"correct": 3, "attempts": 5},
        "1004": {"correct": 3, "attempts": 5},
    }


# --- collection-bound wrappers ----------------------------------------------


def _load(col) -> dict:  # type: ignore[no-untyped-def]
    return col.get_config(PARAPHRASE_KEY, {}) or {}


def record_result(col, card_id, correct: bool):  # type: ignore[no-untyped-def]
    state = record_result_in(_load(col), card_id, correct)
    return col.set_config(PARAPHRASE_KEY, state)


def results_summary(col) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    return summary_in(_load(col))


def measured_accuracy(col):  # type: ignore[no-untyped-def]  # -> ScoreRange | None
    """The deck-independent measured Performance, or None below the minimum."""
    correct, attempts = results_summary(col)
    return paraphrase_accuracy(correct, attempts)


# --- Qt panel: the paraphrase check -----------------------------------------


def _gradeable_cards(col, deck: str, cap: int = 40) -> list[tuple]:  # type: ignore[no-untyped-def]
    """Up to ``cap`` (card_id, front, back) tuples from the deck, html stripped.

    ponytail: takes the first ``cap`` cards with a non-empty front AND back
    (fields[0]/fields[1]); cloze/other note layouts fall back to the first two
    fields. Ceiling: no smart sampling and no cloze-aware answer extraction."""
    from anki.utils import strip_html

    quoted = '"' + deck.replace('"', '\\"') + '"'
    out: list[tuple] = []
    for cid in col.find_cards(f"deck:{quoted}"):
        note = col.get_card(cid).note()
        if not note.fields:
            continue
        front = strip_html(note.fields[0]).strip()
        back = strip_html(note.fields[1]).strip() if len(note.fields) > 1 else ""
        if front and back:
            out.append((cid, front, back))
            if len(out) >= cap:
                break
    return out


def show(mw) -> None:  # type: ignore[no-untyped-def]
    """Answer 2 reworded, exam-style questions per card and self-grade them; the
    results drive the (now real) Performance score. Works with AI OFF."""
    from aqt import mcat_ai as ai
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button, showInfo, tooltip

    col = mw.col
    deck = col.decks.current()["name"]
    cards = _gradeable_cards(col, deck)
    if not cards:
        showInfo(
            "No cards with a front and back were found in the current deck to "
            "reword. Pick a deck with basic cards and try again.",
            parent=mw,
        )
        return

    dialog = QDialog(mw)
    dialog.setWindowTitle(f"Performance test \u2014 {deck}")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            "Answer these reworded, exam-style questions from memory, then reveal "
            "the key and grade yourself. This measures Performance (can you "
            "transfer the idea?), not just Memory (can you recall the card?)."
        )
    )
    progress = QLabel("")
    progress.setEnabled(False)
    layout.addWidget(progress)

    blocks: list[dict] = []
    for _i in range(2):
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        v = QVBoxLayout(box)
        stem = QLabel("")
        stem.setWordWrap(True)
        v.addWidget(stem)
        answer = QLabel("")
        answer.setWordWrap(True)
        answer.setEnabled(False)  # native muted secondary text
        v.addWidget(answer)
        row = QHBoxLayout()
        reveal = QPushButton("Show answer")
        got = QPushButton("Got it")
        missed = QPushButton("Missed it")
        for b in (reveal, got, missed):
            row.addWidget(b)
        v.addLayout(row)
        layout.addWidget(box)
        blocks.append(
            {"stem": stem, "answer": answer, "reveal": reveal, "got": got, "missed": missed, "graded": False}
        )

    footer = QLabel("")
    footer.setWordWrap(True)
    layout.addWidget(footer)

    buttons = QDialogButtonBox()
    next_btn = buttons.addButton("Next card", QDialogButtonBox.ButtonRole.ActionRole)
    buttons.addButton(QDialogButtonBox.StandardButton.Close)
    layout.addWidget(buttons)

    state = {"idx": 0, "cid": None}

    def refresh_footer() -> None:
        correct, attempts = results_summary(col)
        acc = paraphrase_accuracy(correct, attempts)
        if acc is None:
            footer.setText(
                f"Measured Performance: {attempts}/{MIN_PARAPHRASE_ATTEMPTS} answers "
                f"needed before it computes (so far {correct}/{attempts} correct). "
                "See Tools \u203a MCAT \u203a Readiness for the memory\u2192performance gap."
            )
        else:
            footer.setText(
                f"Measured Performance (paraphrase accuracy): {acc.percent_point}% "
                f"(95% CI {acc.percent_range_text}) over {attempts} answers. "
                "See Tools \u203a MCAT \u203a Readiness for the memory\u2192performance gap."
            )

    def load_card(i: int) -> None:
        cid, front, back = cards[i]
        state["cid"] = cid
        progress.setText(f"Card {i + 1} / {len(cards)}")
        qs = ai.paraphrase_questions({"front": front, "back": back}, [], live=None)
        for b, q in zip(blocks, qs):
            b["graded"] = False
            b["stem"].setText(q["stem"])
            b["answer"].setText("Answer: " + q["answer"])
            b["answer"].hide()
            b["reveal"].setEnabled(True)
            b["got"].setEnabled(False)
            b["missed"].setEnabled(False)
        next_btn.setEnabled(False)
        refresh_footer()

    def make_reveal(bi: int):
        def reveal() -> None:
            b = blocks[bi]
            b["answer"].show()
            if not b["graded"]:
                b["got"].setEnabled(True)
                b["missed"].setEnabled(True)
        return reveal

    def make_grader(bi: int, correct: bool):
        def grade() -> None:
            b = blocks[bi]
            if b["graded"]:
                return
            record_result(col, state["cid"], correct)
            b["graded"] = True
            b["answer"].show()
            b["reveal"].setEnabled(False)
            b["got"].setEnabled(False)
            b["missed"].setEnabled(False)
            refresh_footer()
            if all(bb["graded"] for bb in blocks):
                next_btn.setEnabled(True)
        return grade

    def go_next() -> None:
        if state["idx"] + 1 < len(cards):
            state["idx"] += 1
            load_card(state["idx"])
        else:
            tooltip("That was the last card in this deck.", parent=mw)

    for bi, b in enumerate(blocks):
        qconnect(b["reveal"].clicked, make_reveal(bi))
        qconnect(b["got"].clicked, make_grader(bi, True))
        qconnect(b["missed"].clicked, make_grader(bi, False))
    qconnect(next_btn.clicked, go_next)
    qconnect(buttons.rejected, dialog.reject)

    load_card(0)
    dialog.resize(600, 480)
    dialog.exec()


def _self_test() -> None:
    # Honesty gate: below the minimum there is no measured Performance.
    assert paraphrase_accuracy(4, 5) is None
    assert paraphrase_accuracy(0, 0) is None
    assert paraphrase_accuracy(MIN_PARAPHRASE_ATTEMPTS - 1, MIN_PARAPHRASE_ATTEMPTS - 1) is None

    # At/above the minimum: a valid, clamped 95% interval.
    r = paraphrase_accuracy(13, 20)
    assert r is not None
    assert 0.0 <= r.low <= r.point <= r.high <= 1.0, r
    assert abs(r.point - 0.65) < 1e-9, r.point

    # Pure transforms accumulate correct/attempts by source card id.
    st: dict = {}
    record_result_in(st, 42, True)
    record_result_in(st, 42, False)
    record_result_in(st, 7, True)
    assert summary_in(st) == (2, 3), summary_in(st)

    # Seeded demonstration: strong recall, weaker transfer => Performance \u2260 Memory.
    correct, attempts = summary_in(seeded_demo_state())
    assert attempts >= MIN_PARAPHRASE_ATTEMPTS, attempts
    acc = paraphrase_accuracy(correct, attempts)
    assert acc is not None
    gap = memory_performance_gap(SEEDED_MEMORY_POINT, acc.point)
    assert gap > 0, gap
    assert acc.point < SEEDED_MEMORY_POINT, (acc.point, SEEDED_MEMORY_POINT)

    print("mcat_paraphrase self-test: OK")
    print(
        f"  seeded: memory {round(SEEDED_MEMORY_POINT * 100)}% vs paraphrase "
        f"{acc.percent_point}% (95% CI {acc.percent_range_text}) over {attempts} "
        f"answers \u2192 memory\u2192performance gap {round(gap * 100)}% "
        "(Performance is measured, not copied from Memory)"
    )


if __name__ == "__main__":
    _self_test()
