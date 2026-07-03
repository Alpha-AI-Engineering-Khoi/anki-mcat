---
title: "AI Note — what we built, why, and what we skipped"
exam: "MCAT (472–528)"
date: "July 3, 2026"
---

# What the AI does (and only this)

The AI does the **lower-order** work and nothing else. Two components, both in
`qt/aqt/`:

1. **Draft** (`mcat_ai.py`) — reads a bundled real MCAT source, extracts terms,
   and drafts candidate flashcards. Every card is linked to the **exact source
   span** it came from (`source_span: "S#"`) and tagged to one of the 50 MCAT
   topics. Live path calls OpenAI (`gpt-4o-mini`, key from `.env`); an
   offline deterministic extractor runs when AI is switched off.
2. **Card Check** (`mcat_cardcheck.py`) — screens each drafted card with
   deterministic rules first (no answer, over-long, multi-question, overloaded,
   list-dump, term-not-in-source = hallucination proxy, contradiction of a
   known source fact), then a judge classifies the survivors as
   **correct-useful / wrong / correct-but-bad-teaching**. Failures are blocked.

# Why this split

Our BrainLift's core claim: AI should remove the grunt work of *making* study
material, never do the *thinking* that produces learning. So the AI drafts and
screens candidate cards; the human accepts, edits, or rejects them, and the
human alone builds the relationship map (the Prime → Connect → Build workflow).
The AI never answers the learner's inquiry questions and never auto-builds the
map.

# What we deliberately skipped

- **No AI tutor / chatbot.** It would invite passive Q&A, the opposite of the
  generation effect we are trying to force.
- **No AI-written relationship maps.** That is the encoding the learner must do.
- **No LLM in the scores.** Memory / Performance / Readiness are statistical
  (FSRS + held-out accuracy), not model opinions. An LLM readiness number would
  be exactly the "guess in a nice font" the spec forbids.
- **No AI during review.** The review loop is pure engine.

# Traceability, eval, baseline, safety (challenges 6, 7e, 7f)

- **Named source (6):** every drafted card carries `source_span`; Draft is
  forbidden from inventing facts outside the numbered source.
- **Held-out eval (7f):** `mcat_eval.py` runs before any card is shown. It
  classifies Draft output, reports correct-useful / wrong / bad-teaching counts,
  and applies a cutoff **pre-registered before looking**
  (`MAX_LEAKED_WRONG_RATE=0.10`, `MIN_JUDGE_PRECISION=0.75`, `MAX_LEAKAGE=0`).
- **Beats a baseline:** same eval pits Draft against a keyword/cloze generator;
  Draft wins on correct-useful rate (offline: 1.00 vs 0.22).
- **Leakage (7e):** the eval scans the AI's source spans against the gold/test
  items and proves zero near-copies (Jaccard ≥ 0.85 threshold).
- **Judge never trusted blind:** the judge is calibrated against a human-labeled
  set; the safety metric is the **leaked-wrong rate** (cards passed as
  correct-useful that a human marked wrong) — currently 0.0 on 18 labels.
- **AI-off:** Draft, Card Check, and the eval all run deterministically with no
  key and no network. Every score still computes with AI off.

# Honest limits (as of Friday)

- The human gold set is **24 items**; the spec asks for 50. It is seeded and
  real; finishing it is human labeling, which we will not fake.
- The live OpenAI path is wired and tested structurally; the headline eval
  numbers above are the **offline** deterministic run so they are re-runnable by
  a grader with no key.
