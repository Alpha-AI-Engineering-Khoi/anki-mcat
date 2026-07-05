# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Day-1 onboarding: a ~5-minute "sample lesson" that proves higher-order
encoding *on the learner*, then backs it with cited evidence.

Honesty (see ``brainlifts/anki-for-mcat/brainlift.md``, SPOV 2): the claim is
**building the connections yourself beats passively reading/memorizing**, NOT
"maps beat flashcards." Retrieval + feedback is the hinge (Karpicke & Blunt,
2011), which is exactly why Recall follows Mindmap in the program. So the demo
does not stage a rigged score; it lets the learner *experience* a reasoning
question becoming answerable after they build the map, then shows real numbers.

Arc (a 4-page wizard):
  1. Cold open: skim the topic, try a reasoning question with no map (the
     honest "before").
  2. Build: the REAL Mindmap canvas, concepts pre-seeded (Day-1 beginner ->
     seed the scaffold, per the expertise-reversal SPOV); the learner draws the
     labeled arrows (the generative act).
  3. Retry: the same question, now traceable through their arrows + quick
     recall checks.
  4. Evidence: cited effect sizes + handoff into the Day-1 board.

The demo uses a fixed, isolated topic slug (``onboarding.enzymes``) so it never
touches the 50 real program topics.
"""

from __future__ import annotations

DONE_KEY = "mcat_onboarding_done"

# --- fixed sample content (enzyme inhibition: the canonical "you must reason
# from the relationships, you can't just memorize it" MCAT topic) --------------

_TOPIC_SLUG = "onboarding.enzymes"
_TOPIC_NAME = "Enzyme kinetics & inhibition"

# Concepts are SEEDED (beginner scaffold); the learner draws the arrows.
_CONCEPTS = [
    {"id": 1, "parent": None, "label": "Enzyme"},
    {"id": 2, "parent": None, "label": "Active site"},
    {"id": 3, "parent": None, "label": "Substrate"},
    {"id": 4, "parent": None, "label": "Competitive inhibitor"},
    {"id": 5, "parent": None, "label": "Vmax (max rate)"},
    {"id": 6, "parent": None, "label": "Km (substrate for \u00bd-max)"},
]

_SKIM = [
    ("Enzyme", "a protein catalyst; speeds a reaction by lowering activation energy."),
    ("Active site", "the pocket where the substrate binds."),
    ("Substrate", "the molecule the enzyme acts on."),
    ("Competitive inhibitor", "a molecule that resembles the substrate."),
    ("Vmax", "the maximum rate, reached at saturating substrate."),
    ("Km", "the substrate concentration that gives half of Vmax (apparent affinity)."),
]

_QUESTION = (
    "A competitive inhibitor is added to an enzyme-catalyzed reaction. "
    "What happens to <b>Vmax</b> and <b>Km</b>, and <i>why</i>?"
)

_PROMPTS = [
    "Where does the competitive inhibitor bind, and what does it compete with?",
    "What happens if you flood the system with extra substrate?",
    "Which number moves: the ceiling (Vmax), or the substrate needed for half-max (Km)?",
]

# Kept to the four the reasoning question actually needs (avoids "spiderwebbing"
# and protects the ~5-minute budget). "surmountable" carries the why-Vmax-is-unchanged
# idea without a separate arrow.
_SUGGESTED_ARROWS = [
    ("Substrate", "Active site", "binds"),
    ("Competitive inhibitor", "Active site", "competes for"),
    ("Competitive inhibitor", "Km", "raises"),
    ("Competitive inhibitor", "Vmax", "no change (surmountable)"),
]

_MODEL_ANSWER = (
    "Trace your arrows: the competitive inhibitor competes with substrate for the "
    "<b>same active site</b>. Because it only <i>competes</i>, flooding the system "
    "with extra substrate outcompetes it, so the reaction still reaches its "
    "full ceiling. <b>Vmax is unchanged.</b> But you now need more substrate to get "
    "to half-max, so <b>Km increases</b> (apparent affinity drops).<br><br>"
    "You didn't recall that. You <i>reasoned</i> it from the structure you "
    "built. That's the ~65% of the MCAT that is reasoning, not recall."
)

_RECALL = [
    ("Where does a competitive inhibitor bind?",
     "The active site: it mimics the substrate and competes for the same pocket."),
    ("Does a competitive inhibitor lower Vmax?",
     "No. It's surmountable: enough substrate restores full Vmax. It raises Km."),
]


def _demo_topic():  # type: ignore[no-untyped-def]
    from aqt import mcat_program as prog  # noqa: PLC0415

    return prog.Topic(
        section_token="BioBiochem",
        section="Bio/Biochem",
        token="OnbEnzymes",
        name=_TOPIC_NAME,
        tag="MCAT::BioBiochem::OnbEnzymes",
        slug=_TOPIC_SLUG,
    )


def is_done(col) -> bool:  # type: ignore[no-untyped-def]
    return bool(col.get_config(DONE_KEY, False))


# --- page builders (kept thin; return a QWidget) ----------------------------


def _prose(text: str):  # type: ignore[no-untyped-def]
    from aqt.qt import QLabel, Qt  # noqa: PLC0415

    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    return lbl


def _night() -> bool:
    try:
        from aqt import theme  # noqa: PLC0415

        return bool(theme.theme_manager.night_mode)
    except Exception:
        return False


def _muted() -> str:
    """Dim-but-legible secondary text on whichever Qt theme is active."""
    return "#a2a6b3" if _night() else "#5d636e"


def _card(html: str) -> str:
    # No box: plain text with light spacing (the learner asked for normal text,
    # not cards). Text uses the native palette; secondary notes use _muted().
    return f"<div style='margin:8px 0'>{html}</div>"


def show(mw) -> None:  # type: ignore[no-untyped-def]
    """Open the Day-1 sample-lesson wizard."""
    import html as _html  # noqa: PLC0415

    from aqt import mcat_program as prog  # noqa: PLC0415
    from aqt.qt import (  # noqa: PLC0415
        QDialog,
        QHBoxLayout,
        QLabel,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QStackedWidget,
        Qt,
        QTimer,
        QVBoxLayout,
        QWidget,
        qconnect,
    )
    from aqt.utils import disable_help_button  # noqa: PLC0415

    col = mw.col
    topic = _demo_topic()
    # Fresh start every run: seed the concepts, clear any arrows the learner drew
    # last time. Isolated slug -> never touches the real 50 topics.
    prog.save_build(col, topic, [dict(c) for c in _CONCEPTS], [])

    dialog = QDialog(mw)
    dialog.setWindowTitle("MCAT \u00b7 Sample lesson")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)
    dialog.resize(780, 660)

    root = QVBoxLayout(dialog)
    stack = QStackedWidget()
    root.addWidget(stack, 1)

    canvas = {"view": None, "cleanup": None}
    refs: dict = {}  # widgets shared across pages (the cold answer -> the retry page)

    # ---- page 1: cold open --------------------------------------------------
    def page_cold() -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        skim = "".join(
            f"<li><b>{k}</b>: {v}</li>" for k, v in _SKIM
        )
        intro = _prose(
            "<h2 style='margin:0 0 2px'>See it for yourself \u00b7 5 minutes</h2>"
            "<p style='margin:0 0 8px'>Most of the MCAT rewards reasoning, not "
            "memory. Reasoning is something you build, not something you're "
            "born with. The next five minutes won't ask you to believe that. They'll "
            "show you: answer one question cold, build the idea in your own words, and "
            "watch the same question become answerable.</p>"
            + _card(
                "<b>First, skim for the big picture (don't memorize):</b>"
                f"<ul style='margin:6px 0 0 -8px'>{skim}</ul>"
            )
            + _card(
                "<b>Now try this cold, before you've built anything:</b><br>"
                + _QUESTION
            )
        )
        lay.addWidget(intro)
        lay.addWidget(_prose("<b>Your best shot</b> (\u201cnot sure\u201d is a fine answer):"))
        ans = QPlainTextEdit()
        ans.setPlaceholderText("Twenty seconds: what happens to Vmax and Km, and why?")
        ans.setFixedHeight(84)
        refs["cold"] = ans  # echoed back on the retry page for a personal before/after
        lay.addWidget(ans)
        lay.addWidget(
            _prose(
                f"<span style='color:{_muted()}'>Stuck is okay. It's the honest "
                "starting line. A skim hands you facts; it doesn't hand you reasoning. "
                "That's the part you're about to build.</span>"
            )
        )
        lay.addStretch(1)
        return w

    # ---- page 2: guided build (real Mindmap canvas) -------------------------
    def page_build() -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        prompts = "".join(f"<li>{p}</li>" for p in _PROMPTS)
        arrows = "".join(
            f"<li><code>{a}</code> \u2192 <code>{b}</code> &nbsp;\u00b7&nbsp; \u201c{lab}\u201d</li>"
            for a, b, lab in _SUGGESTED_ARROWS
        )
        lay.addWidget(
            _prose(
                "<h3 style='margin:0 0 2px'>Now build the relationships yourself</h3>"
                "<p style='margin:0 0 6px'>The concepts are placed for you "
                "(you're on Day 1). Your job is the part that actually teaches: draw "
                "<b>labeled arrows</b>. Click <b>Draw arrow</b>, drag between two "
                "concepts, then name the link.</p>"
                f"<p style='margin:0 0 6px;color:{_muted()}'>A plain line just says "
                "\u201crelated.\u201d An <b>arrow</b> says <i>how</i> and <i>which "
                "way</i>. Committing to that is the reasoning the MCAT tests.</p>"
                + _card(
                    f"<b>Ask yourself:</b>"
                    f"<ul style='margin:6px 0 8px -8px'>{prompts}</ul>"
                    f"<b>Arrows worth drawing:</b>"
                    f"<ul style='margin:6px 0 0 -8px'>{arrows}</ul>"
                )
            )
        )
        # canvas is created lazily (below) so it initializes while visible.
        holder = QWidget()
        holder.setMinimumHeight(360)
        QVBoxLayout(holder).setContentsMargins(0, 0, 0, 0)
        w._canvas_holder = holder  # type: ignore[attr-defined]
        lay.addWidget(holder, 1)
        return w

    def ensure_canvas(holder: QWidget) -> None:
        if canvas["view"] is not None:
            return
        from aqt import mcat_synapse  # noqa: PLC0415

        view, cleanup = mcat_synapse.build_view(mw, topic, [], parent=holder)
        view.setMinimumHeight(340)
        holder.layout().addWidget(view)
        canvas["view"] = view
        canvas["cleanup"] = cleanup
        # This is an onboarding: keep the generative act with the learner. Hide the
        # "AI does it for you" buttons (auto-build replaces the whole map; seed is
        # moot since concepts are pre-placed). Hint-style "propose arrows" + chat stay.
        QTimer.singleShot(
            500,
            lambda: view.eval(
                "['bAuto','bSeed'].forEach(function(i){var e=document.getElementById(i);"
                "if(e)e.style.display='none';});"
            ),
        )

    # ---- page 3: retry ------------------------------------------------------
    def page_retry() -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.addWidget(
            _prose(
                "<h3 style='margin:0 0 2px'>Same question, now it's yours to reason through</h3>"
                + _card("<b>The question:</b><br>" + _QUESTION)
                + "<p>Follow the arrows you drew. Answer in your head first, "
                "then reveal how the map gets there.</p>"
            )
        )
        # Personal before/after: echo back what the learner wrote cold (filled in on
        # navigation, in go()). Their own words make the payoff concrete and honest.
        cold_lbl = _prose("")
        cold_lbl.setVisible(False)
        refs["cold_lbl"] = cold_lbl
        lay.addWidget(cold_lbl)

        model = _prose(_card(_MODEL_ANSWER))
        model.setVisible(False)
        reveal = QPushButton("Reveal how the map answers it")
        qconnect(reveal.clicked, lambda: (model.setVisible(True), reveal.setVisible(False)))
        lay.addWidget(reveal)
        lay.addWidget(model)

        lay.addWidget(
            _prose(
                "<h3 style='margin:12px 0 2px'>Quick recall check</h3>"
                f"<p style='margin:0 0 4px;color:{_muted()}'>Answer each out loud first, "
                "<i>then</i> check. The attempt is what makes it stick.</p>"
            )
        )
        for q, a in _RECALL:
            lbl_a = _prose(_card("<b>Answer:</b> " + a))
            lbl_a.setVisible(False)
            btn = QPushButton("Check my answer")
            # bind current a via default args
            qconnect(
                btn.clicked,
                lambda _=False, la=lbl_a, b=btn: (la.setVisible(True), b.setVisible(False)),
            )
            lay.addWidget(_prose("<b>Q:</b> " + q))
            lay.addWidget(btn)
            lay.addWidget(lbl_a)
        lay.addStretch(1)
        area.setWidget(inner)
        outer.addWidget(area, 1)
        return w

    # ---- page 4: evidence + handoff ----------------------------------------
    def page_evidence() -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(
            _prose(
                "<h3 style='margin:0 0 2px'>That wasn't a trick. It's how understanding works</h3>"
                + _card(
                    "<ul style='margin:2px 0 0 -8px'>"
                    "<li><b>Building your own map beats studying a ready-made one:</b> "
                    "g = 0.72 vs 0.43 (Schroeder et al., 2018).</li>"
                    "<li><b>Explaining <i>why</i> a link exists is a strong, low-cost "
                    "gain:</b> g = 0.55 (Bisra et al., 2018), which is exactly what "
                    "labeling an arrow forces you to do.</li>"
                    "<li><b>The generation effect:</b> you remember what you produce, "
                    "not what you read (Slamecka & Graf, 1978).</li>"
                    "<li><b>The honest catch:</b> building is step one. You lock it in "
                    "with retrieval + feedback. That's your <b>Recall</b> stage. "
                    "(Retrieval can even beat mapping when it corrects your errors, "
                    "per Karpicke & Blunt, 2011. Feedback is the hinge.)</li>"
                    "</ul>"
                )
                + _card(
                    "<b>Your daily method:</b> "
                    "Scaffold \u2192 <b>Mindmap</b> \u2192 Recall \u2192 Ready.<br>"
                    f"<span style='color:{_muted()}'>Build the ideas and the reasoning "
                    "follows; retrieve them and it lasts. That's the whole method. "
                    "Let's start Day 1.</span>"
                )
            )
        )
        lay.addStretch(1)
        return w

    pages = [page_cold(), page_build(), page_retry(), page_evidence()]
    for p in pages:
        stack.addWidget(p)

    # ---- footer nav ---------------------------------------------------------
    idx = {"i": 0}
    nav = QHBoxLayout()
    back_btn = QPushButton("Back")
    skip_btn = QPushButton("Skip")
    next_btn = QPushButton("")
    next_btn.setDefault(True)
    nav.addWidget(back_btn)
    nav.addStretch(1)
    nav.addWidget(skip_btn)
    nav.addWidget(next_btn)
    root.addLayout(nav)

    _NEXT_LABELS = [
        "Build the map \u2192",
        "See the question again \u2192",
        "Show me the evidence \u2192",
        "Start Day 1 \u2192",
    ]

    def render_nav() -> None:
        i = idx["i"]
        back_btn.setVisible(i > 0)
        skip_btn.setVisible(i < len(pages) - 1)
        next_btn.setText(_NEXT_LABELS[i])

    def go(i: int) -> None:
        i = max(0, min(i, len(pages) - 1))
        idx["i"] = i
        stack.setCurrentIndex(i)
        if i == 1:
            holder = pages[1]._canvas_holder  # type: ignore[attr-defined]
            ensure_canvas(holder)
            QTimer.singleShot(
                300,
                lambda: canvas["view"] and canvas["view"].eval(
                    "window.__refit&&window.__refit()"
                ),
            )
        if i == 2:
            cold = refs.get("cold")
            lbl = refs.get("cold_lbl")
            if cold is not None and lbl is not None:
                txt = cold.toPlainText().strip()
                if txt:
                    lbl.setText(
                        _card(
                            "<b>What you wrote cold:</b> <i>\u201c"
                            + _html.escape(txt)
                            + "\u201d</i>"
                        )
                    )
                    lbl.setVisible(True)
                else:
                    lbl.setVisible(False)
        render_nav()

    def finish() -> None:
        try:
            col.set_config(DONE_KEY, True)
        except Exception:
            pass
        dialog.accept()

        def _open() -> None:
            try:
                import aqt.mcat_today  # noqa: PLC0415

                aqt.mcat_today.show(mw, day=0)
            except Exception:
                pass

        QTimer.singleShot(0, _open)

    def on_next() -> None:
        if idx["i"] >= len(pages) - 1:
            finish()
        else:
            go(idx["i"] + 1)

    qconnect(next_btn.clicked, on_next)
    qconnect(back_btn.clicked, lambda: go(idx["i"] - 1))
    qconnect(skip_btn.clicked, dialog.reject)

    def on_finished(_code: int) -> None:
        if canvas["cleanup"]:
            canvas["cleanup"]()

    qconnect(dialog.finished, on_finished)

    render_nav()
    dialog.show()
