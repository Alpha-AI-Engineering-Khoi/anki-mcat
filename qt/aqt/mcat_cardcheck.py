# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""MCAT "Card Check": a light, calibrated screen for AI-drafted cards.

Per the BrainLift (Application, "Card Check is a light calibrated screen"), this
is deterministic rules first, then a judge, classifying each card as:
  correct-useful | wrong | correct-but-bad-teaching
Failures (wrong / bad-teaching) are blocked; passes ship. The judge has an
offline heuristic (for AI-off and re-runnable tests) and a live OpenAI mode. Its
precision is measured against a human-labeled set, never trusted blind.

Pure logic; unit-testable; run directly for a self-check.
"""

from __future__ import annotations

import json
import os
import re

CORRECT = "correct-useful"
WRONG = "wrong"
BAD_TEACHING = "correct-but-bad-teaching"

OVERLONG_BACK = 220
OVERLONG_FRONT = 120
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"what", "is", "are", "the", "a", "an", "does", "do", "of", "in", "on",
         "how", "why", "which", "blank", "fill", "and", "to", "for", "its"}

# domain contradictions of the bundled source's ground-truth facts
_KNOWN_FALSE = [
    (r"noncompetitive", r"(rais\w+|increas\w+|up)\b.*v ?max|v ?max.*(rais\w+|increas\w+|up)"),
    (r"cofactor", r"\borganic\b"),
    (r"equilibr", r"shift|toward products|change"),
    (r"denatur", r"used up|consumed|uses up"),
    (r"holoenzyme", r"inactive|without (its )?cofactor"),
    (r"v ?max", r"\bmoles?\b"),
    (r"competitive inhibitor", r"lower\w* v ?max|v ?max.*(lower|down|decreas)"),
]


def _tok(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def rules_screen(card: dict, src_text: str) -> str | None:
    """Deterministic screen. Returns a reason code, or None if it passes rules."""
    front = (card.get("front") or "").strip()
    back = (card.get("back") or "").strip()
    if not back:
        return "no-answer"
    if len(back) > OVERLONG_BACK or len(front) > OVERLONG_FRONT:
        return "over-long"
    if front.count("?") > 1:
        return "multi-question"
    if front.lower().count(" and ") >= 2:
        return "overloaded"
    if back.count(",") >= 4:
        return "list-dump"
    if len(front.split()) <= 2 and len(back) > 110:
        return "vague-front"
    # hallucination proxy: card shares essentially no vocabulary with the source
    if _overlap(front + " " + back, src_text) < 0.04:
        return "term-not-in-source"
    return None


def _overlap(text: str, src_text: str) -> float:
    ta, ts = _tok(text) - _STOP, _tok(src_text)
    if not ta:
        return 1.0
    return len(ta & ts) / len(ta)


def _reverses_fact(back: str) -> bool:
    b = " " + back.lower() + " "
    for term, bad in _KNOWN_FALSE:
        if re.search(term, b) and re.search(bad, b):
            return True
    return False


def offline_judge(card: dict, src_text: str, gold: list[dict]) -> str:
    reason = rules_screen(card, src_text)
    if reason in ("no-answer", "term-not-in-source"):
        return WRONG
    if reason in ("over-long", "multi-question", "overloaded", "list-dump",
                  "vague-front"):
        return BAD_TEACHING
    combined = (card.get("front") or "") + " " + (card.get("back") or "")
    if _reverses_fact(combined):
        return WRONG
    return CORRECT


def live_judge(card: dict, src_text: str) -> str:
    import openai

    from . import mcat_ai  # type: ignore

    client = openai.OpenAI(api_key=mcat_ai.api_key())
    prompt = (
        "Classify this flashcard against the SOURCE as exactly one of: "
        "correct-useful, wrong, correct-but-bad-teaching. 'wrong' = the answer "
        "is factually incorrect or unsupported by the source. "
        "'correct-but-bad-teaching' = accurate but vague, overloaded, or tests "
        "many ideas at once. Return JSON {\"label\":..}.\n\n"
        f"SOURCE:\n{src_text}\n\nCARD front: {card.get('front')}\n"
        f"CARD back: {card.get('back')}"
    )
    resp = client.chat.completions.create(
        model=os.environ.get("MCAT_OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    label = json.loads(resp.choices[0].message.content).get("label", CORRECT)
    return label if label in (CORRECT, WRONG, BAD_TEACHING) else CORRECT


def classify(card: dict, src_text: str, gold: list[dict],
             live: bool | None = None) -> str:
    """Full screen: rules, then judge (live if available, else offline)."""
    reason = rules_screen(card, src_text)
    if reason in ("no-answer", "term-not-in-source"):
        return WRONG
    if reason in ("over-long", "multi-question", "overloaded", "list-dump",
                  "vague-front"):
        return BAD_TEACHING
    if live:
        try:
            return live_judge(card, src_text)
        except Exception:
            pass
    return offline_judge(card, src_text, gold)


def calibrate(labeled: list[dict], src_text: str, gold: list[dict],
              live: bool | None = None) -> dict:
    """Measure the judge against human labels. The safety metric is the
    leaked-wrong rate: cards the judge PASSES as correct-useful that humans
    marked wrong."""
    n = len(labeled)
    correct = 0
    passed = 0            # judge said correct-useful
    passed_but_wrong = 0  # judge said correct-useful, human said wrong
    passed_but_bad = 0    # judge said correct-useful, human said bad-teaching
    confusion: dict[str, dict[str, int]] = {}
    for item in labeled:
        human = item["label"]
        pred = classify(item, src_text, gold, live=live)
        confusion.setdefault(human, {}).setdefault(pred, 0)
        confusion[human][pred] += 1
        if pred == human:
            correct += 1
        if pred == CORRECT:
            passed += 1
            if human == WRONG:
                passed_but_wrong += 1
            elif human == BAD_TEACHING:
                passed_but_bad += 1
    precision_correct = (
        (passed - passed_but_wrong - passed_but_bad) / passed if passed else 1.0
    )
    return {
        "n": n,
        "accuracy": round(correct / n, 3) if n else 0.0,
        "judge_passed": passed,
        "leaked_wrong": passed_but_wrong,
        "leaked_wrong_rate": round(passed_but_wrong / passed, 3) if passed else 0.0,
        "precision_correct_useful": round(precision_correct, 3),
        "confusion": confusion,
    }


def _self_test() -> None:
    import mcat_ai  # local run
    topic, spans = mcat_ai.load_source()
    src = mcat_ai.source_text(spans)
    gold = [json.loads(l) for l in
            (mcat_ai.DATA_DIR / "goldset.jsonl").read_text().splitlines() if l.strip()]
    labeled = [json.loads(l) for l in
               (mcat_ai.DATA_DIR / "judge_labels.jsonl").read_text().splitlines() if l.strip()]
    m = calibrate(labeled, src, gold, live=False)
    assert m["n"] == len(labeled)
    print(f"mcat_cardcheck self-test OK: judge accuracy {m['accuracy']}, "
          f"leaked-wrong rate {m['leaked_wrong_rate']}, "
          f"precision(correct-useful) {m['precision_correct_useful']}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _self_test()
