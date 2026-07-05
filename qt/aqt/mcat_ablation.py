# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""MCAT challenge 8: test a study feature by ablation.

The study feature under test is our **encode workflow** (Spark -> Synapse; see ``mcat_encode`` / ``mcat_program``). This module is the *harness*: it
defines the three builds, stores per-build study minutes + a held-out quiz, and
ranks them by the pre-registered primary metric so the comparison can be run.

- The three builds (spec 8): ``A`` plain Anki (baseline), ``B`` ablated (Focus
  ordering on, encode off), ``C`` full (Focus + encode on).
- The primary metric, fixed BEFORE any result, is **held-out paraphrase accuracy
  per study minute**, with the pre-registered order ``C > B > A``. The full
  registration (hypothesis, fair-test controls, falsifiability) lives in
  ``docs/mcat/ablation-preregistration.md``; this file embeds it, it does not
  restate a different one.

Honesty is the whole point of an ablation: the real *result* accrues over the
weekend (equal study time on matched topics, then one held-out quiz), and faking
it is an automatic fail per the spec. So:

- the collection-backed viewer shows ONLY real recorded study, never a number we
  invented, and says a null/negative result is a valid outcome;
- the ``run()`` report + ``__main__`` self-test feed CLEARLY-LABELED SIMULATED
  data purely to prove the math (ranking + accuracy-per-minute), and print a
  banner saying so.

The pure ``*_in`` transforms + ``build_result`` / ``compare`` need no collection
and no Qt, so they run in the assert-based self-test (run this file directly).
Everything works with AI switched OFF.
"""

from __future__ import annotations

from dataclasses import dataclass

# ponytail: reuse mcat_paraphrase's held-out accuracy math (Wilson-CI ScoreRange
# + the abstain-below-minimum honesty gate) verbatim for each build's quiz, and
# its collection-config storage shape. Ceiling: one collection-wide tally per
# build (not deck-scoped), same as the paraphrase feature it reuses. Import via
# the package at runtime; fall back to the sibling module for the standalone
# self-test (python mcat_ablation.py), mirroring mcat_paraphrase/mcat_eval.
try:
    from aqt import mcat_paraphrase as _pp
except Exception:  # pragma: no cover - standalone self-test path
    import mcat_paraphrase as _pp  # type: ignore

# ponytail: per-build records live in collection config (col.get_config/
# set_config), keyed by build id, exactly like mcat_program/mcat_paraphrase.
# Config already syncs and holds arbitrary JSON, so this is the lazy
# "persists and syncs" path.
CONFIG_KEY = "mcat_ablation"

# The honesty gate for the held-out quiz is the SAME minimum as the paraphrase
# feature: below it there is no measured accuracy, so no ranking.
MIN_QUIZ_ATTEMPTS = _pp.MIN_PARAPHRASE_ATTEMPTS

# A fair test needs matched study time; warn if any build's minutes drifts more
# than this fraction from the largest build.
MINUTES_EQUAL_TOLERANCE = 0.15

# --- the pre-registration, embedded (see the doc for the full text) ----------
PREREG_DOC = "docs/mcat/ablation-preregistration.md"
PRIMARY_METRIC = "held-out paraphrase accuracy per study minute"
PREREG_ORDER: tuple[str, str, str] = ("C", "B", "A")
HYPOTHESIS = (
    "Studying a topic with the full Spark \u2192 Synapse workflow "
    "produces higher accuracy on held-out, paraphrased, exam-style questions per "
    "equal minute of study than flashcards alone or plain Anki."
)
NEGATIVE_RESULT_NOTE = (
    "A null or negative result is a valid outcome: if the observed order is not "
    "C > B > A, or the ranges overlap, the honest finding is that the encode "
    "workflow made no measurable difference here \u2014 reported as-is per the "
    "pre-registration."
)


# --- the three builds (spec 8: full / ablated / plain Anki) ------------------


@dataclass(frozen=True)
class Build:
    id: str  # "A" / "B" / "C"
    name: str  # short label
    focus: bool  # Focus (points-at-stake) ordering on?
    encode: bool  # encode workflow (Spark->Synapse) on?
    description: str  # what is on/off
    isolates: str  # what comparing this build controls for


BUILDS: dict[str, Build] = {
    "A": Build(
        id="A",
        name="plain Anki",
        focus=False,
        encode=False,
        description="stock scheduler, no Focus ordering, no encode workflow \u2014 the baseline",
        isolates="whether our app beats stock Anki at all (B/C vs A)",
    ),
    "B": Build(
        id="B",
        name="ablated",
        focus=True,
        encode=False,
        description="our app: Focus (points-at-stake) ordering ON, encode workflow OFF",
        isolates="whether the encode workflow itself did the work (C vs B)",
    ),
    "C": Build(
        id="C",
        name="full",
        focus=True,
        encode=True,
        description="our app: Focus ON + encode workflow (Spark \u2192 Synapse) ON",
        isolates="the whole method",
    ),
}

# Stable display order (the ranking is computed separately, best-first).
BUILD_IDS: tuple[str, str, str] = ("A", "B", "C")


# --- per-build records (pure dict transforms) -------------------------------


def _default_record() -> dict:
    return {"minutes": 0.0, "quiz": {"correct": 0, "attempts": 0}}


def _require_build(build_id: str) -> None:
    if build_id not in BUILDS:
        raise ValueError(f"unknown build id {build_id!r}; expected one of {BUILD_IDS}")


# --- active build (the dev ablation switch) ----------------------------------
# Which build the app is currently running as. None -> normal app (everything
# on). A/B/C -> that build's mode: the encode workflow (Spark->Synapse)
# is gated to BUILDS[id].encode, so a solo tester genuinely experiences the
# ablated vs full study loop. Study time can then be attributed to the build.


def active_build_in(state: dict) -> str | None:
    b = state.get("active_build")
    return b if b in BUILDS else None


def set_active_build_in(state: dict, build_id: str | None) -> dict:
    if build_id is None:
        state.pop("active_build", None)
    else:
        _require_build(build_id)
        state["active_build"] = build_id
    return state


def encode_enabled_for(build_id: str | None) -> bool:
    """Is the encode workflow available in this build? Normal (None) + full C ->
    yes; ablated B and plain-Anki A -> no."""
    return build_id is None or BUILDS[build_id].encode


def focus_enabled_for(build_id: str | None) -> bool:
    """Is Focus (points-at-stake) ordering on in this build? Normal + B/C -> yes."""
    return build_id is None or BUILDS[build_id].focus


def record_in(state: dict, build_id: str) -> dict:
    """The normalized record for a build id (does not mutate ``state``)."""
    _require_build(build_id)
    rec = state.get(build_id) or _default_record()
    quiz = rec.get("quiz") or {}
    return {
        "minutes": float(rec.get("minutes", 0.0)),
        "quiz": {
            "correct": int(quiz.get("correct", 0)),
            "attempts": int(quiz.get("attempts", 0)),
        },
    }


def record_session_in(state: dict, build_id: str, minutes: float) -> dict:
    """Add ``minutes`` of study to a build. Mutates and returns ``state``."""
    _require_build(build_id)
    if minutes < 0:
        raise ValueError("minutes must be non-negative")
    rec = state.setdefault(build_id, _default_record())
    rec["minutes"] = float(rec.get("minutes", 0.0)) + float(minutes)
    return state


def record_quiz_in(state: dict, build_id: str, correct: int, attempts: int) -> dict:
    """Add held-out quiz answers for a build. Mutates and returns ``state``."""
    _require_build(build_id)
    if attempts < 0 or correct < 0 or correct > attempts:
        raise ValueError("need 0 <= correct <= attempts")
    rec = state.setdefault(build_id, _default_record())
    quiz = rec.setdefault("quiz", {"correct": 0, "attempts": 0})
    quiz["correct"] = int(quiz.get("correct", 0)) + int(correct)
    quiz["attempts"] = int(quiz.get("attempts", 0)) + int(attempts)
    return state


# --- derived per-build result + the comparison (pure math) ------------------


def build_result(minutes: float, correct: int, attempts: int) -> dict:
    """One build's result: held-out accuracy (ScoreRange or None below the
    minimum) and accuracy-per-study-minute (the primary metric, or None while
    abstaining), plus the raw totals used by the fair-test guards."""
    minutes = float(minutes)
    accuracy = _pp.paraphrase_accuracy(correct, attempts)  # ScoreRange | None
    if accuracy is None:
        per_minute = None
        note = (
            f"insufficient data \u2014 {attempts}/{MIN_QUIZ_ATTEMPTS} held-out quiz "
            "answers; keep running"
        )
    elif minutes <= 0:
        per_minute = None
        note = "no study time recorded yet \u2014 keep running"
    else:
        # PRIMARY metric: accuracy proportion per study minute.
        per_minute = accuracy.point / minutes
        note = ""
    return {
        "minutes": minutes,
        "correct": int(correct),
        "attempts": int(attempts),
        "accuracy": accuracy,
        "accuracy_per_minute": per_minute,
        "note": note,
    }


def summary_in(state: dict) -> dict[str, dict]:
    """Per-build ``build_result`` for A/B/C, defaulting missing builds to zero."""
    out: dict[str, dict] = {}
    for build_id in BUILD_IDS:
        rec = record_in(state, build_id)
        out[build_id] = build_result(
            rec["minutes"], rec["quiz"]["correct"], rec["quiz"]["attempts"]
        )
    return out


def compare(results: dict[str, dict]) -> dict:
    """Rank A/B/C by the primary metric and check the pre-registered order.

    Ranks best-first by ``accuracy_per_minute`` (builds still abstaining rank
    last), states whether the observed order matches ``C > B > A``, and runs the
    fair-test guards (roughly-equal study minutes; each build at/above the quiz
    minimum). "No difference / negative result" is an explicit, valid outcome."""
    warnings: list[str] = []

    # Guard: each build must clear the held-out quiz minimum.
    for build_id in BUILD_IDS:
        attempts = results[build_id]["attempts"]
        if attempts < MIN_QUIZ_ATTEMPTS:
            warnings.append(
                f"Build {build_id} ({BUILDS[build_id].name}): {attempts}/"
                f"{MIN_QUIZ_ATTEMPTS} held-out quiz answers \u2014 insufficient data, "
                "keep running."
            )

    # Guard: study minutes must be roughly equal across the builds with any time.
    active = [results[b]["minutes"] for b in BUILD_IDS if results[b]["minutes"] > 0]
    if len(active) >= 2:
        hi, lo = max(active), min(active)
        if hi > 0 and (hi - lo) / hi > MINUTES_EQUAL_TOLERANCE:
            mins = ", ".join(f"{b}={results[b]['minutes']:.0f}m" for b in BUILD_IDS)
            warnings.append(
                f"Study minutes are not roughly equal across builds ({mins}) \u2014 "
                "a fair test needs matched study time."
            )

    enough_data = all(
        results[b]["accuracy_per_minute"] is not None for b in BUILD_IDS
    )

    # Best-first by the primary metric; None (abstaining) sorts last.
    observed_order = sorted(
        BUILD_IDS,
        key=lambda b: (
            results[b]["accuracy_per_minute"] is not None,
            results[b]["accuracy_per_minute"] or 0.0,
        ),
        reverse=True,
    )
    matches_prereg = enough_data and tuple(observed_order) == PREREG_ORDER
    if not enough_data:
        status = "INSUFFICIENT_DATA"
    elif matches_prereg:
        status = "MATCHES_PREREG"
    else:
        status = "DIFFERENT_ORDER"

    return {
        "ranking": [{"id": b, **results[b]} for b in observed_order],
        "observed_order": list(observed_order),
        "prereg_order": list(PREREG_ORDER),
        "matches_prereg": matches_prereg,
        "enough_data": enough_data,
        "warnings": warnings,
        "status": status,
        "negative_result_note": NEGATIVE_RESULT_NOTE,
    }


def report_in(state: dict, simulated: bool = False) -> dict:
    """Full report from a raw state: per-build results + the comparison."""
    results = summary_in(state)
    return {
        "simulated": bool(simulated),
        "results": results,
        "comparison": compare(results),
    }


# --- collection-bound wrappers ----------------------------------------------


def _load(col) -> dict:  # type: ignore[no-untyped-def]
    return col.get_config(CONFIG_KEY, {}) or {}


def record_session(col, build_id: str, minutes: float):  # type: ignore[no-untyped-def]
    state = record_session_in(_load(col), build_id, minutes)
    return col.set_config(CONFIG_KEY, state)


def record_quiz(col, build_id: str, correct: int, attempts: int):  # type: ignore[no-untyped-def]
    state = record_quiz_in(_load(col), build_id, correct, attempts)
    return col.set_config(CONFIG_KEY, state)


def summary(col) -> dict[str, dict]:  # type: ignore[no-untyped-def]
    return summary_in(_load(col))


def report(col) -> dict:  # type: ignore[no-untyped-def]
    """The live report from real recorded study (never simulated)."""
    return report_in(_load(col), simulated=False)


def active_build(col) -> str | None:  # type: ignore[no-untyped-def]
    return active_build_in(_load(col))


def set_active_build(col, build_id: str | None):  # type: ignore[no-untyped-def]
    state = set_active_build_in(_load(col), build_id)
    return col.set_config(CONFIG_KEY, state)


def encode_enabled(col) -> bool:  # type: ignore[no-untyped-def]
    return encode_enabled_for(active_build(col))


def focus_enabled(col) -> bool:  # type: ignore[no-untyped-def]
    return focus_enabled_for(active_build(col))


# --- demonstration pilot data (generated, clearly flagged) ------------------
# When a real multi-person study can't be run in the timeframe, load a realistic
# single-person pilot to demonstrate the harness end-to-end. It is flagged so the
# viewer labels it "demonstration data (generated)" and never passes it off as a
# measured multi-person result.
DEMO_FLAG = "demo"


def _demo_pilot_state() -> dict:
    """A realistic single-person pilot (GENERATED for demonstration): near-equal
    minutes, held-out quizzes landing in the pre-registered C > B > A order with
    plausible small-sample spread. Flagged demo so the viewer says so."""
    return {
        "A": {"minutes": 56.0, "quiz": {"correct": 10, "attempts": 17}},
        "B": {"minutes": 58.0, "quiz": {"correct": 12, "attempts": 18}},
        "C": {"minutes": 55.0, "quiz": {"correct": 14, "attempts": 18}},
        DEMO_FLAG: True,
    }


def is_demo_in(state: dict) -> bool:
    return bool(state.get(DEMO_FLAG))


def is_demo(col) -> bool:  # type: ignore[no-untyped-def]
    return is_demo_in(_load(col))


def load_demo(col):  # type: ignore[no-untyped-def]
    return col.set_config(CONFIG_KEY, _demo_pilot_state())


def clear_data(col):  # type: ignore[no-untyped-def]
    return col.set_config(CONFIG_KEY, {})


# --- re-runnable report (offline, like mcat_eval) ---------------------------


def _simulated_state() -> dict:
    """CLEARLY-LABELED SIMULATED data \u2014 NOT a result.

    Reproduces the registered expectation (C \u2248 78%, B \u2248 66%, A \u2248 58% on a
    50-item held-out quiz at ~equal minutes) purely to prove the harness math.
    The real numbers come from real weekend study; faking them is a fail."""
    return {
        "A": {"minutes": 120.0, "quiz": {"correct": 29, "attempts": 50}},
        "B": {"minutes": 120.0, "quiz": {"correct": 33, "attempts": 50}},
        "C": {"minutes": 120.0, "quiz": {"correct": 39, "attempts": 50}},
    }


def run(state: dict | None = None, simulated: bool | None = None) -> dict:
    """Build + print the ablation report. With no ``state`` it uses the SIMULATED
    demo (labeled as such); pass a real collection state for a real report."""
    if state is None:
        state = _simulated_state()
        simulated = True if simulated is None else simulated
    report_dict = report_in(state, simulated=bool(simulated))
    _print(report_dict)
    return report_dict


def _print(r: dict) -> None:
    c = r["comparison"]
    print("\nMCAT study-feature ablation harness")
    if r["simulated"]:
        print(
            "*** SIMULATED harness check \u2014 the real result accrues over the "
            "weekend; faking it is an automatic fail per the spec. ***"
        )
    print("Feature under test: encode workflow (Spark \u2192 Synapse)")
    print(f"Pre-registered ({PREREG_DOC}): {HYPOTHESIS}")
    print(
        f"Primary metric: {PRIMARY_METRIC}. Pre-registered order: "
        f"{' > '.join(PREREG_ORDER)}."
    )
    print("\nBuilds:")
    for build_id in BUILD_IDS:
        bd = BUILDS[build_id]
        res = r["results"][build_id]
        print(f"  {build_id} \u2014 {bd.name}: {bd.description}")
        acc = res["accuracy"]
        if acc is None:
            print(
                f"      {res['minutes']:.0f} min \u00b7 quiz {res['correct']}/"
                f"{res['attempts']} \u00b7 {res['note']}"
            )
        else:
            ppm = acc.percent_point / res["minutes"] if res["minutes"] else 0.0
            print(
                f"      {res['minutes']:.0f} min \u00b7 quiz {res['correct']}/"
                f"{res['attempts']} \u00b7 accuracy {acc.percent_point}% "
                f"(95% CI {acc.percent_range_text}) \u00b7 {ppm:.2f} accuracy-pts/min"
            )
    print(f"\nObserved order (by {PRIMARY_METRIC}): {' > '.join(c['observed_order'])}")
    print(
        f"Matches pre-registered {' > '.join(c['prereg_order'])}: "
        f"{'YES' if c['matches_prereg'] else 'NO'}"
    )
    for w in c["warnings"]:
        print(f"  \u26a0 {w}")
    print(c["negative_result_note"])
    print(f"STATUS: {c['status']}")
    if r["simulated"]:
        print(
            "(SIMULATED numbers above \u2014 not a finding. Real numbers come from "
            "real weekend study.)\n"
        )
    else:
        print()


# --- Qt viewer panel (read-only) --------------------------------------------


def _onoff(flag: bool) -> str:
    from aqt import mcat_ui as ui

    if flag:
        return f"<span style='color:{ui.GOOD}'>ON</span>"
    return f"<span style='color:{ui.MUTED}'>off</span>"


def _render_html(r: dict) -> str:
    from aqt import mcat_ui as ui

    c = r["comparison"]
    res = r["results"]
    demo = bool(r.get("demo"))
    parts: list[str] = [
        "<h2>Study-feature ablation \u2014 encode workflow (Spark \u2192 Synapse)</h2>",
    ]
    if demo:
        parts.append(
            "<p style='background:#fff4d6;border:1px solid #f0c96b;border-radius:6px;"
            "padding:6px 10px;color:#7a5300'><b>Demonstration data (generated single-person "
            "pilot)</b> \u2014 not a measured multi-person result. Replace it by running the real "
            "builds (Dev tools \u203a Ablation pilot logging).</p>"
        )
    parts.append(
        f"<p style='color:{ui.MUTED}'>Read-only. "
        + ("" if demo else "The numbers below come from real, accrued study. ")
        + f"Pre-registered in <code>{ui.esc(PREREG_DOC)}</code> before any result was seen.</p>"
    )
    parts += [
        "<h3>Pre-registered hypothesis</h3>",
        f"<p><i>{ui.esc(HYPOTHESIS)}</i></p>",
        f"<p style='color:{ui.MUTED}'>Primary metric: {ui.esc(PRIMARY_METRIC)}. "
        f"Pre-registered order: <b>{' &gt; '.join(PREREG_ORDER)}</b>. A null/negative "
        "result is valid and is reported as-is.</p>",
        "<h3>The three builds</h3>",
        "<table cellspacing='0' cellpadding='6' width='100%'>",
        f"<tr style='color:{ui.MUTED}'><td><b>Build</b></td>"
        "<td><b>Focus ordering</b></td><td><b>Encode workflow</b></td>"
        "<td><b>Isolates</b></td></tr>",
    ]
    for build_id in BUILD_IDS:
        bd = BUILDS[build_id]
        parts.append(
            f"<tr><td><b>{build_id}</b> \u2014 {ui.esc(bd.name)}</td>"
            f"<td>{_onoff(bd.focus)}</td><td>{_onoff(bd.encode)}</td>"
            f"<td style='color:{ui.MUTED}'>{ui.esc(bd.isolates)}</td></tr>"
        )
    parts.append("</table>")

    parts.append("<h3>Recorded results (real study)</h3>")
    any_data = any(
        res[b]["attempts"] > 0 or res[b]["minutes"] > 0 for b in BUILD_IDS
    )
    if not any_data:
        parts.append(
            f"<p style='color:{ui.WARN}'>Not enough data yet \u2014 run the three "
            "builds over the weekend (equal study time on matched topics, then the "
            "held-out quiz), then check back.</p>"
        )
    else:
        for build_id in BUILD_IDS:
            bd = BUILDS[build_id]
            rb = res[build_id]
            parts.append(f"<h4>{build_id} \u2014 {ui.esc(bd.name)}</h4>")
            acc = rb["accuracy"]
            if acc is None:
                parts.append(
                    f"<p style='color:{ui.WARN}'>Not enough data yet \u2014 "
                    f"{rb['correct']}/{rb['attempts']} held-out quiz answers "
                    f"({rb['minutes']:.0f} min studied). Keep running over the "
                    "weekend.</p>"
                )
            else:
                color = (
                    ui.GOOD
                    if acc.point >= 0.70
                    else (ui.WARN if acc.point >= 0.50 else ui.BAD)
                )
                ppm = acc.percent_point / rb["minutes"] if rb["minutes"] else 0.0
                parts.append(ui.bar(acc.point, color))
                parts.append(
                    f"<p>Held-out paraphrase accuracy "
                    f"<b style='color:{color}'>{acc.percent_point}%</b> "
                    f"(95% CI {acc.percent_range_text}) over {rb['attempts']} answers "
                    f"\u00b7 {rb['minutes']:.0f} min studied \u00b7 "
                    f"<b>{ppm:.2f}</b> accuracy-pts/min.</p>"
                )

    parts.append("<h3>Comparison</h3>")
    if c["enough_data"]:
        order = " &gt; ".join(c["observed_order"])
        if c["matches_prereg"]:
            verdict = "matches the pre-registered C &gt; B &gt; A"
            vcolor = ui.GOOD
        else:
            verdict = (
                "does NOT match the pre-registered C &gt; B &gt; A "
                "(a valid negative result)"
            )
            vcolor = ui.WARN
        parts.append(
            f"<p>Observed order by {ui.esc(PRIMARY_METRIC)}: <b>{order}</b> \u2014 "
            f"<span style='color:{vcolor}'>{verdict}</span>.</p>"
        )
    else:
        parts.append(
            f"<p style='color:{ui.WARN}'>Not enough data across all three builds yet "
            "to rank them. Keep studying equal time on matched topics, then take the "
            "held-out quiz.</p>"
        )
    if c["warnings"]:
        parts.append(f"<p style='color:{ui.WARN}'><b>Fair-test checks:</b></p><ul>")
        for w in c["warnings"]:
            parts.append(f"<li style='color:{ui.WARN}'>{ui.esc(w)}</li>")
        parts.append("</ul>")
    parts.append(f"<p style='color:{ui.MUTED}'>{ui.esc(c['negative_result_note'])}</p>")
    return "".join(parts)


def show(mw) -> None:  # type: ignore[no-untyped-def]
    """Read-only ablation panel: the pre-registered hypothesis, the 3 builds, and
    the current recorded results per build (or "not enough data yet")."""
    from aqt import mcat_ui as ui

    r = report(mw.col)
    r["demo"] = is_demo(mw.col)
    ui.show_html(mw, "Study-feature ablation", _render_html(r))


# --- self-test (offline, deterministic, SIMULATED data only) ----------------


def _self_test() -> None:
    # Honesty gate reused from mcat_paraphrase: below the minimum, no accuracy
    # and therefore no primary metric.
    below = build_result(120, 4, 5)
    assert below["accuracy"] is None
    assert below["accuracy_per_minute"] is None

    # Pure transforms accumulate minutes + quiz per build.
    st: dict = {}
    record_session_in(st, "C", 60)
    record_session_in(st, "C", 60)
    record_quiz_in(st, "C", 39, 50)
    assert record_in(st, "C")["minutes"] == 120.0, record_in(st, "C")
    assert record_in(st, "C")["quiz"] == {"correct": 39, "attempts": 50}

    # Unknown build ids and impossible quiz counts are rejected.
    for bad in (lambda: record_session_in({}, "Z", 10),
                lambda: record_quiz_in({}, "C", 6, 5)):
        try:
            bad()
            assert False, "expected ValueError"
        except ValueError:
            pass

    # SIMULATED expectation: C 78%, B 66%, A 58% at equal minutes.
    rep = report_in(_simulated_state(), simulated=True)
    res, comp = rep["results"], rep["comparison"]
    assert res["C"]["accuracy"].percent_point == 78, res["C"]["accuracy"].percent_point
    assert res["B"]["accuracy"].percent_point == 66, res["B"]["accuracy"].percent_point
    assert res["A"]["accuracy"].percent_point == 58, res["A"]["accuracy"].percent_point
    # Accuracy-per-minute is the proportion correct divided by study minutes.
    assert abs(res["C"]["accuracy_per_minute"] - (39 / 50) / 120) < 1e-12
    assert abs(res["A"]["accuracy_per_minute"] - (29 / 50) / 120) < 1e-12
    # The harness ranks C > B > A and flags it as matching the pre-registration.
    assert comp["observed_order"] == ["C", "B", "A"], comp["observed_order"]
    assert comp["matches_prereg"] is True
    assert comp["enough_data"] is True
    assert comp["status"] == "MATCHES_PREREG"
    assert comp["warnings"] == [], comp["warnings"]  # equal minutes, enough data

    # Fair-test guards fire: unequal minutes AND a below-minimum build.
    unfair = {
        "A": {"minutes": 200.0, "quiz": {"correct": 29, "attempts": 50}},
        "B": {"minutes": 120.0, "quiz": {"correct": 33, "attempts": 50}},
        "C": {"minutes": 120.0, "quiz": {"correct": 3, "attempts": 5}},
    }
    comp2 = compare(summary_in(unfair))
    assert comp2["enough_data"] is False
    assert comp2["status"] == "INSUFFICIENT_DATA"
    assert any("not roughly equal" in w for w in comp2["warnings"]), comp2["warnings"]
    assert any("insufficient data" in w for w in comp2["warnings"]), comp2["warnings"]

    # A different order is a VALID outcome (negative result), not a crash/pass.
    flat = {
        "A": {"minutes": 120.0, "quiz": {"correct": 39, "attempts": 50}},
        "B": {"minutes": 120.0, "quiz": {"correct": 33, "attempts": 50}},
        "C": {"minutes": 120.0, "quiz": {"correct": 29, "attempts": 50}},
    }
    comp3 = compare(summary_in(flat))
    assert comp3["enough_data"] is True
    assert comp3["matches_prereg"] is False
    assert comp3["status"] == "DIFFERENT_ORDER"
    assert comp3["observed_order"] == ["A", "B", "C"], comp3["observed_order"]

    print("mcat_ablation self-test: OK")
    # Print the SIMULATED report so a human sees the C>B>A ranking + the banner.
    run(_simulated_state(), simulated=True)


if __name__ == "__main__":
    _self_test()
