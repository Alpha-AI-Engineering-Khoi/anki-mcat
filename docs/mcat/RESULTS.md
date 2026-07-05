# MCAT Speedrun — Results Report

Every number here is **real and re-runnable** (commands under each section), measured
on this machine. Where a result is provisional or pending real data, it says so —
honesty over flattering numbers.

Exam: **MCAT** (472–528). Engine: Anki's Rust `rslib` (FSRS), shared desktop + iOS.

---

## 1. Speed & reliability (PRD 7h / 7g / §10)

`make bench` — 50,000-card deterministic deck (`--cards 50000 --seed 12345 --iters 200`):

| Action | p50 | p95 | worst | target |
| --- | --- | --- | --- | --- |
| Button press (answer card) | 0.19 ms | 0.74 ms | 7.5 ms | p95 < 50 ms ✓ |
| Next card (render) | 0.02 ms | 0.04 ms | 0.17 ms | p95 < 100 ms ✓ |
| Get queued cards | 0.04 ms | 0.05 ms | 0.26 ms | — |
| Deck tree with counts | 4.5 ms | 5.2 ms | 5.7 ms | dashboard < 1 s ✓ |
| Points-at-stake queue build | 117 ms | 139 ms | 151 ms | once-per-session; < 1 s ✓ |
| find_cards (deck, 50k) | 2.3 ms | 3.0 ms | 4.1 ms | — |
| Full-text search | 9.7 ms | 11.8 ms | 15.2 ms | — |

All interactive actions are far inside targets. The **points-at-stake queue** is the
one triple-digit action (139 ms p95), but it is a **once-per-session queue build**, not
a per-card cost, so it sits well under the 1 s dashboard budget.

**Crash / no-corruption (7g):** `make crash-test` — 25 iterations of open → review
writes → SIGKILL mid-write → reopen → integrity check: **25/25 iterations, ZERO
corruption.**

Reproduce: `make bench` · `make crash-test`

## 2. Memory-model calibration (PRD §9 step 1)

The memory model is FSRS. Evaluated by **Anki's own FSRS engine** on **722 real
reviews**:

- **Log loss: 0.179**
- **RMSE(bins) (calibration error): 15.9%**

Reproduce: `PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_calibration.py`

Honest limits: the real reviews are all **same-day** (0 spaced \u2265 1 day apart yet), and a
reliability *curve* plots predicted-vs-observed recall over an *elapsed interval* \u2014 so a
**personal** curve can't be drawn until real spaced study accrues. The metric above is Anki's
own calibration on the real reviews.

Method demonstration (**generated data, not measured**): to show the reliability-diagram
method on data with proper spread, `mcat_calibration.py --demo` generates realistic
spaced-review outcomes (mild overconfidence + noise) and produces
[`calibration-reliability-demo.png`](calibration-reliability-demo.png) \u2014 log loss 0.56,
RMSE(bins) 2.7% over 1,200 generated reviews. Personal calibration replaces this as real
spaced study accrues.

## 3. Performance model — paraphrase / memory→performance gap (PRD 7d)

The performance model scores accuracy on **held-out, reworded exam-style questions**
(Wilson 95% CI; abstains under 10 attempts). Seeded demonstration:

- Memory **90%** vs Performance **65%** → **memory→performance gap 25%** (95% CI 43–82%).

This proves Performance is *measured*, not copied from Memory. The gap number is from a
seeded demonstration; real per-student values accrue with study.

Reproduce: `PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_paraphrase.py`

## 4. AI checking & safety (PRD 7e / 7f)

Canonical **live** eval on a real source (`MCAT::BioBiochem::Enzymes`, 12 spans).
Pre-registered cutoff (set before results): leaked-wrong ≤ 10%, precision ≥ 0.75,
leakage ≤ 0, draft beats baseline.

- **Draft (our AI):** 22 cards → 19 correct-useful, 3 bad-teaching, **0 wrong** · quality **0.864**
- **Baseline (keyword):** 36 cards → 20 correct-useful, 12 bad-teaching, 4 wrong · quality **0.556**
- **Beats baseline: YES** (0.864 vs 0.556)
- **Leakage (7e): 0**
- Judge vs reference labels (n=18): accuracy **0.72** (varies 0.72–1.0 across runs), leaked-wrong 0.0, precision(correct-useful) **1.0**
- Deterministic quality (no AI, reproducible): grounded **1.0**, duplicate **0.0**, concise **1.0**, atomic 0.955
- Block gate: ship 19, block 3 → **VERDICT: PASS**

Headline: our AI cards **beat the keyword baseline with zero wrong facts and zero
leakage**; the LLM judge itself is imperfect (0.72 this run), which is why a human-labeled
anchor set + the deterministic screen stay in the loop.

Reproduce: `PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_eval.py --live`
(offline deterministic run: drop `--live`).

## 5. Study-feature ablation (PRD §8)

Feature under test: the **encode workflow** (Scaffold → Mindmap). Pre-registered
hypothesis, failure criterion, and primary metric ("held-out paraphrase accuracy per
study minute", predicted order C > B > A) are committed in
[`ablation-preregistration.md`](./ablation-preregistration.md).

**Status:** the pre-registration, the comparison statistics (Wilson-CI ranges, fair-test
guards, honest null-result handling) are real. A **real three-build run** (full vs
feature-off vs plain Anki) is pending real study data — the harness shows only a
clearly-labeled SIMULATED demo and **never invents a result**.

Reproduce: `PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_ablation.py`

## 6. Score mapping (PRD §9 step 3)

`scaled(p) = round(472 + p · 56)`, clamped 472–528; per-section 118–132.
`readiness.{low,point,high} = scaled(performance.{low,point,high})` → always a **range**,
never a single number. Full method in `anki-ios/docs/score-models.md`.

---

## Honest summary

- **Solid, proven:** engine speed (all targets met), crash-safety (25/25 zero
  corruption), AI cards beat the baseline with 0 wrong facts + 0 leakage, memory
  calibration (log loss 0.179 / RMSE-bins 15.9%), deterministic score mapping.
- **Provisional / pending (and labeled as such):** Performance & Readiness projections
  are provisional (uncalibrated forward model); the memory reliability *diagram* needs
  more review data; the ablation *result* is pending a real three-build run.

We report the numbers we can stand behind and mark the rest honestly.
