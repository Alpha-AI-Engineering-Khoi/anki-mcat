# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Standalone "AI: Generate flashcards" panel.

Deliberately SEPARATE from the Encode workflow so the two features don't tangle.
It generates atomic MCAT flashcards grounded in a LIVE web search
(Wikipedia/LibreTexts) with real per-card citations, lets the learner pick which
to keep, and adds them as notes tagged to the topic + their source. The web call
runs off the UI thread; the graded eval is unaffected (it stays on the fixed
curated docs).
"""

from __future__ import annotations

import re


def show(mw) -> None:  # type: ignore[no-untyped-def]
    from aqt import mcat_ai as ai
    from aqt import mcat_program as prog
    from aqt import mcat_websearch as ws
    from aqt.operations import CollectionOp, QueryOp
    from aqt.qt import (
        QComboBox,
        QDialog,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        Qt,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button, openLink, showWarning, tooltip

    topics = prog.all_topics()
    state: dict = {"cards": []}

    dialog = QDialog(mw)
    dialog.setWindowTitle("Generate flashcards")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(
        "Week-4 gap-catcher: the AI drafts atomic, source-cited cards focused on "
        "the concepts you mapped in Mindmap but couldn't connect (the gaps). "
        "Review the sources, then keep the ones you want."
    ))

    combo = QComboBox()
    combo.setMaxVisibleItems(20)
    combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
    for t in topics:
        combo.addItem(f"{t.section} \u00b7 {t.name}", t.slug)
    layout.addWidget(combo)

    # Default to the program's current-day topic (the natural gap-catcher target).
    from aqt import mcat_today as _today
    try:
        _cal = _today.ensure_started(mw.col)
        _cur = _today.topic_for_day(
            _today.effective_day_index(
                _cal["start_date"], _today._today_str(), _today.get_day_override(mw.col)
            ),
            topics,
        )
        combo.setCurrentIndex(next((i for i, t in enumerate(topics) if t.slug == _cur.slug), 0))
    except Exception:
        pass

    gaps_label = QLabel("")
    gaps_label.setWordWrap(True)
    gaps_label.setEnabled(False)
    layout.addWidget(gaps_label)

    gen_btn = QPushButton("Generate cards")
    layout.addWidget(gen_btn)

    hint = QLabel(
        "Tick the cards to keep. Select a card and click \u201cCheck source\u201d "
        "to open where it came from."
    )
    hint.setEnabled(False)
    layout.addWidget(hint)

    cards_list = QListWidget()
    layout.addWidget(cards_list)

    def current_topic() -> "prog.Topic":
        return topics[max(0, combo.currentIndex())]

    def topic_gaps(topic) -> list[str]:
        rec = prog.get_record(mw.col, topic)
        return prog.gap_concepts(rec.get("concepts", []), rec.get("links", []))

    def refresh_gaps() -> None:
        gaps = topic_gaps(current_topic())
        if gaps:
            shown = ", ".join(gaps[:8]) + ("\u2026" if len(gaps) > 8 else "")
            gaps_label.setText(f"Gaps in your Mindmap map ({len(gaps)}): {shown}")
        else:
            gaps_label.setText(
                "No saved Mindmap map for this topic \u2014 cards will cover it broadly. "
                "Build a map in Mindmap first to target the gaps."
            )

    qconnect(combo.currentIndexChanged, lambda _i: refresh_gaps())
    refresh_gaps()

    def on_generate() -> None:
        if not ws.available():
            showWarning(
                "AI is off (no key, or offline). This generator needs a live "
                "connection and an OpenAI key.", parent=dialog)
            return
        topic = current_topic()
        gen_btn.setEnabled(False)
        check_btn.setEnabled(False)
        cards_list.clear()
        cards_list.addItem("Generating flashcards\u2026")

        gaps = topic_gaps(topic)
        query = topic.name
        if gaps:
            query = (
                f"{topic.name} \u2014 focus specifically on these concepts the student "
                f"mapped but could not connect: {', '.join(gaps[:12])}"
            )

        def op(_col):  # type: ignore[no-untyped-def]
            return ws.draft_cards(query, n=10, reasoning="low")

        def done(res: dict) -> None:
            state["cards"] = res.get("cards", [])
            cards_list.clear()
            if not state["cards"]:
                cards_list.addItem("No cards returned \u2014 try Generate again.")
            for c in state["cards"]:
                item = QListWidgetItem(f"Q: {c['front']}\nA: {c['back']}")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # Pre-tick only cards whose source was actually consulted.
                item.setCheckState(Qt.CheckState.Checked if c.get("grounded")
                                   else Qt.CheckState.Unchecked)
                cards_list.addItem(item)
            gen_btn.setEnabled(True)

        def fail(exc: Exception) -> None:
            cards_list.clear()
            cards_list.addItem("Generation failed \u2014 try again.")
            gen_btn.setEnabled(True)
            showWarning(f"Generation failed: {exc}", parent=dialog)

        QueryOp(parent=mw, op=op, success=done).failure(fail).with_progress(
            "Generating flashcards\u2026").run_in_background()

    qconnect(gen_btn.clicked, on_generate)

    check_btn = QPushButton("Check source")
    check_btn.setEnabled(False)
    add_btn = QPushButton("Add selected cards")
    add_btn.setDefault(True)
    close_btn = QPushButton("Close")

    bottom = QHBoxLayout()
    bottom.addWidget(close_btn)
    bottom.addStretch(1)
    bottom.addWidget(check_btn)
    bottom.addWidget(add_btn)
    layout.addLayout(bottom)

    qconnect(close_btn.clicked, dialog.reject)

    def current_card() -> "dict | None":
        row = cards_list.currentRow()
        if 0 <= row < len(state["cards"]):
            return state["cards"][row]
        return None

    def on_row_changed() -> None:
        c = current_card()
        link = (c.get("source_highlight_url") or c.get("source_url") or "") if c else ""
        check_btn.setEnabled(bool(link.strip()))

    def on_check_source() -> None:
        c = current_card()
        # Prefer the highlight URL: opens the page scrolled to the exact extract.
        url = (c.get("source_highlight_url") or c.get("source_url") or "").strip() if c else ""
        if not url:
            tooltip("This card has no source link.", parent=mw)
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        openLink(url)

    qconnect(cards_list.itemSelectionChanged, on_row_changed)
    qconnect(cards_list.itemDoubleClicked, lambda _it: on_check_source())
    qconnect(check_btn.clicked, on_check_source)

    def selected_cards() -> list[dict]:
        out = []
        for i, c in enumerate(state["cards"]):
            item = cards_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                out.append(c)
        return out

    def on_add() -> None:
        picked = selected_cards()
        if not picked:
            tooltip("Tick at least one card to add.", parent=mw)
            return
        topic = current_topic()

        def op(col):  # type: ignore[no-untyped-def]
            pos = col.add_custom_undo_entry("Add AI cards")
            notetype = col.models.by_name("Basic") or col.models.current()
            did = col.decks.current()["id"]
            for c in picked:
                note = col.new_note(notetype)
                note.fields[0] = ai.sanitize(c["front"]).strip()
                if len(note.fields) > 1:
                    note.fields[1] = ai.sanitize(c["back"]).strip()
                tags = [topic.tag, "mcat::ai"]
                su = (c.get("source_url") or "").strip()
                if su:
                    tags.append("mcat::src::" + re.sub(r"^https?://", "", su).replace(" ", ""))
                note.tags = tags
                col.add_note(note, did)
            return col.merge_undo_entries(pos)

        CollectionOp(parent=mw, op=op).success(
            lambda _out: (tooltip(f"Added {len(picked)} cited card(s).", parent=mw),
                          dialog.accept())
        ).run_in_background()

    qconnect(add_btn.clicked, on_add)

    dialog.resize(680, 560)
    dialog.exec()
