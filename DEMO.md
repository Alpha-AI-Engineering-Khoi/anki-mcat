# Demo Runbook — Anki MCAT Speedrun

One exam (MCAT), two apps (desktop + iOS) on one shared Rust engine, a real engine
change, three honest scores, and re-runnable proof. This is the filming script for
the 3–5 minute demo, mapped to the PRD's required contents (review session, Rust
change, phone→desktop sync, the three scores with ranges, AI features, test results).

Every command below was verified to run. The offline scripts need no network; the
three AI commands read the key from `~/.mcat_openai_key`.

## Paths

Desktop commands run from the desktop fork:

```bash
cd /Users/khoilam/Documents/Crossover/coding-projects/anki.nosync/anki-desktop/main
```

iOS commands run from the iOS app:

```bash
cd /Users/khoilam/Documents/Crossover/coding-projects/anki.nosync/anki-ios
```

## 0. Setup (already running — establishing shot)

Desktop app (`./run`), the iPhone 17 simulator running the app, and the Fly.io sync
server are up. Just show both windows side by side. Relaunch only if needed:

```bash
# Desktop (only if it is not already running — do not double-run, it locks the collection)
OPENAI_API_KEY="$(cat ~/.mcat_openai_key)" ./run

# Phone app (relaunch on the booted simulator)
xcrun simctl launch 13C9FD93-440E-4B13-BEF7-0427F90CCF93 com.khoilam.ankispeedrun
```

Sync target is the same for both apps: `https://anki-mcat-sync.fly.dev/`
(desktop: Preferences → Syncing; iOS: Settings → Custom sync server). Both must be
logged into the same account for cross-device sync.

## 1. Review session (both apps share one engine)

In the app: open a deck and grade a few cards (4-button grading + interval previews)
on desktop and on the phone.

## 2. The Rust engine change in action (PRD 7a)

In the app: tap **Focus Weak Topics** — this calls the `points_at_stake` Rust queue
(highest-value weak-topic cards first). Then show the tests behind it:

```bash
# 3 Rust unit tests for the change
cargo test -p anki scheduler::points_at_stake

# the test that calls the Rust change from Python
PYTHONPATH=out/pylib out/pyenv/bin/python -m pytest pylib/tests/test_points_at_stake.py -v
```

Same engine, verified on iOS (from `anki-ios`):

```bash
cd -P AnkiKit && swift test --filter testPointsAtStakeQueueOrdersWeakTopicFirst
```

## 3. Two-way sync: phone <-> desktop (Fly.io) (PRD 7b)

- On the phone: review 1–2 cards, then tap **Sync**.
- On the desktop: tap **Sync** and show the same reviews land.
- Reverse it: review on desktop, Sync, then Sync the phone.

## 4. Three scores with ranges + the give-up rule (PRD 4 / 9)

In the app: tap **MCAT Readiness** — show Memory / Performance / Readiness each as a
range, plus the abstain state before ≥200 reviews and ≥50% coverage.

CLI proof (also proves scores compute with AI off — no key needed):

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_models.py
```

## 5. Coverage map (PRD 7c)

In the app: tap **MCAT Coverage** — the 50-topic AAMC outline, per-section rollup,
percent covered; abstains below the line.

## 6. AI features, every output traced to a source (PRD 3 / 7f)

```bash
# AI drafts cards grounded to a consulted source (traceable-source requirement)
OPENAI_API_KEY="$(cat ~/.mcat_openai_key)" out/pyenv/bin/python qt/aqt/mcat_websearch.py --cards "Amino acids & proteins"

# AI card check (structural screen; add the key for the live factual judge)
PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_cardcheck.py
```

## 7. Test results (the graded proof)

```bash
# AI eval: accuracy + wrong-answer rate on held-out, baseline, and the leakage check (7e)
PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_eval.py
#   add --live for the factual LLM judge:
OPENAI_API_KEY="$(cat ~/.mcat_openai_key)" PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_eval.py --live

# Paraphrase test (7d): memory vs performance gap (proves performance is measured, not copied)
PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_paraphrase.py

# Study-feature ablation (section 8): full vs feature-off vs plain Anki (C>B>A + honest null-result banner)
PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_ablation.py

# One-command benchmark (7h): p50/p95/worst on a 50k deck (~1–2 min; warm it up before filming)
make bench
#   quick version for filming:
make bench BENCH_CARDS=5000 BENCH_ITERS=50

# Crash / no-corruption test (7g): >=20 abrupt-kill iterations
make crash-test
```

## 8. Full test suites (optional — show green)

```bash
just test-rust      # all Rust engine tests
just test-py        # all Python tests (incl. the points-at-stake bridge)
cd -P AnkiKit && swift test   # 88 iOS engine-backed tests (from anki-ios)
```

## Notes

- The three AI commands (`mcat_websearch`, `mcat_eval --live`, live `mcat_cardcheck`)
  load the key from `~/.mcat_openai_key`. Everything else is offline and deterministic.
- `make bench` on the full 50k deck generates a cached deck on first run; run it once
  before filming so it is warm, or use the smaller knobs.
- Sync only shows across devices if the phone and desktop are the same account on
  `anki-mcat-sync.fly.dev`. Do one test sync both ways before recording.
