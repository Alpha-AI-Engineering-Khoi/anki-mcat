# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Desktop MCAT "encode front-half": Prime -> Connect -> Build.

Three interactive panels that teach encoding *before* drilling, plus an
overflow -> cards bridge into Anki's normal add-note path:

- Prime: skim the whole topic for the big picture, commit hypotheses, mark the
  topic primed (a synced per-topic flag).
- Connect: make the topic personal via four editable inquiry prompts.
- Build: lay out concepts as an indented outline and add labeled links, with a
  live, non-blocking 2-4 linter; overflow details you couldn't relate become
  flashcards.

All pure logic (topic mapping, state, the linter) lives in the shared, tested
``mcat_program``; the lower-order AI (scope / keywords / concepts / overflow
draft) lives in ``mcat_ai`` and works with AI OFF. This file is just the Qt.
"""

from __future__ import annotations

from aqt import mcat_ai as ai
from aqt import mcat_program as prog

# The four seeded inquiry prompts (Connect). Seeded per keyword; the learner
# edits or rewrites them. AI never answers them.
_CONNECT_TEMPLATES = [
    "What's most relevant to me about {kw}?",
    "What am I curious about with {kw}?",
    "Why do I need to know {kw}?",
    "Where would I apply {kw}?",
]


def _spans_for(topic: "prog.Topic") -> list[dict]:
    """Source spans for this topic, or [] when the bundled source is a different
    topic (only Enzymes ships a source today)."""
    try:
        src_topic, spans = ai.load_source(topic_tag=topic.tag)
    except Exception:
        return []
    return spans if src_topic == topic.tag else []


def _status_text(rec: dict) -> str:
    def mark(flag: bool) -> str:
        return "\u2713" if flag else "\u2014"

    primed = bool(rec.get("primed"))
    connected = any((q or "").strip() for q in rec.get("connect", []))
    built = len(rec.get("concepts", [])) > 0
    return (
        f"Primed {mark(primed)}     \u00b7     "
        f"Connected {mark(connected)}     \u00b7     "
        f"Built {mark(built)}"
    )


def _encode_gated(mw) -> bool:  # type: ignore[no-untyped-def]
    """True (and warns) when the active ablation build has the encode workflow
    OFF (builds A/B). Keeps the ablation honest: you can't encode in a build
    whose whole point is that encoding is disabled."""
    from aqt import mcat_ablation as ab
    from aqt.utils import showInfo

    if ab.encode_enabled(mw.col):
        return False
    showInfo(
        "The encode workflow (Spark \u2192 Synapse) is OFF in this ablation build. "
        "Switch to Normal or build C in Tools \u2192 MCAT \u2192 Dev tools to use it.",
        parent=mw,
    )
    return True


def show(mw) -> None:  # type: ignore[no-untyped-def]
    """The launcher: pick a topic, then open Prime / Connect / Build."""
    if _encode_gated(mw):
        return
    from aqt.qt import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button

    topics = prog.all_topics()

    dialog = QDialog(mw)
    dialog.setWindowTitle("Encode: Prime \u2192 Build")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            "Encode before you drill: prime the topic for the big picture, "
            "then build the map."
        )
    )

    combo = QComboBox()
    # macOS shows a non-scrolling native popup for long lists; force a normal
    # scrollable list view (with a scrollbar) so all 50 topics are reachable.
    combo.setMaxVisibleItems(20)
    combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
    for t in topics:
        combo.addItem(f"{t.section} \u00b7 {t.name}", t.slug)
    layout.addWidget(combo)

    prime_btn = QPushButton("\u2460 Prime\u2026")
    build_btn = QPushButton("\u2461 Build\u2026")
    row = QHBoxLayout()
    for b in (prime_btn, build_btn):
        # keep both neutral/gray — don't let Prime become the blue default button
        b.setAutoDefault(False)
        b.setDefault(False)
        row.addWidget(b)
    layout.addLayout(row)

    def current_topic() -> "prog.Topic":
        return topics[max(0, combo.currentIndex())]

    qconnect(prime_btn.clicked, lambda: _prime_dialog(mw, current_topic()))
    qconnect(build_btn.clicked, lambda: _build_dialog(mw, current_topic()))

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(buttons)

    dialog.resize(540, 240)
    dialog.exec()


def open_for(mw, topic: "prog.Topic", stage: str | None = None) -> None:  # type: ignore[no-untyped-def]
    """Open one encode stage for a preselected topic (entry point for the Today
    panel). ``stage`` is "prime" / "connect" / "build"; anything else falls back
    to the topic-picker launcher. Keeps ``show(mw)`` as the standalone flow."""
    if _encode_gated(mw):
        return
    if stage == "prime":
        _prime_dialog(mw, topic)
    elif stage == "connect":
        _connect_dialog(mw, topic)
    elif stage == "build":
        _build_dialog(mw, topic)
    else:
        show(mw)


def _prime_dialog(mw, topic: "prog.Topic") -> None:  # type: ignore[no-untyped-def]
    import html as _html

    from aqt.operations import QueryOp
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QLabel,
        QListWidget,
        QPlainTextEdit,
        QTextBrowser,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button, tooltip

    spans = _spans_for(topic)
    rec = prog.get_record(mw.col, topic)
    holder: dict = {"items": []}

    dialog = QDialog(mw)
    dialog.setWindowTitle(f"Prime: {topic.name}")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel("Skim the whole topic for the big picture. Do NOT memorize details yet.")
    )
    layout.addWidget(QLabel("Scope / skim \u2014 the big ideas (click one):"))
    scope_list = QListWidget()
    scope_list.addItem("Generating scope + explanations\u2026")
    layout.addWidget(scope_list)

    explain_box = QTextBrowser()
    explain_box.setOpenExternalLinks(True)
    explain_box.setMinimumHeight(140)
    explain_box.setHtml(
        "<i>Click an idea above to read a short, sourced explanation.</i>")
    layout.addWidget(explain_box)

    layout.addWidget(QLabel("Your 1\u20132 hypotheses:"))
    hypotheses = QPlainTextEdit(rec.get("hypotheses", ""))
    hypotheses.setPlaceholderText(
        "e.g. Enzymes lower activation energy without shifting equilibrium\u2026")
    layout.addWidget(hypotheses)

    buttons = QDialogButtonBox()
    mark_btn = buttons.addButton("Mark primed", QDialogButtonBox.ButtonRole.ActionRole)
    buttons.addButton(QDialogButtonBox.StandardButton.Close)
    layout.addWidget(buttons)

    def revalidate() -> None:
        mark_btn.setEnabled(bool(hypotheses.toPlainText().strip()))

    def do_mark() -> None:
        prog.mark_primed(mw.col, topic, hypotheses.toPlainText().strip())
        tooltip(f"Primed \u201c{topic.name}\u201d.", parent=mw)
        dialog.accept()

    qconnect(hypotheses.textChanged, revalidate)
    qconnect(mark_btn.clicked, do_mark)
    qconnect(buttons.rejected, dialog.reject)

    def _fill(items: list) -> None:
        holder["items"] = items or []
        scope_list.clear()
        if not holder["items"]:
            scope_list.addItem("(no scope returned \u2014 reopen to retry)")
            return
        for it in holder["items"]:
            scope_list.addItem("\u2022 " + it.get("term", ""))

    # ONE background run generates every idea + its explanation + source.
    QueryOp(parent=mw, op=lambda _col: ai.scope_explained(spans, topic.name),
            success=_fill).run_in_background()

    def _on_select(row: int) -> None:
        items = holder["items"]
        if row < 0 or row >= len(items):
            return
        it = items[row]
        html = (f"<b>{_html.escape(it.get('term', ''))}</b><br>"
                f"{_html.escape(it.get('explanation') or '(no explanation available)')}")
        srcs = [s for s in (it.get("sources") or []) if s.get("url")]
        if srcs:
            rows = []
            for i, s in enumerate(srcs, 1):
                title = s.get("title") or s["url"]
                rows.append(f"<span style='color:#888'>Source {i}: "
                            f"<a href='{_html.escape(s['url'])}'>"
                            f"{_html.escape(title)}</a></span>")
            html += "<br><br>" + "<br>".join(rows)
        explain_box.setHtml(html)

    qconnect(scope_list.currentRowChanged, _on_select)

    revalidate()
    dialog.resize(560, 640)
    dialog.exec()


def _connect_dialog(mw, topic: "prog.Topic") -> None:  # type: ignore[no-untyped-def]
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QLabel,
        QLineEdit,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button, tooltip

    spans = _spans_for(topic)
    keywords = ai.keyword_candidates(spans, topic.name) or [topic.name]
    rec = prog.get_record(mw.col, topic)
    saved = rec.get("connect") or []

    dialog = QDialog(mw)
    dialog.setWindowTitle(f"Connect: {topic.name}")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            "Make it personal. Edit these into your own questions \u2014 "
            "you answer them, not the AI."
        )
    )

    edits: list = []
    for i, template in enumerate(_CONNECT_TEMPLATES):
        # Strip trailing punctuation so a keyword can't produce "…cofactors.?"
        # when slotted into a question template.
        keyword = keywords[i % len(keywords)].rstrip(" .;:,?!")
        if i < len(saved) and (saved[i] or "").strip():
            seed = saved[i]
        else:
            seed = template.format(kw=keyword)
        edit = QLineEdit(seed)
        layout.addWidget(edit)
        edits.append(edit)

    buttons = QDialogButtonBox()
    save_btn = buttons.addButton("Save questions", QDialogButtonBox.ButtonRole.ActionRole)
    buttons.addButton(QDialogButtonBox.StandardButton.Close)
    layout.addWidget(buttons)

    def do_save() -> None:
        prog.save_connect(mw.col, topic, [e.text() for e in edits])
        tooltip(f"Saved your questions for \u201c{topic.name}\u201d.", parent=mw)
        dialog.accept()

    qconnect(save_btn.clicked, do_save)
    qconnect(buttons.rejected, dialog.reject)

    dialog.resize(560, 260)
    dialog.exec()


def _build_dialog(mw, topic: "prog.Topic") -> None:  # type: ignore[no-untyped-def]
    """Synapse: the higher-order encoding map.

    An interactive node-graph canvas (vis-network in an AnkiWebView) where the
    learner lays out concepts and draws *named* relationships between them; AI
    only proposes (seed / propose arrows / auto-build a whole map to react to)
    and coaches via chat. Replaces the old outline+links tree editor. All the
    canvas wiring lives in ``mcat_synapse``; this is just the host dialog."""
    from aqt.qt import QDialog, QDialogButtonBox, QVBoxLayout, qconnect
    from aqt.utils import disable_help_button

    from aqt import mcat_synapse as syn

    spans = _spans_for(topic)

    dialog = QDialog(mw)
    dialog.setWindowTitle(f"Synapse: {topic.name}")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    view, cleanup = syn.build_view(mw, topic, spans, parent=dialog)
    outer.addWidget(view, 1)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.setContentsMargins(8, 4, 8, 8)
    qconnect(buttons.rejected, dialog.reject)
    outer.addWidget(buttons)

    # Tear down the webview on close so a late AI callback can't touch a
    # torn-down page. (Save is explicit, via the in-canvas "Save map" button.)
    qconnect(dialog.finished, lambda _code: cleanup())

    dialog.resize(1040, 700)
    dialog.exec()


def _confirm_overflow_card(mw, topic: "prog.Topic", spans: list[dict], detail: str) -> None:  # type: ignore[no-untyped-def]
    """Draft an overflow detail into a flashcard and add it via Anki's normal
    add-note operation, tagged to the topic and linked to its source span."""
    from aqt.operations.note import add_note
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import askUser, disable_help_button, showWarning, tooltip

    card = ai.draft_overflow_card(detail, spans, topic.tag)

    dialog = QDialog(mw)
    dialog.setWindowTitle("Send to cards")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            "A detail you couldn't relate becomes a flashcard \u2014 review it "
            "later instead of memorizing now."
        )
    )
    layout.addWidget(QLabel("Front:"))
    front = QLineEdit(card["front"])
    layout.addWidget(front)
    layout.addWidget(QLabel("Back:"))
    back = QPlainTextEdit(card["back"])
    layout.addWidget(back)
    meta = QLabel(
        f"Tagged {topic.tag} \u00b7 source span {card['source_span'] or '\u2014'}"
    )
    meta.setEnabled(False)
    layout.addWidget(meta)

    buttons = QDialogButtonBox()
    add_btn = buttons.addButton("Add card", QDialogButtonBox.ButtonRole.AcceptRole)
    buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
    layout.addWidget(buttons)

    def do_add() -> None:
        # Sanitize before the fields become HTML in a note (QA-6): raw <script> /
        # on*= handlers or invisible chars must never reach a rendered card.
        front_text = ai.sanitize(front.text()).strip()
        back_text = ai.sanitize(back.toPlainText()).strip()
        if not front_text or not back_text:
            showWarning("A card needs both a front and a back.", parent=dialog)
            return
        # Provenance gate: only tag a REAL span id. If the draft has no verified
        # source, make the learner confirm rather than silently adding untraced.
        valid_span_ids = {s["id"] for s in spans}
        span_id = card["source_span"] if card["source_span"] in valid_span_ids else ""
        if not span_id and not askUser(
            "This card has no verified source span, so it won't trace back to a "
            "named source. Add it anyway?",
            parent=dialog,
            defaultno=True,
            title="No verified source",
        ):
            return
        col = mw.col
        notetype = col.models.by_name("Basic") or col.models.current()
        if notetype is None:
            showWarning("No note type is available to add a card.", parent=dialog)
            return
        note = col.new_note(notetype)
        note.fields[0] = front_text
        if len(note.fields) > 1:
            note.fields[1] = back_text
        tags = [topic.tag, "mcat::overflow"]
        if span_id:
            tags.append(f"mcat::src::{span_id}")
        note.tags = tags
        deck_id = col.decks.current()["id"]
        add_note(parent=mw, note=note, target_deck_id=deck_id).success(
            lambda _out: (tooltip("Added overflow card.", parent=mw), dialog.accept())
        ).run_in_background()

    qconnect(add_btn.clicked, do_add)
    qconnect(buttons.rejected, dialog.reject)

    dialog.resize(480, 360)
    dialog.exec()
