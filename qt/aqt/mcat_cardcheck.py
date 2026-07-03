# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""MCAT "Card Check": screen AI-drafted cards for structure and (AI on) facts.

Deterministic STRUCTURAL rules first (no answer, over-long, overloaded,
list-dump, off-topic), then a FACTUAL judge. Factual judging is the live LLM
judge, which judges each card against the source. Offline there is NO factual
judge -- keyword/regex cannot verify truth (an earlier attempt was circular,
fit to its own labels, and leaked ~45% of genuinely wrong cards), so offline
only the structural screen runs and the eval reports offline results as
structural-only. The live judge FAILS CLOSED: an unusable response never
auto-passes a card. Classes: correct-useful | wrong | correct-but-bad-teaching.

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


def offline_judge(card: dict, src_text: str, gold: list[dict]) -> str:
    """STRUCTURAL screen only. Offline (no LLM) we cannot verify factual
    correctness: regex keyword matching can't tell true from false, and QA
    showed the previous hand-written contradiction table was circular (fit to
    its own labels) and leaked ~45% of genuinely wrong cards. So the offline
    judge catches only STRUCTURAL problems -- missing/off-topic answer -> wrong;
    over-long / overloaded / list-dump / vague -> bad-teaching. A card that
    passes structure returns CORRECT meaning "passed the structural screen", NOT
    "verified true". Factual judging is the live LLM judge's job, and the eval
    reports offline results as structural-only (never as a factual accuracy)."""
    reason = rules_screen(card, src_text)
    if reason in ("no-answer", "term-not-in-source"):
        return WRONG
    if reason in ("over-long", "multi-question", "overloaded", "list-dump",
                  "vague-front"):
        return BAD_TEACHING
    return CORRECT


def live_judge(card: dict, src_text: str) -> str:
    """The real factual checker: an LLM judges the card against the source. Fails
    CLOSED -- an unusable response raises so classify() falls back to the
    structural screen instead of shipping an unverified card as correct."""
    import openai

    try:  # package-relative inside aqt; plain import for eval / tests / standalone
        from . import mcat_ai  # type: ignore
    except Exception:
        import mcat_ai  # type: ignore

    # timeout so a stalled network can't hang the UI (QA-5); model_for lets the
    # safety-critical judge run on a stronger model via MCAT_OPENAI_MODEL_JUDGE.
    client = openai.OpenAI(api_key=mcat_ai.api_key(), timeout=mcat_ai.API_TIMEOUT)
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
        model=mcat_ai.model_for("judge"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    label = json.loads(resp.choices[0].message.content).get("label")
    if label not in (CORRECT, WRONG, BAD_TEACHING):
        raise ValueError(f"live judge returned an unusable label: {label!r}")
    return label


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


def _fake_openai(label_payload: str):
    """Stand-in ``openai`` module whose create() returns a fixed JSON body, so
    live_judge can run in the self-test with no network or key."""
    import types

    resp = types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=label_payload))])
    chat = types.SimpleNamespace(
        completions=types.SimpleNamespace(create=lambda **_k: resp))
    mod = types.ModuleType("openai")
    mod.OpenAI = lambda **_k: types.SimpleNamespace(chat=chat)
    return mod


def _self_test() -> None:
    import sys

    import mcat_ai  # local run
    _topic, spans = mcat_ai.load_source()
    src = mcat_ai.source_text(spans)

    # Offline = STRUCTURAL screen: no answer -> wrong; over-long -> bad-teaching;
    # a clean short card passes structure.
    assert classify({"front": "What is Km?", "back": ""}, src, [], live=False) == WRONG
    assert classify({"front": "Define enzymes", "back": "x" * 260}, src, [],
                    live=False) == BAD_TEACHING
    clean = {"front": "What is an enzyme?",
             "back": "A biological catalyst that lowers activation energy."}
    assert classify(clean, src, [], live=False) == CORRECT

    # Honesty: offline does NOT verify facts. A structurally-clean but factually
    # WRONG card passes the offline structural screen (which is exactly why the
    # eval reports offline as structural-only and factual judging needs --live).
    wrongish = {"front": "What does a noncompetitive inhibitor do to Vmax?",
                "back": "It raises Vmax."}
    assert classify(wrongish, src, [], live=False) == CORRECT

    # Live judge: the import is path-tolerant (it now actually runs), and it
    # FAILS CLOSED -- an unusable label raises so classify() falls back to the
    # structural screen instead of auto-passing an unverified card.
    saved = sys.modules.get("openai")
    saved_key = mcat_ai.api_key
    mcat_ai.api_key = lambda: "sk-test"
    try:
        sys.modules["openai"] = _fake_openai(json.dumps({"label": WRONG}))
        assert live_judge(wrongish, src) == WRONG, "live_judge did not run/return the label"
        assert classify(wrongish, src, [], live=True) == WRONG, "live factual catch failed"
        sys.modules["openai"] = _fake_openai(json.dumps({"label": "??"}))
        raised = False
        try:
            live_judge(wrongish, src)
        except Exception:
            raised = True
        assert raised, "live_judge must fail closed on an unusable label"
        assert classify(wrongish, src, [], live=True) == CORRECT, "did not fall back"
    finally:
        mcat_ai.api_key = saved_key
        if saved is not None:
            sys.modules["openai"] = saved
        else:
            sys.modules.pop("openai", None)

    print("mcat_cardcheck self-test OK: offline = structural screen only (no fake "
          "factual accuracy); live judge runs (import fixed) + fails closed on a "
          "bad response; factual judging is the live LLM's job.")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _self_test()
