# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Re-runnable held-out eval for the MCAT AI layer (challenges 7f + 7e).

Factual judging is the live LLM judge's job (--live). With AI OFF the eval is
deterministic but the judge is only a STRUCTURAL screen, so offline it reports
just the parts it can stand behind (structure + leakage + baseline) and defers
the factual verdict to --live -- it never claims an offline factual accuracy. It:
  1. drafts cards from the bundled source, and also runs a simpler baseline;
  2. screens every card with Card Check (structural offline; factual with --live);
  3. checks that Draft beats the baseline on correct-useful rate;
  4. with --live, measures the judge against the human-labeled set (accuracy +
     the safety metric: leaked-wrong rate) so we never trust the judge blind;
  5. scans the source for leakage of the gold/test items (7e);
  6. applies a cutoff declared BEFORE looking and blocks failures.

Run:  python mcat_eval.py           (offline: structure + leakage + baseline)
      python mcat_eval.py --live    (live LLM judge: the real factual verdict)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mcat_ai  # noqa: E402
import mcat_cardcheck as cc  # noqa: E402

# --- cutoff, pre-registered BEFORE looking at any result ---------------------
MAX_LEAKED_WRONG_RATE = 0.10   # judge must not pass >10% truly-wrong cards
MIN_JUDGE_PRECISION = 0.75     # of cards judged correct-useful, >=75% must be
MAX_LEAKAGE = 0                # zero near-copies of the gold/test set allowed
LEAKAGE_JACCARD = 0.85


def _load_jsonl(name: str) -> list[dict]:
    path = mcat_ai.DATA_DIR / name
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _classify_set(cards: list[dict], src: str, gold: list[dict],
                  live: bool) -> dict[str, int]:
    counts = {cc.CORRECT: 0, cc.WRONG: 0, cc.BAD_TEACHING: 0}
    for card in cards:
        counts[cc.classify(card, src, gold, live=live)] += 1
    return counts


def _quality(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    return counts[cc.CORRECT] / total if total else 0.0


def _source_leakage(spans: list[dict], gold: list[dict]) -> list[dict]:
    """7e: is the source we feed the AI clean of the gold/test items? A source
    that already contains the test Q/A would inflate results."""
    flagged = []
    for g in gold:
        gtext = g["front"] + " " + g["back"]
        for s in spans:
            if mcat_ai.jaccard(gtext, s["text"]) >= LEAKAGE_JACCARD:
                flagged.append({"gold": g["id"], "span": s["id"]})
                break
    return flagged


def _dup_vs_gold(drafted: list[dict], gold: list[dict]) -> list[dict]:
    """Info only: drafted cards that duplicate an existing gold card (would be
    de-duplicated before adding). Not contamination, since Draft reads the
    source, not the gold answer key."""
    flagged = []
    for c in drafted:
        for g in gold:
            if (mcat_ai.jaccard(c["front"], g["front"]) >= LEAKAGE_JACCARD or
                    mcat_ai.jaccard(c["back"], g["back"]) >= LEAKAGE_JACCARD):
                flagged.append(c["front"])
                break
    return flagged


def run(live: bool = False) -> dict:
    topic, spans = mcat_ai.load_source()
    src = mcat_ai.source_text(spans)
    gold = _load_jsonl("goldset.jsonl")
    labeled = _load_jsonl("judge_labels.jsonl")

    drafted = mcat_ai.draft_cards(spans, topic, live=live)
    baseline = mcat_ai.baseline_cards(spans, topic)

    draft_counts = _classify_set(drafted, src, gold, live)
    base_counts = _classify_set(baseline, src, gold, live)
    draft_q, base_q = _quality(draft_counts), _quality(base_counts)

    cal = cc.calibrate(labeled, src, gold, live=live)
    leaks = _source_leakage(spans, gold)
    dups = _dup_vs_gold(drafted, gold)

    beats_baseline = draft_q > base_q
    # Factual judging happens ONLY with the live LLM judge. Offline, Card Check
    # is a STRUCTURAL screen (mcat_cardcheck.offline_judge), so its accuracy /
    # leaked-wrong measure structure, not truth -- they must NOT gate a factual
    # verdict. Offline we stand behind only the deterministic parts (leakage +
    # beats-baseline); the factual verdict requires --live.
    factual = bool(live)
    deterministic_ok = len(leaks) <= MAX_LEAKAGE and beats_baseline
    if factual:
        verdict = "PASS" if (
            deterministic_ok
            and cal["leaked_wrong_rate"] <= MAX_LEAKED_WRONG_RATE
            and cal["precision_correct_useful"] >= MIN_JUDGE_PRECISION
        ) else "FAIL"
    else:
        verdict = ("PASS (deterministic only \u2014 run --live for the factual judge)"
                   if deterministic_ok else "FAIL (deterministic checks)")
    shipped = draft_counts[cc.CORRECT]
    blocked = draft_counts[cc.WRONG] + draft_counts[cc.BAD_TEACHING]

    report = {
        "mode": "live" if live else "offline",
        "ai_available": mcat_ai.ai_available(),
        "factual_checked": factual,
        "topic": topic,
        "spans": len(spans),
        "draft": draft_counts, "draft_quality": round(draft_q, 3),
        "baseline": base_counts, "baseline_quality": round(base_q, 3),
        "beats_baseline": beats_baseline,
        "calibration": cal,
        "leakage_flagged": len(leaks),
        "dup_vs_gold": len(dups),
        "shipped": shipped, "blocked": blocked,
        "verdict": verdict,
    }
    _print(report)
    return report


def _print(r: dict) -> None:
    factual = r["factual_checked"]
    print(f"\nMCAT AI eval  (mode: {r['mode']}, ai_available={r['ai_available']})")
    print(f"Source: {r['topic']}  ({r['spans']} spans)")
    print("Pre-registered cutoff: leaked-wrong <= "
          f"{int(MAX_LEAKED_WRONG_RATE*100)}%, precision(correct-useful) >= "
          f"{MIN_JUDGE_PRECISION}, leakage <= {MAX_LEAKAGE}, draft beats baseline")
    d, b = r["draft"], r["baseline"]
    tag = "" if factual else "  (structural screen only)"
    print(f"\nDraft:    {sum(d.values()):>3} cards -> "
          f"correct-useful {d['correct-useful']}, bad-teaching "
          f"{d['correct-but-bad-teaching']}, wrong {d['wrong']}  "
          f"(quality={r['draft_quality']}){tag}")
    print(f"Baseline: {sum(b.values()):>3} cards -> "
          f"correct-useful {b['correct-useful']}, bad-teaching "
          f"{b['correct-but-bad-teaching']}, wrong {b['wrong']}  "
          f"(quality={r['baseline_quality']}){tag}")
    print(f"Beats baseline: {'YES' if r['beats_baseline'] else 'NO'}" +
          ("" if factual
           else "  (structural/format quality; factual comparison needs --live)"))
    c = r["calibration"]
    if factual:
        print(f"\nJudge vs human labels (n={c['n']}): accuracy={c['accuracy']}, "
              f"leaked-wrong rate={c['leaked_wrong_rate']}, "
              f"precision(correct-useful)={c['precision_correct_useful']}")
    else:
        print("\nJudge (offline): STRUCTURAL screen only \u2014 NOT a factual check. "
              "Keyword/regex can't verify truth, so no factual accuracy/leaked-wrong "
              "is claimed offline. Run with --live for the real LLM judge.")
    print(f"Leakage (7e) source vs gold/test items: {r['leakage_flagged']} "
          f"(threshold jaccard>={LEAKAGE_JACCARD}); drafted duplicating a gold "
          f"card: {r['dup_vs_gold']} (info, de-duplicated)")
    print(f"\nBlock failures: ship {r['shipped']} correct-useful, "
          f"block {r['blocked']}.")
    print(f"VERDICT: {r['verdict']}\n")


if __name__ == "__main__":
    run(live="--live" in sys.argv)
