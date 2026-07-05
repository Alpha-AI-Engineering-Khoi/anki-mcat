# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Desktop MCAT Scores — one panel, two tabs sharing a single deck picker:

- **Readiness**: the three honest scores (Memory / Performance / Readiness).
- **Coverage**: the per-section AAMC coverage map.

Both reuse the existing, tested renders from ``mcat_readiness`` / ``mcat_coverage``
and the shared ``mcat_models`` logic; this module only wires them into one
``deck_scoped_tabs`` panel so the learner can switch between the metrics.
"""

from __future__ import annotations

from aqt import mcat_coverage as coverage
from aqt import mcat_models as m
from aqt import mcat_readiness as readiness
from aqt import mcat_ui as ui


def show(mw) -> None:  # type: ignore[no-untyped-def]
    decks = m.scorable_decks(mw.col)
    ui.deck_scoped_tabs(
        mw,
        "MCAT Scores",
        decks,
        tabs=[
            ("Readiness", lambda col, sel: m.assess(col, sel), readiness._render),
            ("Coverage", lambda col, sel: m.gather_coverage(col, sel), coverage._render),
        ],
    )
