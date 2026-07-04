# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Desktop MCAT Speedrun Library: browse and one-tap import curated decks.

Lists decks from the public Supabase "Library" (a read-only catalog table plus a
public storage bucket of .apkg files) and imports the chosen deck straight into
the collection with scheduling enabled - so the readiness score and
points-at-stake have data immediately. This is read-only against the backend:
the app only GETs the catalog and downloads files; uploads are admin-only.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass, field

# Public Supabase project. The anon key is designed to ship in clients: it only
# grants the public-read access the Library's row-level-security policies allow
# (read the catalog + download from the public bucket); it cannot write.
SUPABASE_URL = "https://jscreeiypfopowtquriu.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpzY3JlZWl5cGZvcG93dHF1cml1Iiwicm9sZSI6"
    "ImFub24iLCJpYXQiOjE3ODI5MzM2OTAsImV4cCI6MjA5ODUwOTY5MH0."
    "PIhKqznEhNLilhR2-bs60qetVzvWRcx1SrlZHZdZ7yM"
)
_TABLE = "decks"
_BUCKET = "decks"
_TIMEOUT = 30


@dataclass
class LibraryDeck:
    id: str
    title: str
    description: str
    card_count: int
    sections: list[str] = field(default_factory=list)
    storage_path: str = ""


def fetch_decks() -> list[LibraryDeck]:
    """GET the public deck catalog (read-only)."""
    url = (
        f"{SUPABASE_URL}/rest/v1/{_TABLE}"
        "?select=id,title,description,card_count,sections,storage_path"
        "&order=created_at.desc"
    )
    req = urllib.request.Request(
        url,
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    return [
        LibraryDeck(
            id=str(r.get("id", "")),
            title=r.get("title") or "(untitled)",
            description=r.get("description") or "",
            card_count=int(r.get("card_count") or 0),
            sections=list(r.get("sections") or []),
            storage_path=r.get("storage_path") or "",
        )
        for r in rows
    ]


def download_deck(storage_path: str) -> str:
    """Download a deck's .apkg from the public bucket to a temp file; return path."""
    url = f"{SUPABASE_URL}/storage/v1/object/public/{_BUCKET}/{storage_path}"
    fd, tmp = tempfile.mkstemp(prefix="mcat_library_", suffix=".apkg")
    os.close(fd)
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp, open(tmp, "wb") as fh:
        fh.write(resp.read())
    return tmp


def import_apkg(col, path: str, deck_name: str | None = None):  # type: ignore[no-untyped-def]
    """Import a downloaded .apkg with scheduling, name the imported deck after the
    Library catalog title (so the Library is the single source of truth for the
    deck's name — the .apkg's own embedded name can differ), then enable FSRS
    collection-wide so the Readiness Memory score (mean FSRS retrievability) can
    populate as the imported cards are reviewed. Idempotent: only flips FSRS on if
    it's off."""
    from anki.collection import ImportAnkiPackageRequest

    before = {d["name"] for d in col.decks.all()}
    presets = col._backend.get_import_anki_package_presets()
    presets.with_scheduling = True
    result = col.import_anki_package(
        ImportAnkiPackageRequest(package_path=path, options=presets)
    )
    if deck_name:
        _rename_imported_deck(col, before, deck_name)
    # FSRS is a collection-wide setting (the Deck Options toggle writes this same
    # config key); turning it on here means Memory works without the learner
    # hunting through Deck Options.
    if not col.get_config("fsrs", False):
        col.set_config("fsrs", True)
    return result


def _rename_imported_deck(col, before_names, deck_name: str) -> None:  # type: ignore[no-untyped-def]
    """Rename the single new top-level deck the import created to `deck_name`.

    Uses a before/after name diff so it works regardless of the .apkg's embedded
    deck name. No-op if the import created zero or several new top-level decks (an
    ambiguous case we won't guess at) or the name already matches. `decks.rename`
    reparents any subdecks under the new name."""
    new_tops = [
        d for d in col.decks.all()
        if d["name"] not in before_names and "::" not in d["name"] and d["name"] != "Default"
    ]
    if len(new_tops) != 1 or new_tops[0]["name"] == deck_name:
        return
    col.decks.rename(new_tops[0], deck_name)


@dataclass
class _BatchImportResult:
    """Return value of the batch-import background op.

    CollectionOp passes this to the success callback (which reads ``count`` for
    the summary tooltip) and afterwards reads ``.changes`` to refresh the UI and
    undo state, so we carry the last import's changes alongside the count."""

    count: int
    changes: object


def show(mw) -> None:  # type: ignore[no-untyped-def]
    """Open the MCAT Speedrun Library browser for the given main window."""
    from aqt.operations import CollectionOp, QueryOp
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button, showWarning, tooltip

    dialog = QDialog(mw)
    dialog.setWindowTitle("MCAT Speedrun Library")
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            "Curated MCAT decks. Pick one or more and import them — scheduling is "
            "included, so your readiness score and weak-topics show right away."
        )
    )

    listw = QListWidget()
    # Multi-select: pick several decks (Cmd/Ctrl- or Shift-click) and import them
    # all in one action.
    listw.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
    layout.addWidget(listw)

    detail = QLabel("")
    detail.setWordWrap(True)
    # Native secondary text: a disabled-role label adapts to light/dark instead
    # of a fixed "#888" that failed contrast on the light theme.
    detail.setEnabled(False)
    layout.addWidget(detail)

    buttons = QDialogButtonBox()
    import_btn = buttons.addButton(
        "Import", QDialogButtonBox.ButtonRole.ActionRole
    )
    refresh_btn = buttons.addButton("Refresh", QDialogButtonBox.ButtonRole.ActionRole)
    close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
    import_btn.setEnabled(False)
    layout.addWidget(buttons)

    decks: list[LibraryDeck] = []

    def selected_decks() -> list[LibraryDeck]:
        rows = sorted(idx.row() for idx in listw.selectedIndexes())
        return [decks[r] for r in rows if 0 <= r < len(decks)]

    def on_select() -> None:
        sel = selected_decks()
        importable = [d for d in sel if d.storage_path]
        import_btn.setEnabled(bool(importable))
        if len(sel) == 1:
            d = sel[0]
            secs = ", ".join(d.sections) if d.sections else "—"
            detail.setText(f"{d.description}\n\n{d.card_count} cards · {secs}")
        elif len(sel) > 1:
            detail.setText(f"{len(sel)} decks selected")
        elif not decks:
            detail.setText("The Library is empty.")
        else:
            detail.setText("")

    def populate(loaded: list[LibraryDeck]) -> None:
        nonlocal decks
        decks = loaded
        listw.clear()
        for d in decks:
            QListWidgetItem(f"{d.title}  ({d.card_count} cards)", listw)
        if decks:
            listw.setCurrentRow(0)
        on_select()

    def on_err(err: Exception) -> None:
        showWarning(f"Could not reach the MCAT Library:\n{err}", parent=dialog)

    def load() -> None:
        QueryOp(
            parent=dialog, op=lambda _: fetch_decks(), success=populate
        ).with_progress("Loading MCAT Library…").failure(on_err).run_in_background()

    def import_decks(to_import: list[LibraryDeck]) -> None:
        # Only decks that actually have a downloadable file can be imported.
        to_import = [d for d in to_import if d.storage_path]
        if not to_import:
            return
        import_btn.setEnabled(False)

        def op(col):  # type: ignore[no-untyped-def]
            # Download + import each selected deck on the background thread (safe,
            # off the UI thread). Each import_apkg renames the imported deck to
            # the catalog title and enables FSRS. We hand back a count for the
            # tooltip plus the last import's `.changes` for CollectionOp.
            count = 0
            last = None
            for d in to_import:
                tmp = download_deck(d.storage_path)
                try:
                    last = import_apkg(col, tmp, d.title)
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                count += 1
            return _BatchImportResult(count=count, changes=last.changes)

        def imported(result: _BatchImportResult) -> None:
            noun = "deck" if result.count == 1 else "decks"
            tooltip(
                f"Imported {result.count} {noun} and enabled FSRS. Select a deck, "
                "then Tools › MCAT › Readiness.",
                parent=mw,
            )
            dialog.accept()

        CollectionOp(parent=dialog, op=op).success(imported).failure(
            lambda e: (import_btn.setEnabled(True), on_err(e))
        ).run_in_background()

    def do_import() -> None:
        import_decks(selected_decks())

    def do_import_item(item) -> None:  # type: ignore[no-untyped-def]
        # Double-click always imports just that one deck, regardless of the
        # wider multi-selection.
        row = listw.row(item)
        if 0 <= row < len(decks):
            import_decks([decks[row]])

    qconnect(listw.itemSelectionChanged, on_select)
    qconnect(listw.itemDoubleClicked, do_import_item)
    qconnect(import_btn.clicked, do_import)
    qconnect(refresh_btn.clicked, load)
    qconnect(close_btn.clicked, dialog.reject)

    dialog.resize(540, 480)
    load()
    dialog.exec()
