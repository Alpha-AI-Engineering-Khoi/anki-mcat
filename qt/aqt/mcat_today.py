# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The MCAT Today / Calendar program shell — the front door.

Turns the loose MCAT toolkit into a guided, time-boxed program that answers one
question: "what do I do right now?" One panel shows today's phase, today's
topic, the stage tasks (Spark -> Synapse -> Recall -> Ready) as
buttons into the features we already built, a one-line reflection, and a compact
readiness snapshot.

Everything schedule-shaped is pure and unit-testable so the Qt panel stays thin:

- the program calendar (start date + horizon) lives in collection config so it
  SYNCS, stored via the same ``*_in(state, ...)`` pure-dict + ``col``-bound
  wrapper pattern as ``mcat_program``;
- ``day_index`` / ``phase_for`` / ``topic_for_day`` / ``day_plan`` are pure
  functions of the day number and horizon (topics injectable so the self-test
  needs no collection or Qt).

The horizon is parameterized (default 28 days): the first ~75% is
encode-dominant (Prime/Connect/Build the sequenced topics), the final ~25% is
recall-dominant (interleaved review, no new encoding), with one Consolidate day
per 7. Run this file directly for an assert-based self-check of that logic.
"""

from __future__ import annotations

from datetime import date, timedelta

# ponytail: the calendar lives in collection config (col.get_config/set_config)
# under one key, exactly like mcat_program/mcat_ablation — config already syncs
# and holds arbitrary JSON, so this is the lazy "persists and syncs" path. The
# same dict also holds per-day reflections under "reflect". Ceiling: no history
# of past horizons; changing the exam date just rewrites the single record.
CAL_KEY = "mcat_program_cal"
DEFAULT_HORIZON = 28

# Encode-dominant for the first ~75% of the horizon (weeks 1-3 of a 28-day run),
# recall-dominant for the final ~25% (week 4). One Consolidate day per 7.
ENCODE_FRACTION = 0.75

PHASE_ENCODE = "Encode"
PHASE_RECALL = "Recall"
PHASE_CONSOLIDATE = "Consolidate"

# The stage tasks the panel surfaces as buttons: Spark -> Synapse -> Recall ->
# Ready (the learning-science workflow; the old "Connect" step is dropped).
STAGES = ("Spark", "Synapse", "Recall", "Ready")

# Calendar cell colors per phase (light chip bg + accent), readable on either theme.
_PHASE_BG = {PHASE_ENCODE: "#e8ecfb", PHASE_RECALL: "#e7f6ec", PHASE_CONSOLIDATE: "#f3e9fb"}
_PHASE_ACCENT = {PHASE_ENCODE: "#4b56d2", PHASE_RECALL: "#1b9e57", PHASE_CONSOLIDATE: "#8a4fd0"}


# --- pure calendar math -----------------------------------------------------


def day_index(start_date: str, today: str) -> int:
    """0-based day number since ``start_date`` (both ``YYYY-MM-DD``).

    Clamped at 0 so a start set in the future never reads negative."""
    delta = (date.fromisoformat(today) - date.fromisoformat(start_date)).days
    return max(0, delta)


def phase_for(day_index: int, horizon: int) -> str:
    """The phase for a 0-based day: Encode (front ~75%), Recall (final ~25%),
    or Consolidate (every 7th day). Consolidate wins over the encode/recall
    split so each week ends on a checkpoint."""
    if horizon <= 0:
        horizon = DEFAULT_HORIZON
    if (day_index + 1) % 7 == 0:
        return PHASE_CONSOLIDATE
    encode_days = round(horizon * ENCODE_FRACTION)
    return PHASE_ENCODE if day_index < encode_days else PHASE_RECALL


def _interleave(topics: list) -> list:
    """Section-interleaved order: round-robin across the sections so consecutive
    days rotate sections instead of running 12 Chem/Phys topics back-to-back.

    ponytail: a stable section round-robin over the outline order — simple and
    defensible (spaces the four sections evenly). Ceiling: NOT difficulty- or
    prerequisite-ordered; a smarter syllabus could sequence by dependency."""
    buckets: dict[str, list] = {}
    for t in topics:
        buckets.setdefault(t.section_token, []).append(t)
    columns = list(buckets.values())
    order: list = []
    row = 0
    while len(order) < len(topics):
        progressed = False
        for column in columns:
            if row < len(column):
                order.append(column[row])
                progressed = True
        row += 1
        if not progressed:
            break  # safety; unreachable while len(order) < len(topics)
    return order


def _all_topics() -> list:
    """The real 50-topic list. Imported lazily so this module stays import-safe
    for the Qt-free / collection-free self-test (aqt's package init needs anki)."""
    from aqt import mcat_program as prog  # noqa: PLC0415

    return prog.all_topics()


def topic_for_day(day_index: int, topics: list | None = None):  # -> Topic
    """The sequenced topic for a 0-based day. Stable and always in range: the
    interleaved order is indexed modulo its length, so recall/consolidate days
    past the topic count still resolve to a real topic."""
    order = _interleave(topics if topics is not None else _all_topics())
    return order[day_index % len(order)]


def _blocks_for_phase(phase: str) -> list[dict]:
    """The ordered time-budget blocks for a phase, straight from the program.

    ponytail: fixed per-phase budgets as a dict literal, not a scheduler.
    Ceiling: minutes are identical every week (no taper toward the exam)."""
    if phase == PHASE_RECALL:
        return [
            {"stage": "Recall", "minutes": 90, "note": "full interleaved recall \u2014 no new encoding"},
            {"stage": "Ready", "minutes": 10, "note": "readiness check"},
        ]
    if phase == PHASE_CONSOLIDATE:
        return [
            {"stage": "Recall", "minutes": 75, "note": "interleave the week\u2019s topics"},
            {"stage": "Ready", "minutes": 15, "note": "\u224880% checkpoint"},
        ]
    return [
        {"stage": "Spark", "minutes": 20},
        {"stage": "Synapse", "minutes": 90},
        {"stage": "Recall", "minutes": 40},
        {"stage": "Reflect", "minutes": 5},
    ]


def day_plan(day_index: int, horizon: int, topics: list | None = None) -> dict:
    """Everything the panel needs for a 0-based day: phase, today's topic, and
    the ordered stage blocks with the plan's time budget."""
    phase = phase_for(day_index, horizon)
    return {
        "day_index": day_index,
        "day_number": day_index + 1,
        "horizon": horizon,
        "phase": phase,
        "topic": topic_for_day(day_index, topics),
        "blocks": _blocks_for_phase(phase),
    }


# --- pure calendar state (dict transforms) ----------------------------------


def get_start_date_in(state: dict, today: str) -> str:
    return state.get("start_date") or today


def get_horizon_in(state: dict) -> int:
    try:
        horizon = int(state.get("horizon_days") or DEFAULT_HORIZON)
    except (TypeError, ValueError):
        horizon = DEFAULT_HORIZON
    return max(1, horizon)


def set_program_in(state: dict, start_date: str, horizon_days: int) -> dict:
    """Set start date + horizon, preserving any saved reflections."""
    state["start_date"] = start_date
    state["horizon_days"] = max(1, int(horizon_days))
    return state


def get_reflect_in(state: dict, date_str: str) -> str:
    return (state.get("reflect") or {}).get(date_str, "")


def set_reflect_in(state: dict, date_str: str, text: str) -> dict:
    reflect = state.setdefault("reflect", {})
    reflect[date_str] = text
    return state


# --- dev-only day override (program time-travel for testing) -----------------
# When set, the program acts as if today were this 0-based day, so the whole
# timeline (phase, topic, calendar, stage gating) can be tested without waiting
# real days. Cleared -> back to the real date. Lives in the same synced config.


def get_day_override_in(state: dict) -> int | None:
    v = state.get("dev_day_override")
    return int(v) if isinstance(v, int) else None


def set_day_override_in(state: dict, day: int | None) -> dict:
    if day is None:
        state.pop("dev_day_override", None)
    else:
        state["dev_day_override"] = max(0, int(day))
    return state


def effective_day_index(start_date: str, today: str, override: int | None) -> int:
    """The day the program should render: the dev override if set, else real."""
    return override if override is not None else day_index(start_date, today)


# --- collection-bound wrappers ----------------------------------------------


def _today_str() -> str:
    return date.today().isoformat()


def _load(col) -> dict:  # type: ignore[no-untyped-def]
    return col.get_config(CAL_KEY, {}) or {}


def get_cal(col) -> dict:  # type: ignore[no-untyped-def]
    state = _load(col)
    return {
        "start_date": get_start_date_in(state, _today_str()),
        "horizon_days": get_horizon_in(state),
    }


def set_cal(col, start_date: str, horizon_days: int):  # type: ignore[no-untyped-def]
    state = set_program_in(_load(col), start_date, horizon_days)
    return col.set_config(CAL_KEY, state)


def ensure_started(col) -> dict:  # type: ignore[no-untyped-def]
    """Persist a start date on first open so the program actually starts counting
    from today (default horizon), then return the calendar."""
    state = _load(col)
    if not state.get("start_date"):
        set_program_in(state, _today_str(), get_horizon_in(state))
        col.set_config(CAL_KEY, state)
    return {
        "start_date": state["start_date"],
        "horizon_days": get_horizon_in(state),
    }


def get_reflect(col, date_str: str) -> str:  # type: ignore[no-untyped-def]
    return get_reflect_in(_load(col), date_str)


def save_reflect(col, date_str: str, text: str):  # type: ignore[no-untyped-def]
    state = set_reflect_in(_load(col), date_str, text)
    return col.set_config(CAL_KEY, state)


def get_day_override(col) -> int | None:  # type: ignore[no-untyped-def]
    return get_day_override_in(_load(col))


def set_day_override(col, day: int | None):  # type: ignore[no-untyped-def]
    state = set_day_override_in(_load(col), day)
    return col.set_config(CAL_KEY, state)


def studied_today(col) -> bool:  # type: ignore[no-untyped-def]
    """True if any card was reviewed today (the Recall stage marker).

    ponytail: one collection-wide revlog count against the scheduler's day
    cutoff — the lazy "did I study today?" signal. Ceiling: not deck-scoped, so
    reviewing any deck counts."""
    try:
        cutoff_ms = (col.sched.day_cutoff - 86400) * 1000
        count = col.db.scalar("select count() from revlog where id >= ?", cutoff_ms)
        return bool(count)
    except Exception:
        return False


# --- the Today panel (Qt) ---------------------------------------------------


def _stage_hint(plan: dict, stage: str) -> str:
    for block in plan["blocks"]:
        if block["stage"] == stage:
            note = block.get("note")
            return f"{block['minutes']}m" + (f" \u00b7 {note}" if note else "")
    return "not scheduled today"


def _snapshot_text(assessment) -> str:
    """The compact inline snapshot: top-3 scores, or the abstain message."""
    if assessment is None:
        return "Ready snapshot: computing\u2026"
    if not assessment.is_scored:
        return "Ready snapshot: no score yet \u2014 " + assessment.best_next_thing
    return (
        f"Memory {assessment.memory.percent_range_text} \u00b7 "
        f"Performance {assessment.performance.percent_range_text} \u00b7 "
        f"Readiness {assessment.readiness.range_text}"
    )


def _snapshot_html(assessment) -> str:
    """A compact readiness snapshot for the Ready button (reuses mcat_ui + the
    shared score model — the full breakdown lives in mcat_readiness). Scored
    whole-collection (all MCAT cards), matching the Readiness dashboard."""
    from aqt import mcat_models as m  # noqa: PLC0415
    from aqt import mcat_ui as ui  # noqa: PLC0415

    head = "<h2>Ready snapshot \u2014 all MCAT cards</h2>"
    if not assessment.is_scored:
        return (
            head
            + "<h3>No score yet \u2014 not enough data</h3>"
            + f"<p style='color:{ui.MUTED}'>{ui.esc(m.GIVE_UP_RULE)}</p>"
            + f"<p><b>Best next thing:</b> {ui.esc(assessment.best_next_thing)}</p>"
        )
    mem, perf, rdy = assessment.memory, assessment.performance, assessment.readiness
    scale = (rdy.point - m.SCALE_MIN) / (m.SCALE_MAX - m.SCALE_MIN)
    return (
        head
        + f"<p><b style='color:{ui.GOOD}'>Memory {mem.percent_range_text}</b> "
        f"(\u2248{mem.percent_point}%){ui.bar(mem.point, ui.GOOD)}</p>"
        + f"<p><b style='color:{ui.WARN}'>Performance {perf.percent_range_text}</b> "
        f"(\u2248{perf.percent_point}%){ui.bar(perf.point, ui.WARN)}</p>"
        + f"<p><b style='color:{ui.ACCENT}'>Readiness {rdy.range_text}</b> "
        f"\u00b7 MCAT 472\u2013528{ui.bar(scale, ui.ACCENT)}</p>"
        + f"<p><b>Best next thing:</b> {ui.esc(assessment.best_next_thing)}</p>"
    )


def home_html(col) -> str:  # type: ignore[no-untyped-def]
    """Compact program dashboard prepended to the deck-browser home page (the real
    front door): Day N of H, phase + topic, a phase-colored calendar with today
    ringed, and quick actions. Read-only (uses ``get_cal`` — no writes in the
    render path); clicks route through ``pycmd('mcat-home:...')`` handled in
    main.py. The caller guards against exceptions so this can never break the
    home page."""
    import html as _html  # noqa: PLC0415

    from aqt import mcat_program as prog  # noqa: PLC0415

    cal = get_cal(col)
    horizon = cal["horizon_days"]
    di = effective_day_index(cal["start_date"], _today_str(), get_day_override(col))
    topics = prog.all_topics()
    done = di >= horizon
    show_day = di if not done else horizon - 1
    plan = day_plan(show_day, horizon, topics)
    topic = plan["topic"]
    phase = plan["phase"]
    accent = _PHASE_ACCENT.get(phase, "#4b56d2")

    head_day = (
        f"Program complete \u2014 {horizon}-day plan finished"
        if done
        else f"Day {di + 1} of {horizon}"
    )
    topic_line = (
        ""
        if done
        else (
            f"<div style='font-size:13px;opacity:.8;margin-top:3px'>{phase} \u00b7 "
            f"{_html.escape(topic.section)} \u00b7 <b>{_html.escape(topic.name)}</b></div>"
        )
    )

    cells = []
    for d in range(horizon):
        p = phase_for(d, horizon)
        bg = _PHASE_BG.get(p, "#eee")
        ac = _PHASE_ACCENT.get(p, "#888")
        is_today = (not done) and d == di
        border = f"2px solid {ac}" if is_today else "1px solid rgba(128,128,128,.35)"
        weight = "800" if is_today else "500"
        cells.append(
            f"<a href=# onclick=\"pycmd('mcat-home:day:{d}');return false\" "
            f'title="Day {d + 1} \u00b7 {p}" '
            f"style=\"display:flex;align-items:center;justify-content:center;"
            f"width:34px;height:28px;background:{bg};border:{border};border-radius:6px;"
            f'color:#222;font-weight:{weight};font-size:12px;text-decoration:none">{d + 1}</a>'
        )
    grid = (
        "<div style='display:grid;grid-template-columns:repeat(7,34px);gap:4px;"
        "justify-content:center;margin:10px 0'>" + "".join(cells) + "</div>"
    )

    def _chip(label: str, p: str) -> str:
        return (
            f"<span style='background:{_PHASE_BG[p]};border:1px solid {_PHASE_ACCENT[p]};"
            f"padding:1px 6px;border-radius:4px;color:#222;font-size:11px'>{label}</span>"
        )

    legend = (
        _chip("Encode", PHASE_ENCODE) + " " + _chip("Recall", PHASE_RECALL) + " "
        + _chip("Consolidate", PHASE_CONSOLIDATE) + " &nbsp;<b>ring = today</b>"
    )

    def _btn(label: str, cmd: str) -> str:
        return (
            f"<a href=# onclick=\"pycmd('mcat-home:{cmd}');return false\" "
            f"style='display:inline-block;padding:6px 14px;margin:0 4px;border-radius:7px;"
            f"background:{accent};color:#fff;font-weight:600;font-size:12px;"
            f"text-decoration:none'>{label}</a>"
        )

    actions = (
        _btn("Open program \u25b8", "today")
        + _btn("Diagnostic", "diagnostic")
        + _btn("Readiness", "readiness")
    )

    return (
        "<div style=\"max-width:640px;margin:18px auto 8px;padding:14px 18px;"
        "border:1px solid rgba(128,128,128,.3);border-radius:12px;"
        "background:linear-gradient(180deg,rgba(75,86,210,.08),rgba(75,86,210,0))\">"
        "<div style='display:flex;justify-content:space-between;align-items:baseline'>"
        "<div style='font-size:16px;font-weight:800'>MCAT program</div>"
        f"<div style='font-size:13px;opacity:.7'>{head_day}</div></div>"
        f"{topic_line}{grid}"
        f"<div style='text-align:center;opacity:.75;margin-bottom:10px'>{legend}</div>"
        f"<div style='text-align:center'>{actions}</div>"
        "</div>"
    )


def show(mw) -> None:  # type: ignore[no-untyped-def]
    """The Today front door: today's phase + topic, the five stage buttons, a
    daily reflection, a progress line, and a compact readiness snapshot."""
    from aqt import mcat_ablation as ab  # noqa: PLC0415
    from aqt import mcat_encode as encode  # noqa: PLC0415
    from aqt import mcat_models as m  # noqa: PLC0415
    from aqt import mcat_program as prog  # noqa: PLC0415
    from aqt import mcat_ui as ui  # noqa: PLC0415
    from aqt.operations import QueryOp  # noqa: PLC0415
    from aqt.qt import (  # noqa: PLC0415
        QDialog,
        QDialogButtonBox,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QPushButton,
        QVBoxLayout,
        Qt,
        qconnect,
    )
    from aqt.utils import disable_help_button, showWarning, tooltip  # noqa: PLC0415

    col = mw.col
    today = _today_str()
    cal = ensure_started(col)

    def eff_di() -> int:
        return effective_day_index(cal["start_date"], _today_str(), get_day_override(col))

    holder: dict = {"assessment": None}
    ready_shown = {"v": False}
    alive = {"v": True}

    dialog = QDialog(mw)
    dialog.setWindowTitle("MCAT Today")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)

    header = QLabel("")
    header_font = header.font()
    header_font.setPointSize(header_font.pointSize() + 3)
    header_font.setBold(True)
    header.setFont(header_font)
    layout.addWidget(header)

    subhead = QLabel("")
    subhead.setWordWrap(True)
    layout.addWidget(subhead)

    dev_banner = QLabel("")
    dev_banner.setWordWrap(True)
    dev_banner.setStyleSheet(
        "background:#fff4d6; border:1px solid #f0c96b; border-radius:6px; "
        "padding:3px 8px; color:#7a5300;"
    )
    dev_banner.setVisible(False)
    layout.addWidget(dev_banner)

    plan_line = QLabel("")
    plan_line.setEnabled(False)
    plan_line.setWordWrap(True)
    layout.addWidget(plan_line)

    # --- 30-day program calendar (tap a day to preview its plan) ---
    cal_head = QLabel("Program calendar \u2014 tap a day to preview")
    cal_head_font = cal_head.font()
    cal_head_font.setBold(True)
    cal_head.setFont(cal_head_font)
    layout.addWidget(cal_head)

    cal_wrap = QFrame()
    cal_grid = QGridLayout(cal_wrap)
    cal_grid.setSpacing(3)
    cal_grid.setContentsMargins(0, 2, 0, 2)
    layout.addWidget(cal_wrap)

    def _swatch(text: str, phase: str) -> str:
        return (
            f"<span style='background:{_PHASE_BG[phase]};border:1px solid "
            f"{_PHASE_ACCENT[phase]};padding:1px 6px;border-radius:4px;color:#222'>{text}</span>"
        )

    legend = QLabel(
        _swatch("Encode", PHASE_ENCODE) + " " + _swatch("Recall", PHASE_RECALL)
        + " " + _swatch("Consolidate", PHASE_CONSOLIDATE)
        + " &nbsp; <b>ring = today</b>"
    )
    legend.setTextFormat(Qt.TextFormat.RichText)
    layout.addWidget(legend)

    def preview_day(d: int) -> None:
        plan = day_plan(d, cal["horizon_days"], prog.all_topics())
        topic = plan["topic"]
        blocks = "  ".join(f"{b['stage']} {b['minutes']}m" for b in plan["blocks"])
        tooltip(
            f"Day {d + 1} \u00b7 {plan['phase']} \u2014 {topic.section} \u00b7 {topic.name}\n{blocks}",
            parent=mw,
            period=4000,
        )

    def rebuild_calendar() -> None:
        while cal_grid.count():
            item = cal_grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        topics = prog.all_topics()
        horizon = cal["horizon_days"]
        di_today = eff_di()
        cols = 7
        for d in range(horizon):
            plan = day_plan(d, horizon, topics)
            phase = plan["phase"]
            topic = plan["topic"]
            cell = QPushButton(str(d + 1))
            cell.setFixedSize(48, 38)
            cell.setAutoDefault(False)
            cell.setDefault(False)
            is_today = d == di_today
            accent = _PHASE_ACCENT.get(phase, "#888")
            bg = _PHASE_BG.get(phase, "#eeeeee")
            border = f"2px solid {accent}" if is_today else "1px solid #d7d9e6"
            weight = "700" if is_today else "500"
            cell.setStyleSheet(
                f"QPushButton {{ background:{bg}; border:{border}; border-radius:6px; "
                f"color:#222; font-weight:{weight}; }} "
                f"QPushButton:hover {{ border:2px solid {accent}; }}"
            )
            cell.setToolTip(f"Day {d + 1} \u00b7 {phase}\n{topic.section} \u00b7 {topic.name}")
            qconnect(cell.clicked, lambda _=False, dd=d: preview_day(dd))
            r, c = divmod(d, cols)
            cal_grid.addWidget(cell, r, c)

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setEnabled(False)
    layout.addWidget(line)

    # --- five stage rows ---
    grid = QGridLayout()
    layout.addLayout(grid)
    markers: dict[str, QLabel] = {}
    hints: dict[str, QLabel] = {}
    stage_buttons: dict = {}

    def add_row(index: int, stage: str, button_text: str, on_click) -> None:
        marker = QLabel("\u2014")
        marker.setFixedWidth(16)
        name = QLabel(stage)
        name_font = name.font()
        name_font.setBold(True)
        name.setFont(name_font)
        name.setFixedWidth(80)
        hint = QLabel("")
        hint.setEnabled(False)
        button = QPushButton(button_text)
        button.setFixedWidth(150)
        grid.addWidget(marker, index, 0)
        grid.addWidget(name, index, 1)
        grid.addWidget(hint, index, 2)
        grid.addWidget(button, index, 3)
        markers[stage] = marker
        hints[stage] = hint
        stage_buttons[stage] = button
        qconnect(button.clicked, on_click)

    def current_topic():
        di = eff_di()
        return topic_for_day(di, prog.all_topics())

    def open_encode(stage: str):
        encode.open_for(mw, current_topic(), stage)
        refresh()

    def open_recall():
        # ponytail: land on the current deck's study/overview screen — Anki
        # starts the actual review from there. Robust with no due cards / AI off,
        # unlike jumping straight into "review". Ceiling: one extra click to
        # begin. Close Today so the main window is visible.
        col.startTimebox()
        mw.moveToState("overview")
        dialog.accept()

    def open_ready():
        ready_shown["v"] = True
        cached = holder.get("assessment")
        if cached is not None:
            ui.show_html(mw, "Ready snapshot", _snapshot_html(cached))
            refresh()
            return

        def on_ok(assessment) -> None:
            holder["assessment"] = assessment
            ui.show_html(mw, "Ready snapshot", _snapshot_html(assessment))
            if alive["v"]:
                snapshot.setText(_snapshot_text(assessment))
                refresh()

        QueryOp(parent=mw, op=lambda c: m.assess(c), success=on_ok).with_progress(
            "Scoring\u2026"
        ).failure(
            lambda e: showWarning(f"Could not compute readiness: {e}", parent=mw)
        ).run_in_background()

    add_row(0, "Spark", "Spark\u2026", lambda: open_encode("prime"))
    add_row(1, "Synapse", "Synapse\u2026", lambda: open_encode("build"))
    add_row(2, "Recall", "Study now\u2026", open_recall)
    add_row(3, "Ready", "Check readiness\u2026", open_ready)

    line2 = QFrame()
    line2.setFrameShape(QFrame.Shape.HLine)
    line2.setEnabled(False)
    layout.addWidget(line2)

    # --- daily reflection ---
    layout.addWidget(QLabel("Reflect \u2014 what will I change 1%?"))
    reflect_edit = QLineEdit(get_reflect(col, today))
    reflect_edit.setPlaceholderText("One small change for tomorrow (saved for today)\u2026")
    layout.addWidget(reflect_edit)

    def save_reflection() -> None:
        save_reflect(col, today, reflect_edit.text().strip())

    qconnect(reflect_edit.editingFinished, save_reflection)

    # --- progress + snapshot ---
    progress = QLabel("")
    layout.addWidget(progress)

    snapshot = QLabel(_snapshot_text(None))
    snapshot.setWordWrap(True)
    layout.addWidget(snapshot)

    # --- footer buttons ---
    buttons = QDialogButtonBox()
    settings_btn = buttons.addButton(
        "Set exam date\u2026", QDialogButtonBox.ButtonRole.ActionRole
    )
    buttons.addButton(QDialogButtonBox.StandardButton.Close)
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(buttons)

    def edit_settings() -> None:
        current = get_cal(col)
        start = date.fromisoformat(current["start_date"])
        exam_default = (start + timedelta(days=current["horizon_days"])).isoformat()
        text, ok = QInputDialog.getText(
            dialog,
            "Set exam date",
            "Exam date (YYYY-MM-DD):",
            text=exam_default,
        )
        if not ok:
            return
        try:
            exam = date.fromisoformat(text.strip())
        except ValueError:
            showWarning("Enter the exam date as YYYY-MM-DD.", parent=dialog)
            return
        horizon = max(1, (exam - start).days)
        set_cal(col, current["start_date"], horizon)
        cal["horizon_days"] = horizon
        tooltip(f"Exam in {horizon} day(s) \u2014 horizon set to {horizon}.", parent=mw)
        rebuild_calendar()
        refresh()

    qconnect(settings_btn.clicked, edit_settings)

    def refresh() -> None:
        di = eff_di()
        horizon = cal["horizon_days"]
        plan = day_plan(di, horizon, prog.all_topics())
        topic = plan["topic"]

        tail = " \u00b7 program complete" if di >= horizon else ""
        header.setText(f"Day {plan['day_number']} of {horizon} \u00b7 {plan['phase']}{tail}")
        subhead.setText(f"Today\u2019s topic: {topic.section} \u00b7 {topic.name}")
        plan_line.setText(
            "Plan: "
            + "   ".join(f"{b['stage']} {b['minutes']}m" for b in plan["blocks"])
        )

        rec = prog.get_record(col, topic)
        done = {
            "Spark": bool(rec.get("primed")),
            "Synapse": len(rec.get("concepts", [])) > 0,
            "Recall": studied_today(col),
            "Ready": ready_shown["v"],
        }
        for stage in STAGES:
            markers[stage].setText("\u2713" if done[stage] else "\u2014")
            hints[stage].setText(_stage_hint(plan, stage))

        # dev: the ablation build gates the encode stages; a day override retitles.
        build = ab.active_build(col)
        enc_on = ab.encode_enabled(col)
        for st in ("Spark", "Synapse"):
            stage_buttons[st].setEnabled(enc_on)
            if not enc_on:
                hints[st].setText(f"off in build {build}")
        override = get_day_override(col)
        bits = []
        if override is not None:
            bits.append(f"DEV \u2014 viewing day {override + 1} of {horizon} (not the real date)")
        if build:
            bits.append(
                f"Build {build}: {ab.BUILDS[build].name} \u00b7 encode {'on' if enc_on else 'off'}"
            )
        dev_banner.setText("      ".join(bits))
        dev_banner.setVisible(bool(bits))

        progress.setText(f"Stages done today: {sum(done.values())} / {len(STAGES)}")

    def on_finished(_code: int) -> None:
        alive["v"] = False
        save_reflection()

    qconnect(dialog.finished, on_finished)

    def on_assessed(assessment) -> None:
        holder["assessment"] = assessment
        if alive["v"]:
            snapshot.setText(_snapshot_text(assessment))

    # Compute the inline snapshot in the background so opening stays snappy.
    QueryOp(parent=mw, op=lambda c: m.assess(c), success=on_assessed).failure(
        lambda _e: None
    ).run_in_background()

    rebuild_calendar()
    refresh()
    dialog.resize(640, 720)
    dialog.exec()


# --- self-test (pure logic; no Qt, no collection) ---------------------------


def _self_test() -> None:
    from collections import namedtuple

    Stub = namedtuple("Stub", "section_token token")
    # 4 sections of uneven size (12/11/14/13-ish), like the real outline.
    fake = (
        [Stub("ChemPhys", f"cp{i}") for i in range(12)]
        + [Stub("CARS", f"ca{i}") for i in range(11)]
        + [Stub("BioBiochem", f"bb{i}") for i in range(14)]
        + [Stub("PsychSoc", f"ps{i}") for i in range(13)]
    )
    assert len(fake) == 50

    # day_index: 0-based, clamps at 0.
    assert day_index("2026-01-01", "2026-01-01") == 0
    assert day_index("2026-01-01", "2026-01-08") == 7
    assert day_index("2026-01-10", "2026-01-01") == 0  # future start -> clamp

    # phase_for: encode-dominant front, recall-dominant tail, Consolidate per 7.
    h = 28
    encode_days = round(h * ENCODE_FRACTION)  # 21
    assert phase_for(0, h) == PHASE_ENCODE
    assert phase_for(encode_days - 2, h) == PHASE_ENCODE  # day 20
    # the encode->recall boundary: week-3 ends on a Consolidate, then Recall.
    assert phase_for(encode_days - 1, h) == PHASE_CONSOLIDATE  # day 21 (idx 20)
    assert phase_for(encode_days, h) == PHASE_RECALL  # day 22 (idx 21)
    assert phase_for(h - 1, h) == PHASE_CONSOLIDATE  # day 28 closes on checkpoint
    # every 7th day is a Consolidate day.
    for wk in range(1, 5):
        assert phase_for(wk * 7 - 1, h) == PHASE_CONSOLIDATE
    # a shorter horizon still splits ~75/25.
    assert phase_for(0, 14) == PHASE_ENCODE
    assert phase_for(13, 14) == PHASE_CONSOLIDATE
    assert phase_for(11, 14) == PHASE_RECALL  # round(14*0.75)=11 -> idx 11 recall

    # topic_for_day: stable and always in range, even past the topic count.
    seq = _interleave(fake)
    assert len(seq) == len(fake) and set(seq) == set(fake)  # a permutation
    assert seq[0].section_token != seq[1].section_token  # sections interleave
    first = topic_for_day(0, fake)
    assert topic_for_day(0, fake) == first  # stable across calls
    for d in range(0, 130):
        t = topic_for_day(d, fake)
        assert t in fake
    assert topic_for_day(len(fake), fake) == topic_for_day(0, fake)  # wraps

    # day_plan: encode day is the Spark->Synapse budget; recall day drops encoding.
    enc = day_plan(0, h, fake)
    assert enc["phase"] == PHASE_ENCODE
    assert [b["stage"] for b in enc["blocks"]] == [
        "Spark", "Synapse", "Recall", "Reflect",
    ]
    assert enc["day_number"] == 1 and enc["topic"] in fake
    rec = day_plan(encode_days, h, fake)  # first clean recall day (idx 21)
    assert rec["phase"] == PHASE_RECALL
    rec_stages = [b["stage"] for b in rec["blocks"]]
    assert "Spark" not in rec_stages and "Synapse" not in rec_stages
    assert "Recall" in rec_stages and "Ready" in rec_stages
    con = day_plan(6, h, fake)  # day 7 Consolidate
    assert con["phase"] == PHASE_CONSOLIDATE
    assert any("checkpoint" in (b.get("note") or "") for b in con["blocks"])

    # calendar state round-trips through a plain dict, preserving reflections.
    st: dict = {}
    assert get_horizon_in(st) == DEFAULT_HORIZON
    assert get_start_date_in(st, "2026-03-03") == "2026-03-03"
    set_program_in(st, "2026-01-01", 28)
    assert get_start_date_in(st, "2026-09-09") == "2026-01-01"
    assert get_horizon_in(st) == 28
    set_reflect_in(st, "2026-01-02", "sleep 8h")
    assert get_reflect_in(st, "2026-01-02") == "sleep 8h"
    # changing the exam date rewrites start/horizon but keeps reflections.
    set_program_in(st, "2026-02-01", 14)
    assert get_horizon_in(st) == 14
    assert get_reflect_in(st, "2026-01-02") == "sleep 8h"
    assert get_reflect_in(st, "2026-12-31") == ""  # unknown day -> empty
    # horizon is always sane: 0/blank -> default, negatives clamp to 1.
    assert get_horizon_in({"horizon_days": 0}) == DEFAULT_HORIZON
    assert get_horizon_in({"horizon_days": -5}) == 1
    assert get_horizon_in({"horizon_days": "oops"}) == DEFAULT_HORIZON

    print("mcat_today self-test: OK")
    print(
        f"  {h}-day horizon: days 1\u2013{encode_days} encode-dominant, "
        f"{encode_days + 1}\u2013{h} recall-dominant, Consolidate every 7th; "
        f"50 topics section-interleaved & stable"
    )


if __name__ == "__main__":
    _self_test()
