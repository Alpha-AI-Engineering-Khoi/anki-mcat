# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Shared Qt helpers for the MCAT desktop panels (Readiness / Coverage / Weak
Topics). Keeps the panels to just their content HTML."""

from __future__ import annotations

import html as _html

def _night() -> bool:
    try:
        from aqt import theme

        return bool(theme.theme_manager.night_mode)
    except Exception:
        return False


# Accent + semantic colors resolved for the current Qt theme, so text stays
# legible (the old fixed values were tuned for dark and failed contrast on the
# light theme, e.g. MUTED "#888" is ~3.5:1 on white). ACCENT matches the iOS
# app's brand indigo. ponytail: hues are fixed at import; a mid-session
# light/dark toggle only restyles on the next app run, which is fine — the bar
# track (the worst offender on the wrong theme) is re-read live in bar().
_DARK = _night()
ACCENT = "#7c8cff" if _DARK else "#4b45c9"
GOOD = "#3fb984" if _DARK else "#157347"
WARN = "#e0912f" if _DARK else "#b23a0a"
BAD = "#e0564e" if _DARK else "#c0271f"
MUTED = "#9aa0a6" if _DARK else "#5d636e"


def esc(text: str) -> str:
    return _html.escape(str(text))


def bar(fraction: float, color: str) -> str:
    """A thin, full-width inline progress bar (0..1) as an HTML table.

    Qt's rich-text engine (QTextBrowser) ignores ``width`` set via the CSS
    ``style`` attribute on table cells — it only honors the HTML ``width``
    *attribute* — so a single style-sized fill cell renders as an even 50/50
    split regardless of value (why a 100% bar looked half full). Size BOTH cells
    with the ``width`` attribute (summing to 100%), and collapse to a single cell
    at the extremes so an empty 0%-width cell can't claim a minimum column width.
    """
    pct = max(0, min(100, round(fraction * 100)))
    fill = f"background:{color};height:8px"
    # Re-read the theme so an empty track never renders near-black on the light
    # theme (the previous fixed "#3a3a3a" did exactly that).
    track_bg = "#3a3a3a" if _night() else "#e6e8ec"
    track = f"background:{track_bg};height:8px"
    if pct >= 100:
        cells = f"<td style='{fill}'></td>"
    elif pct <= 0:
        cells = f"<td style='{track}'></td>"
    else:
        cells = (
            f"<td width='{pct}%' style='{fill}'></td>"
            f"<td width='{100 - pct}%' style='{track}'></td>"
        )
    return (
        f"<table cellspacing='0' cellpadding='0' width='100%' "
        f"style='margin:4px 0'><tr>{cells}</tr></table>"
    )


def show_html(mw, title: str, body_html: str, width: int = 580, height: int = 600) -> None:  # type: ignore[no-untyped-def]
    """Present read-only rich text in a modal, scrollable Close dialog."""
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QTextBrowser,
        QVBoxLayout,
        qconnect,
    )
    from aqt.utils import disable_help_button

    dialog = QDialog(mw)
    dialog.setWindowTitle(title)
    disable_help_button(dialog)
    mw.garbage_collect_on_dialog_finish(dialog)

    layout = QVBoxLayout(dialog)
    browser = QTextBrowser()
    browser.setOpenExternalLinks(False)
    browser.setHtml(f"<div style='font-size:13px; line-height:1.4'>{body_html}</div>")
    layout.addWidget(browser)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    qconnect(buttons.rejected, dialog.reject)
    qconnect(buttons.accepted, dialog.accept)
    layout.addWidget(buttons)

    dialog.resize(width, height)
    dialog.exec()
