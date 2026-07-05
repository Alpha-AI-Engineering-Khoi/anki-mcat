# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""MCAT dev tools: program time-travel + the 3-mode ablation switch.

Two testing controls in one dialog (Tools -> MCAT -> Dev tools):

- Jump to day: override the program's "today" (a 0-based override in the synced
  calendar config) so the whole timeline \u2014 phase, topic, calendar, stage gating
  \u2014 can be exercised without waiting real days. Reset returns to the real date.
- Ablation build: run the app as build A (plain Anki), B (ablated), C (full), or
  Normal. The active build gates the encode workflow (mcat_ablation.encode_enabled)
  so a solo tester genuinely lives the ablated-vs-full loop; study time can then be
  attributed to that build in the ablation harness.

These are DEV controls; nothing here computes a score, so they can't touch the
readiness honesty gate.
"""

from __future__ import annotations

from aqt import mcat_ablation as ab
from aqt import mcat_today as today


def show(mw) -> None:  # type: ignore[no-untyped-def]
    from aqt.qt import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSpinBox,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button, tooltip

    col = mw.col
    cal = today.ensure_started(col)
    horizon = cal["horizon_days"]

    dialog = QDialog(mw)
    dialog.setWindowTitle("MCAT Dev tools")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)
    layout = QVBoxLayout(dialog)

    status = QLabel("")
    status.setWordWrap(True)
    sfont = status.font()
    sfont.setBold(True)
    status.setFont(sfont)
    layout.addWidget(status)

    # --- program time-travel ---
    layout.addWidget(
        QLabel("<b>Program time-travel</b> \u2014 jump to any day to test the timeline")
    )
    row = QHBoxLayout()
    row.addWidget(QLabel("Day:"))
    spin = QSpinBox()
    spin.setRange(1, horizon)
    row.addWidget(spin)
    jump_btn = QPushButton("Jump to day")
    reset_btn = QPushButton("Reset to real day")
    row.addWidget(jump_btn)
    row.addWidget(reset_btn)
    row.addStretch(1)
    layout.addLayout(row)

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setEnabled(False)
    layout.addWidget(line)

    # --- ablation build switch ---
    layout.addWidget(
        QLabel("<b>Ablation build</b> \u2014 run the app as a study-feature build")
    )
    note = QLabel(
        "A plain Anki (no Focus, no encode) \u00b7 B ablated (Focus on, encode off) \u00b7 "
        "C full (Focus + encode). The encode workflow is gated by build; Focus "
        "ordering is a known runtime limitation (kept on in every build)."
    )
    note.setWordWrap(True)
    note.setEnabled(False)
    layout.addWidget(note)

    brow = QHBoxLayout()
    normal_btn = QPushButton("Normal")
    a_btn = QPushButton("A \u00b7 plain")
    b_btn = QPushButton("B \u00b7 ablated")
    c_btn = QPushButton("C \u00b7 full")
    mode_btns = ((normal_btn, None), (a_btn, "A"), (b_btn, "B"), (c_btn, "C"))
    for btn, _val in mode_btns:
        btn.setCheckable(True)
        btn.setAutoDefault(False)
        btn.setDefault(False)
        brow.addWidget(btn)
    layout.addLayout(brow)

    line2 = QFrame()
    line2.setFrameShape(QFrame.Shape.HLine)
    line2.setEnabled(False)
    layout.addWidget(line2)

    # --- ablation pilot logging (record a study block + held-out quiz per build) ---
    layout.addWidget(
        QLabel("<b>Ablation pilot logging</b> \u2014 record a study block's minutes and a "
               "held-out quiz result to a build, then open the comparison")
    )
    log_row = QHBoxLayout()
    log_row.addWidget(QLabel("Build:"))
    build_combo = QComboBox()
    for bid in ab.BUILD_IDS:
        build_combo.addItem(f"{bid} \u00b7 {ab.BUILDS[bid].name}", bid)
    log_row.addWidget(build_combo)
    log_row.addWidget(QLabel("minutes:"))
    min_spin = QSpinBox()
    min_spin.setRange(0, 600)
    min_spin.setValue(25)
    log_row.addWidget(min_spin)
    min_btn = QPushButton("Log minutes")
    log_row.addWidget(min_btn)
    log_row.addStretch(1)
    layout.addLayout(log_row)

    quiz_row = QHBoxLayout()
    quiz_row.addWidget(QLabel("quiz correct:"))
    correct_spin = QSpinBox()
    correct_spin.setRange(0, 500)
    quiz_row.addWidget(correct_spin)
    quiz_row.addWidget(QLabel("/ attempts:"))
    attempts_spin = QSpinBox()
    attempts_spin.setRange(0, 500)
    attempts_spin.setValue(10)
    quiz_row.addWidget(attempts_spin)
    quiz_btn = QPushButton("Log quiz")
    quiz_row.addWidget(quiz_btn)
    results_btn = QPushButton("Open results\u2026")
    quiz_row.addWidget(results_btn)
    quiz_row.addStretch(1)
    layout.addLayout(quiz_row)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(buttons)

    def refresh() -> None:
        override = today.get_day_override(col)
        real_di = today.day_index(cal["start_date"], today._today_str())
        eff = override if override is not None else real_di
        build = ab.active_build(col)
        bname = f"{build} ({ab.BUILDS[build].name})" if build else "Normal (all features on)"
        day_txt = (
            f"Day {eff + 1} \u2014 DEV override"
            if override is not None
            else f"Day {real_di + 1} \u2014 real date"
        )
        enc = "ON" if ab.encode_enabled(col) else "OFF"
        status.setText(f"Now: {day_txt}  \u00b7  Build {bname}  \u00b7  encode workflow {enc}")
        spin.setValue(min(horizon, eff + 1))
        for btn, val in mode_btns:
            btn.setChecked(build == val)

    def do_jump() -> None:
        today.set_day_override(col, spin.value() - 1)
        tooltip(f"Jumped to day {spin.value()}.", parent=mw)
        refresh()

    def do_reset() -> None:
        today.set_day_override(col, None)
        tooltip("Back to the real day.", parent=mw)
        refresh()

    def set_build(build_id: str | None) -> None:
        ab.set_active_build(col, build_id)
        tooltip(f"Switched to {('build ' + build_id) if build_id else 'Normal'}.", parent=mw)
        refresh()

    def log_minutes() -> None:
        bid = build_combo.currentData()
        ab.record_session(col, bid, float(min_spin.value()))
        tooltip(f"Logged {min_spin.value()} min to build {bid}.", parent=mw)

    def log_quiz() -> None:
        bid = build_combo.currentData()
        c, a = correct_spin.value(), attempts_spin.value()
        if a <= 0 or c > a:
            tooltip("Need 0 \u2264 correct \u2264 attempts, and attempts > 0.", parent=mw)
            return
        ab.record_quiz(col, bid, c, a)
        tooltip(f"Logged quiz {c}/{a} to build {bid}.", parent=mw)

    def open_results() -> None:
        ab.show(mw)

    qconnect(jump_btn.clicked, do_jump)
    qconnect(reset_btn.clicked, do_reset)
    qconnect(normal_btn.clicked, lambda: set_build(None))
    qconnect(a_btn.clicked, lambda: set_build("A"))
    qconnect(b_btn.clicked, lambda: set_build("B"))
    qconnect(c_btn.clicked, lambda: set_build("C"))
    qconnect(min_btn.clicked, log_minutes)
    qconnect(quiz_btn.clicked, log_quiz)
    qconnect(results_btn.clicked, open_results)

    refresh()
    dialog.resize(620, 420)
    dialog.exec()
