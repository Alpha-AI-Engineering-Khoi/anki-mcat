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
        src_topic, spans = ai.load_source()
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


def show(mw) -> None:  # type: ignore[no-untyped-def]
    """The launcher: pick a topic, then open Prime / Connect / Build."""
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
    dialog.setWindowTitle("Encode: Prime \u2192 Connect \u2192 Build")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            "Encode before you drill: prime the topic for the big picture, "
            "connect it to yourself, then build the map."
        )
    )

    combo = QComboBox()
    for t in topics:
        combo.addItem(f"{t.section} \u00b7 {t.name}", t.slug)
    layout.addWidget(combo)

    status = QLabel("")
    status.setEnabled(False)  # native secondary text (adapts to light/dark)
    layout.addWidget(status)

    prime_btn = QPushButton("\u2460 Prime\u2026")
    connect_btn = QPushButton("\u2461 Connect\u2026")
    build_btn = QPushButton("\u2462 Build\u2026")
    row = QHBoxLayout()
    for b in (prime_btn, connect_btn, build_btn):
        row.addWidget(b)
    layout.addLayout(row)

    def current_topic() -> "prog.Topic":
        return topics[max(0, combo.currentIndex())]

    def refresh() -> None:
        status.setText(_status_text(prog.get_record(mw.col, current_topic())))

    qconnect(combo.currentIndexChanged, lambda _i: refresh())
    qconnect(prime_btn.clicked, lambda: (_prime_dialog(mw, current_topic()), refresh()))
    qconnect(connect_btn.clicked, lambda: (_connect_dialog(mw, current_topic()), refresh()))
    qconnect(build_btn.clicked, lambda: (_build_dialog(mw, current_topic()), refresh()))

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(buttons)

    dialog.resize(540, 240)
    refresh()
    dialog.exec()


def open_for(mw, topic: "prog.Topic", stage: str | None = None) -> None:  # type: ignore[no-untyped-def]
    """Open one encode stage for a preselected topic (entry point for the Today
    panel). ``stage`` is "prime" / "connect" / "build"; anything else falls back
    to the topic-picker launcher. Keeps ``show(mw)`` as the standalone flow."""
    if stage == "prime":
        _prime_dialog(mw, topic)
    elif stage == "connect":
        _connect_dialog(mw, topic)
    elif stage == "build":
        _build_dialog(mw, topic)
    else:
        show(mw)


def _prime_dialog(mw, topic: "prog.Topic") -> None:  # type: ignore[no-untyped-def]
    from aqt.qt import (
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QLabel,
        QListWidget,
        QPlainTextEdit,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button, tooltip

    spans = _spans_for(topic)
    scope = ai.scope_list(spans, topic.name)
    rec = prog.get_record(mw.col, topic)

    dialog = QDialog(mw)
    dialog.setWindowTitle(f"Prime: {topic.name}")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel("Skim the whole topic for the big picture. Do NOT memorize details yet.")
    )
    layout.addWidget(QLabel("Scope / skim \u2014 the big ideas:"))
    scope_list = QListWidget()
    for s in scope:
        scope_list.addItem("\u2022 " + s)
    layout.addWidget(scope_list)

    checks = [
        QCheckBox("I have the big picture"),
        QCheckBox("I covered the whole topic"),
        QCheckBox("I did NOT memorize details"),
        QCheckBox("I can write 1\u20132 hypotheses"),
    ]
    for c in checks:
        layout.addWidget(c)

    layout.addWidget(QLabel("Your 1\u20132 hypotheses:"))
    hypotheses = QPlainTextEdit(rec.get("hypotheses", ""))
    hypotheses.setPlaceholderText("e.g. Enzymes lower activation energy without shifting equilibrium\u2026")
    layout.addWidget(hypotheses)

    if rec.get("primed"):
        for c in checks:
            c.setChecked(True)

    buttons = QDialogButtonBox()
    mark_btn = buttons.addButton("Mark primed", QDialogButtonBox.ButtonRole.ActionRole)
    buttons.addButton(QDialogButtonBox.StandardButton.Close)
    layout.addWidget(buttons)

    def revalidate() -> None:
        ready = all(c.isChecked() for c in checks) and bool(
            hypotheses.toPlainText().strip()
        )
        mark_btn.setEnabled(ready)

    def do_mark() -> None:
        prog.mark_primed(mw.col, topic, hypotheses.toPlainText().strip())
        tooltip(f"Primed \u201c{topic.name}\u201d.", parent=mw)
        dialog.accept()

    for c in checks:
        qconnect(c.stateChanged, lambda _s: revalidate())
    qconnect(hypotheses.textChanged, revalidate)
    qconnect(mark_btn.clicked, do_mark)
    qconnect(buttons.rejected, dialog.reject)

    revalidate()
    dialog.resize(540, 600)
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
        keyword = keywords[i % len(keywords)]
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
    from aqt.qt import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QPushButton,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        Qt,
        qconnect,
    )
    from aqt.utils import disable_help_button, showInfo, tooltip

    spans = _spans_for(topic)
    rec = prog.get_record(mw.col, topic)
    links: list[dict] = [dict(link) for link in rec.get("links", [])]
    next_id = [0]

    dialog = QDialog(mw)
    dialog.setWindowTitle(f"Build: {topic.name}")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    outer = QVBoxLayout(dialog)
    outer.addWidget(
        QLabel(
            "Lay out the backbone \u2192 chunks \u2192 sub-concepts \u2192 details, "
            "then link them. Warnings are hints, never blocks."
        )
    )

    panes = QHBoxLayout()
    outer.addLayout(panes)

    # --- concepts pane ---
    concepts_box = QGroupBox("Concepts (outline)")
    concepts_layout = QVBoxLayout(concepts_box)
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    concepts_layout.addWidget(tree)
    cbtns = QHBoxLayout()
    add_root_btn = QPushButton("Add root")
    add_child_btn = QPushButton("Add child")
    del_btn = QPushButton("Delete")
    draft_btn = QPushButton("Draft (AI)")
    for b in (add_root_btn, add_child_btn, del_btn, draft_btn):
        cbtns.addWidget(b)
    concepts_layout.addLayout(cbtns)
    panes.addWidget(concepts_box, 3)

    # --- links pane ---
    links_box = QGroupBox("Links")
    links_layout = QVBoxLayout(links_box)
    links_layout.addWidget(QLabel("Select a source concept, pick a target, name the relationship:"))
    target_combo = QComboBox()
    links_layout.addWidget(target_combo)
    rel_edit = QLineEdit()
    rel_edit.setPlaceholderText("relationship, e.g. causes / part of / contrast with")
    links_layout.addWidget(rel_edit)
    add_link_btn = QPushButton("Add link")
    links_layout.addWidget(add_link_btn)
    links_list = QListWidget()
    links_layout.addWidget(links_list)
    del_link_btn = QPushButton("Remove selected link")
    links_layout.addWidget(del_link_btn)
    panes.addWidget(links_box, 2)

    # --- warnings + overflow ---
    outer.addWidget(QLabel("Warnings (2\u20134 linter):"))
    warn_list = QListWidget()
    warn_list.setMaximumHeight(90)
    outer.addWidget(warn_list)

    buttons = QDialogButtonBox()
    overflow_btn = buttons.addButton(
        "Send to cards\u2026", QDialogButtonBox.ButtonRole.ActionRole
    )
    save_btn = buttons.addButton("Save map", QDialogButtonBox.ButtonRole.ActionRole)
    buttons.addButton(QDialogButtonBox.StandardButton.Close)
    outer.addWidget(buttons)

    def make_item(label: str, cid: int) -> "QTreeWidgetItem":
        item = QTreeWidgetItem([label])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(0, Qt.ItemDataRole.UserRole, cid)
        return item

    def collect() -> list[dict]:
        out: list[dict] = []

        def walk(item, parent_id) -> None:
            cid = item.data(0, Qt.ItemDataRole.UserRole)
            out.append({"id": cid, "parent": parent_id, "label": item.text(0).strip()})
            for i in range(item.childCount()):
                walk(item.child(i), cid)

        for i in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(i), None)
        return out

    def refresh_targets(concepts: list[dict]) -> None:
        target_combo.clear()
        for c in concepts:
            target_combo.addItem(c["label"] or "(unnamed)", c["id"])

    def refresh_links(concepts: list[dict]) -> None:
        label_of = {c["id"]: (c["label"] or "(unnamed)") for c in concepts}
        links_list.clear()
        for link in links:
            src = label_of.get(link["src"], "?")
            dst = label_of.get(link["dst"], "?")
            links_list.addItem(f"{src} \u2014[{link['label']}]\u2192 {dst}")

    def refresh_warnings(concepts: list[dict]) -> None:
        warn_list.clear()
        warnings = prog.lint_concepts(concepts, links)
        if not warnings:
            warn_list.addItem("No warnings \u2014 nicely chunked.")
            return
        for w in warnings:
            warn_list.addItem("\u26a0 " + w)

    def refresh_all() -> None:
        concepts = collect()
        refresh_targets(concepts)
        refresh_links(concepts)
        refresh_warnings(concepts)

    def add_root() -> None:
        text, ok = QInputDialog.getText(dialog, "Add concept", "Concept:")
        if ok and text.strip():
            tree.addTopLevelItem(make_item(text.strip(), next_id[0]))
            next_id[0] += 1
            refresh_all()

    def add_child() -> None:
        parent = tree.currentItem()
        if parent is None:
            showInfo("Select a concept first, then Add child.", parent=dialog)
            return
        text, ok = QInputDialog.getText(dialog, "Add sub-concept", "Sub-concept:")
        if ok and text.strip():
            parent.addChild(make_item(text.strip(), next_id[0]))
            next_id[0] += 1
            parent.setExpanded(True)
            refresh_all()

    def delete_current() -> None:
        item = tree.currentItem()
        if item is None:
            return
        removed = {
            c["id"]
            for c in _subtree_ids(item)
        }
        # prune links touching any removed concept
        links[:] = [
            link for link in links if link["src"] not in removed and link["dst"] not in removed
        ]
        parent = item.parent()
        if parent is None:
            tree.takeTopLevelItem(tree.indexOfTopLevelItem(item))
        else:
            parent.removeChild(item)
        refresh_all()

    def _subtree_ids(item) -> list[dict]:
        out = [{"id": item.data(0, Qt.ItemDataRole.UserRole)}]
        for i in range(item.childCount()):
            out.extend(_subtree_ids(item.child(i)))
        return out

    def draft_ai() -> None:
        candidates = ai.concept_candidates(spans, topic.name)
        for label in candidates:
            tree.addTopLevelItem(make_item(label, next_id[0]))
            next_id[0] += 1
        refresh_all()
        # ponytail: "suggest missing links" is a one-shot hint on unlinked
        # concepts, not an inline suggestion engine. Ceiling: no ranked link
        # proposals; the learner draws the relationships.
        concepts = collect()
        linked = {link["src"] for link in links} | {link["dst"] for link in links}
        unlinked = [c["label"] for c in concepts if c["id"] not in linked]
        msg = f"Added {len(candidates)} candidate concept(s) \u2014 edit or delete freely."
        if unlinked:
            msg += "\nNo links yet on: " + ", ".join(unlinked[:6])
        tooltip(msg, parent=mw, period=4000)

    def add_link() -> None:
        source = tree.currentItem()
        if source is None:
            showInfo("Select the source concept in the outline first.", parent=dialog)
            return
        if target_combo.currentIndex() < 0:
            showInfo("Add a concept to link to first.", parent=dialog)
            return
        src_id = source.data(0, Qt.ItemDataRole.UserRole)
        dst_id = target_combo.currentData()
        if src_id == dst_id:
            showInfo("Link two different concepts.", parent=dialog)
            return
        label = rel_edit.text().strip() or "relates to"
        links.append({"src": src_id, "dst": dst_id, "label": label})
        rel_edit.clear()
        refresh_all()

    def remove_link() -> None:
        row = links_list.currentRow()
        if 0 <= row < len(links):
            del links[row]
            refresh_all()

    def send_to_cards() -> None:
        item = tree.currentItem()
        if item is None:
            showInfo("Select the detail concept you couldn't relate.", parent=dialog)
            return
        if not spans:
            # No bundled source for this topic, so a card made here could not
            # trace back to a named source. Block it rather than adding untraced.
            showInfo(
                f"\u201c{topic.name}\u201d has no bundled source document yet, so a "
                "card made here couldn't be traced to a named source.\n\nSend to "
                "cards is disabled for this topic.",
                parent=dialog,
            )
            return
        _confirm_overflow_card(mw, topic, spans, item.text(0).strip())

    def persist() -> None:
        prog.save_build(mw.col, topic, collect(), list(links))

    def persist_on_close() -> None:
        # Don't write an empty record just because Build was opened; only save
        # when there's something now, or something was saved before.
        if collect() or links or rec.get("concepts") or rec.get("links"):
            persist()

    def do_save() -> None:
        persist()
        tooltip(f"Saved the map for \u201c{topic.name}\u201d.", parent=mw)

    # Load an existing map, then wire signals (so loading doesn't re-lint per row).
    saved_concepts = rec.get("concepts") or []
    if saved_concepts:
        item_by_id: dict = {}
        for c in saved_concepts:
            item_by_id[c["id"]] = make_item(c["label"], c["id"])
            next_id[0] = max(next_id[0], int(c["id"]) + 1)
        for c in saved_concepts:
            item = item_by_id[c["id"]]
            parent_id = c.get("parent")
            if parent_id is None or parent_id not in item_by_id:
                tree.addTopLevelItem(item)
            else:
                item_by_id[parent_id].addChild(item)
        tree.expandAll()

    qconnect(add_root_btn.clicked, add_root)
    qconnect(add_child_btn.clicked, add_child)
    qconnect(del_btn.clicked, delete_current)
    qconnect(draft_btn.clicked, draft_ai)
    qconnect(add_link_btn.clicked, add_link)
    qconnect(del_link_btn.clicked, remove_link)
    qconnect(overflow_btn.clicked, send_to_cards)
    qconnect(save_btn.clicked, do_save)
    qconnect(buttons.rejected, dialog.reject)
    qconnect(tree.itemChanged, lambda _i, _c: refresh_all())
    qconnect(dialog.finished, lambda _code: persist_on_close())

    refresh_all()
    dialog.resize(780, 560)
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
