# MCAT Speedrun — Model Descriptions

Three separate models answer three different questions. **None is a blend of the
others** (mixing them is the easiest way to fail this project). Exam scale: **MCAT
472–528**. Pure logic lives in `qt/aqt/mcat_models.py` (+ `mcat_paraphrase.py`) and is
mirrored on iOS. Every score obeys the give-up rule below and is shown as a range.

## The give-up rule (applies to every score)

> **No score until ≥ 200 graded reviews AND ≥ 50% topic coverage.**
> (`mcat_models.GIVE_UP_RULE`)

Below the line the app **abstains** — it shows *no* number and instead surfaces the
single best next thing to study. "A good system knows when it does not know."

---

## 1. Memory model — *"can the student recall this fact right now?"*

- **Model:** FSRS (Anki's own engine) — predicted retrievability per card.
- **Score:** the mean predicted retrievability across studied cards, reported as a
  **range** (95% CI from the per-card spread), via `memory_score()`.
- **Confidence** (`memory_confidence`): `low` < 25 cards · `moderate` < 80 · `high` ≥ 80.
- **Calibration (held-out — PRD §9 step 1):** evaluated by Anki's own FSRS engine on
  **722 real reviews** → **log loss 0.179**, **RMSE(bins) 15.9%**.
  Reproduce: `PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_calibration.py`.
  A reliability *curve* needs reviews spaced across days; this collection's history is
  same-day, so the personal curve accrues with real spaced study. `mcat_calibration.py
  --demo` renders the calibration method on **generated** spaced data (labeled as such):
  `calibration-reliability-demo.png`.

## 2. Performance model — *"can the student answer a NEW, exam-style question?"*

- **Model:** measured **paraphrase accuracy**. The learner answers reworded, exam-style
  questions that test the same idea in new words, and self-grades. Performance **is** that
  measurement of transfer — not a discount of Memory (`performance_score` uses the
  measured value when present).
- **Score:** proportion correct with a **Wilson 95% CI** (`paraphrase_accuracy`),
  **abstaining below 10 answers** (`MIN_PARAPHRASE_ATTEMPTS`).
- **The bridge (PRD 7d):** we report the **memory → performance gap** — recall minus
  measured transfer (~25 points on the demo set). A gap near zero would mean Performance
  is just copying Memory; a real gap proves the bridge was built.
- **Fallback:** with no measured questions yet, a clearly-provisional coverage-weighted
  blend (Memory × transfer factor + guess baseline) so a score still computes with AI off.

## 3. Readiness model — *"what score today, and how sure?"*

- **Model:** maps the Performance proportion onto the **472–528** scale
  (`readiness_projection` → `_scaled_score`).
- **Output (never a bare number — the honesty rule):** point estimate **+ range +
  confidence + % of exam covered + last-updated + main reasons + the give-up rule.**
  Example: *Projected 508 · likely 503–512 · confidence low (42% coverage).*
- **30-day projection (`project_readiness` / `projection_confidence`):** anchored on a
  measured diagnostic; expected gain scales with program adherence toward a ceiling with
  diminishing returns; the **range widens** with the horizon; **confidence is never
  "high"** (the growth rate isn't yet validated against real outcomes) and it **abstains**
  below 10 diagnostic answers. The plan can be aggressive; the *number* stays honest.

---

## Honesty posture

Real user data drives every real score, always with a range + confidence + abstain.
Any **generated** data used to demonstrate a method (the calibration reliability chart,
the A/B/C ablation pilot) is clearly labeled "demonstration / generated," never presented
as a measured result. See `RESULTS.md` for the numbers and reproduce commands.
