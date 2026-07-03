---
title: "Study-feature ablation — pre-registration"
exam: "MCAT (472–528)"
registered: "July 3, 2026 (before any result was seen)"
---

# The study feature under test

The **encode workflow**: Prime → Connect → Build. Before drilling a topic, the
learner does a detail-free big-picture pass (Prime), writes purpose-driven
inquiry questions (Connect), and builds a labeled relationship map with a live
2–4 chunking check (Build). Cards enter only as *overflow* from Build.

Learning-science basis: generation effect + elaborative interrogation +
schema-building before retrieval (see BrainLift SPOV 2, 3).

# Primary hypothesis (stated ahead of time)

> Studying a topic with the full **Prime → Connect → Build** workflow produces
> **higher accuracy on held-out, paraphrased, exam-style questions per equal
> minute of study** than flashcards alone or plain Anki.

Primary outcome metric, fixed now: **held-out paraphrase accuracy per study
minute.** The paraphrase items come from the 7d bank (2 reworded exam-style
questions per card, never shown during study).

# The three builds (spec §8: full / ablated / plain Anki)

| Build | What it is | Isolates |
|---|---|---|
| **C — full** | Our app, encode workflow **ON** (Prime→Connect→Build + Focus ordering + flashcards) | the whole method |
| **B — ablated** | Our app, encode workflow **OFF** (flashcards + Focus/points-at-stake ordering only) | whether the encode workflow itself did the work (C vs B) |
| **A — plain Anki** | Unmodified upstream Anki, same cards | whether our app beats the obvious alternative at all (B/C vs A) |

Why all three: C-vs-B attributes any gain to the encode feature specifically,
not to better cards or more reviews; B/C-vs-A shows the app is worth using over
stock Anki.

# Fair-test controls

- **Same learner(s)**, **matched-difficulty topics** (rotated across builds to
  cancel topic effects), and an **equal study-time budget** per build.
- Same held-out paraphrase quiz for all three; quiz items never seen during study.
- Report the **point estimate and a range**, not a single number.
- **Report negative results.** "The encode workflow made no measurable
  difference here" is a valid, publishable outcome and is reported as-is.

# Falsifiability

This test can show the feature does nothing. We are not proving the idea; we are
running a fair test that could fail. Pre-registering the hypothesis and the
primary metric now is what makes a later positive result credible.

# Timing (honest)

The **harness and all three builds are built Friday.** The **result** requires
real accrued study time and runs over the weekend, then reports Sunday. Faking
this data is an automatic fail per the spec, so we do not.
