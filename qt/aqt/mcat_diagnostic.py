# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""MCAT diagnostic: a short baseline quiz -> starting score -> honest projection.

Samples ~15 front/back cards across the MCAT decks, self-graded (Got it / Missed
it), then maps the measured accuracy onto the 472-528 scale for a STARTING score
and projects exam-day readiness over the remaining program. The plan is
aggressive by design; the projected number stays honest \u2014 a range + a stated
confidence (never "high" until validated) + an explicit abstain below the answer
minimum. If an ablation build is active, the diagnostic doubles as that build's
held-out quiz (feeding mcat_ablation).
"""

from __future__ import annotations

import random

from aqt import mcat_ablation as ab
from aqt import mcat_models as m
from aqt import mcat_paraphrase as pp
from aqt import mcat_today as today

DIAG_KEY = "mcat_diagnostic"
N_QUESTIONS = 15


def _sample_cards(col, n: int):  # type: ignore[no-untyped-def]
    """Up to ``n`` (card_id, front, back) tuples sampled across the MCAT decks."""
    from anki.utils import strip_html

    cids = list(col.find_cards("deck:MCAT* -is:suspended"))
    random.shuffle(cids)
    out: list[tuple] = []
    for cid in cids:
        try:
            note = col.get_card(cid).note()
        except Exception:
            continue
        if not note.fields:
            continue
        front = strip_html(note.fields[0]).strip()
        back = strip_html(note.fields[1]).strip() if len(note.fields) > 1 else ""
        if front and back:
            out.append((cid, front, back))
            if len(out) >= n:
                break
    return out


def _days_remaining(col):  # type: ignore[no-untyped-def]
    cal = today.ensure_started(col)
    horizon = cal["horizon_days"]
    di = today.effective_day_index(
        cal["start_date"], today._today_str(), today.get_day_override(col)
    )
    return max(0, horizon - di), horizon


def _pct_on_scale(point: int) -> float:
    return (point - m.SCALE_MIN) / (m.SCALE_MAX - m.SCALE_MIN)


def _result_html(col, correct: int, attempts: int) -> str:  # type: ignore[no-untyped-def]
    from aqt import mcat_ui as ui

    acc = pp.paraphrase_accuracy(correct, attempts)  # ScoreRange | None
    days_remaining, horizon = _days_remaining(col)
    conf = m.projection_confidence(attempts, days_remaining, horizon)
    head = "<h2>Diagnostic \u2014 baseline &amp; 30-day projection</h2>"
    if acc is None:
        return (
            head
            + f"<p>You answered <b>{correct}/{attempts}</b>. A diagnostic needs "
            f"\u2265{m.DIAGNOSTIC_MIN_ANSWERS} answers before it computes a score.</p>"
            + f"<p style='color:{ui.WARN}'><b>No projection \u2014 not enough data</b> "
            "(honest abstain). Answer a few more and re-run.</p>"
        )
    starting = m.readiness_projection(acc)
    proj = m.project_readiness(acc, days_remaining, horizon)
    parts = [
        head,
        f"<p>Diagnostic accuracy: <b>{acc.percent_point}%</b> "
        f"(95% CI {acc.percent_range_text}) over {attempts} answers.</p>",
        f"<p><b>Starting readiness</b> (today): "
        f"<b style='color:{ui.ACCENT}'>{starting.range_text}</b> on MCAT 472\u2013528"
        f"{ui.bar(_pct_on_scale(starting.point), ui.ACCENT)}</p>",
    ]
    if proj is not None:
        parts.append(
            f"<p><b>Projected exam-day readiness</b> after {days_remaining} program "
            f"day(s) of adherence: <b style='color:{ui.GOOD}'>{proj.range_text}</b> "
            f"(confidence: <b>{conf}</b>){ui.bar(_pct_on_scale(proj.point), ui.GOOD)}</p>"
        )
    parts.append(
        f"<p style='color:{ui.MUTED}'>The 30-day plan is aggressive by design, but the "
        "projection stays honest: a range, a stated confidence (never \u201chigh\u201d until "
        "validated against real outcomes), and an abstain when data is thin. It assumes "
        "daily adherence and is not a guarantee.</p>"
    )
    build = ab.active_build(col)
    if build and attempts:
        parts.append(
            f"<p style='color:{ui.MUTED}'>Recorded as build <b>{build}</b>'s held-out "
            "quiz for the study-feature ablation.</p>"
        )
    return "".join(parts)


def _finish(mw, correct: int, attempts: int) -> None:  # type: ignore[no-untyped-def]
    from aqt import mcat_ui as ui

    col = mw.col
    col.set_config(
        DIAG_KEY,
        {"correct": int(correct), "attempts": int(attempts), "date": today._today_str()},
    )
    build = ab.active_build(col)
    if build and attempts:
        ab.record_quiz(col, build, int(correct), int(attempts))
    ui.show_html(mw, "Diagnostic", _result_html(col, correct, attempts))


def show(mw) -> None:  # type: ignore[no-untyped-def]
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button, showInfo

    col = mw.col
    cards = _sample_cards(col, N_QUESTIONS)
    if len(cards) < m.DIAGNOSTIC_MIN_ANSWERS:
        showInfo(
            f"A diagnostic needs at least {m.DIAGNOSTIC_MIN_ANSWERS} front/back MCAT "
            f"cards; found {len(cards)}. Generate or import more cards and try again.",
            parent=mw,
        )
        return

    dialog = QDialog(mw)
    dialog.setWindowTitle("MCAT Diagnostic")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)
    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            "Answer each from memory, reveal the key, and grade yourself honestly. "
            f"{len(cards)} questions across your MCAT decks \u2014 this sets your baseline "
            "and a 30-day projection."
        )
    )
    progress = QLabel("")
    progress.setEnabled(False)
    layout.addWidget(progress)

    stem = QLabel("")
    stem.setWordWrap(True)
    sfont = stem.font()
    sfont.setPointSize(sfont.pointSize() + 2)
    stem.setFont(sfont)
    layout.addWidget(stem)

    answer = QLabel("")
    answer.setWordWrap(True)
    answer.setEnabled(False)
    layout.addWidget(answer)

    row = QHBoxLayout()
    reveal = QPushButton("Show answer")
    got = QPushButton("Got it")
    missed = QPushButton("Missed it")
    for b in (reveal, got, missed):
        b.setAutoDefault(False)
        row.addWidget(b)
    layout.addLayout(row)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(buttons)

    st = {"i": 0, "correct": 0, "attempts": 0}
    shown = {"v": False}

    def finish_once() -> None:
        if shown["v"]:
            return
        shown["v"] = True
        _finish(mw, st["correct"], st["attempts"])

    def load() -> None:
        i = st["i"]
        if i >= len(cards):
            dialog.accept()  # -> finished -> finish_once
            return
        progress.setText(
            f"Question {i + 1} of {len(cards)}  \u00b7  score so far "
            f"{st['correct']}/{st['attempts']}"
        )
        stem.setText(cards[i][1])
        answer.setText("")
        got.setEnabled(False)
        missed.setEnabled(False)
        reveal.setEnabled(True)

    def do_reveal() -> None:
        answer.setText("Key: " + cards[st["i"]][2])
        got.setEnabled(True)
        missed.setEnabled(True)
        reveal.setEnabled(False)

    def grade(ok: bool) -> None:
        st["attempts"] += 1
        if ok:
            st["correct"] += 1
        st["i"] += 1
        load()

    qconnect(reveal.clicked, do_reveal)
    qconnect(got.clicked, lambda: grade(True))
    qconnect(missed.clicked, lambda: grade(False))
    # show results on completion OR early close, as long as anything was answered
    qconnect(dialog.finished, lambda _c: finish_once() if st["attempts"] else None)

    load()
    dialog.resize(560, 340)
    dialog.exec()
