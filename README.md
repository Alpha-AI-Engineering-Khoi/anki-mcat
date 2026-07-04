# Anki for the MCAT — Speedrun (desktop engine + Qt app)

A fork of [Anki](https://github.com/ankitects/anki) built for **one graduate exam: the MCAT**
(scored **472–528**, four sections scored 118–132). It is one half of a two-app system that
shares a single **Rust engine**:

- **Desktop** (this repo) — the Qt app plus the shared `rslib` Rust engine, including the
  MCAT engine change.
- **iOS companion** — native SwiftUI, same Rust engine over a C-FFI:
  **https://github.com/kimkhoi2202/anki-mcat-ios**

Reviews and progress **sync** between the two apps through a version-matched, self-hosted
server (`anki-mcat-sync.fly.dev`).

The product bet (see the Brainlift): the MCAT is mostly reasoning, so the tool trains
**higher-order encoding + honest readiness**, not just flashcard memory — built *on top of*
Anki's engine, never reimplementing the scheduler.

## Download and run

- **Prebuilt macOS app (Apple Silicon):** the latest
  [**mcat-friday** release](https://github.com/kimkhoi2202/anki-mcat/releases/tag/mcat-friday) →
  `anki-26.05-mac-apple.dmg`. It is **Developer ID signed but not notarized**, so on first launch
  right-click `Anki.app` → **Open** → **Open** (or `xattr -dr com.apple.quarantine /Applications/Anki.app`).
- **From source (any platform):** install the toolchain per Anki's
  [dev docs](https://dev-docs.ankiweb.net) (Rust, Python 3.10+, Node), then:

  ```bash
  ./run                 # builds the engine + launches the desktop app
  ```

  AI features are **off by default**; the app still computes all three scores without them.
  To enable AI, copy `.env.example` to `.env` and set `OPENAI_API_KEY` (or export it).

## Architecture

```
proto/anki/*.proto            typed RPC contract (shared by desktop + iOS)
      │
rslib/ (Rust engine)          FSRS scheduler, SQLite collection, sync, media
      │                       + MCAT change: points-at-stake review queue
      ├── pylib (Python)  →   qt/aqt (this desktop app: MCAT layer in qt/aqt/mcat_*.py)
      └── C-FFI            →   ../anki-mcat-ios (SwiftUI companion)
```

The engine is compiled **once** and shared. The desktop MCAT features are thin Python on top
of engine RPCs; the iOS app calls the *same* Rust through a C interface. Nothing about the
MCAT layer forks the scheduler — it adds one new engine query and reads engine numbers.

## Verify the shared Rust engine change (start here)

The one required engine change is a **points-at-stake review queue**: a new backend query that
orders due cards by `topic_weight × student_weakness` so the highest-value weak-topic cards come
first. It ships to **both** apps because the engine is shared.

**Read it (all in `rslib`, the shared engine):**

| File | What |
| --- | --- |
| `proto/anki/scheduler.proto` (`rpc GetPointsAtStakeQueue`, msgs `GetPointsAtStakeQueueRequest` / `PointsAtStakeQueue`) | the new typed RPC contract |
| `rslib/src/scheduler/points_at_stake.rs` | the implementation + **8 Rust unit tests** |
| `rslib/src/scheduler/service/mod.rs` (`get_points_at_stake_queue`) | RPC handler wiring |
| `rslib/src/scheduler/mod.rs`, `rslib/src/scheduler/queue/mod.rs`, `rslib/src/backend/mod.rs` | module + queue + backend registration |

**See exactly what the fork changed vs upstream Anki (base commit `b00308e5`):**

```bash
git diff --stat b00308e5..HEAD          # every file this fork touches (55 files)
git diff b00308e5..HEAD -- rslib/ proto/anki/scheduler.proto   # just the engine change
```

**Run the tests (per PRD 7a: ≥3 Rust unit tests + 1 test that calls it from Python):**

```bash
cargo test -p anki scheduler::points_at_stake       # 8 Rust unit tests
just test-py                                         # incl. pylib/tests/test_points_at_stake.py
#   the same change, verified on iOS (in the anki-mcat-ios repo):
#   cd -P AnkiKit && swift test --filter testPointsAtStakeQueueOrdersWeakTopicFirst
```

Undo integrity + no-corruption is exercised by the crash test below. A prose note on why this
belongs in Rust (not Python) and its upstream-merge cost is in
[`docs/rust-change.md`](./docs/rust-change.md).

## The MCAT layer (desktop)

All under `qt/aqt/mcat_*.py`, wired into the menu from `qt/aqt/main.py`; every number comes from
the engine.

- **Three honest scores** (`mcat_models.py`, `mcat_readiness.py`) — Memory / Performance /
  Readiness, each a **range**; **abstains** until ≥200 graded reviews AND ≥50% topic coverage.
- **Coverage map** (`mcat_coverage.py`) over the 50-topic AAMC outline.
- **Focus Weak Topics** (`mcat_weak_topics.py`) — drives the points-at-stake engine queue above.
- **AI, traceable + checked** — grounded card generation (`mcat_websearch.py`, `mcat_aicards.py`),
  a card-check gate (`mcat_cardcheck.py`), and an eval harness (`mcat_eval.py`) with held-out
  accuracy, a keyword/vector baseline, and a leakage check. AI note: [`docs/mcat/AI-NOTE.md`](./docs/mcat/AI-NOTE.md).
- **Program stages** (`mcat_encode.py`, `mcat_recall.py`, `mcat_today.py`, `mcat_program.py`),
  **paraphrase test** (`mcat_paraphrase.py`), **ablation** (`mcat_ablation.py`), **Library** (`mcat_library.py`).

## Verify everything else (re-runnable)

```bash
just test-rust                                       # full Rust engine suite
just test-py                                         # full Python suite
make bench                                           # p50/p95/worst on a 50k-card deck (PRD 7h)
make crash-test                                      # >=20 abrupt-kill / no-corruption iters (PRD 7g)
PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_eval.py        # AI eval + leakage (7e)
PYTHONPATH=out/pylib out/pyenv/bin/python qt/aqt/mcat_paraphrase.py  # memory-vs-performance gap (7d)
```

A full, camera-ready walkthrough of every feature and command is in [`DEMO.md`](./DEMO.md).
More docs: [`docs/mcat/TESTING.md`](./docs/mcat/TESTING.md),
[`docs/mcat/ablation-preregistration.md`](./docs/mcat/ablation-preregistration.md),
[`docs/mcat/sync-7b.md`](./docs/mcat/sync-7b.md), [`docs/benchmarks.md`](./docs/benchmarks.md).

## Deployment artifacts

- **Desktop installer:** `anki-26.05-mac-apple.dmg` on the
  [mcat-friday release](https://github.com/kimkhoi2202/anki-mcat/releases/tag/mcat-friday).
  Rebuild it with `SIGN_IDENTITY="Developer ID Application: <you>" RELEASE=2 ./ninja installer`
  (Briefcase; drops the `.dmg` in `out/installer/dist/`).
- **iOS build:** built from the companion repo (simulator, or a device build with a team) — see its README.
- **Sync server:** version-matched Anki sync server on Fly.io (`anki-mcat-sync.fly.dev`); iOS
  Dockerfile + `fly.toml` live in the companion repo's `deploy/syncserver/`.

## Files this fork touches

55 files vs upstream `b00308e5` (`git diff --stat b00308e5..HEAD`), grouped:

- **Shared Rust engine change (7):** `proto/anki/scheduler.proto`, `rslib/Cargo.toml`,
  `rslib/src/scheduler/points_at_stake.rs`, `rslib/src/scheduler/mod.rs`,
  `rslib/src/scheduler/service/mod.rs`, `rslib/src/scheduler/queue/mod.rs`, `rslib/src/backend/mod.rs`
- **MCAT desktop layer:** `qt/aqt/main.py` (menu) + `qt/aqt/mcat_*.py` (17 modules) + `qt/aqt/mcat_data/` (gold set, judge labels, source texts)
- **Tests & tooling:** `pylib/tests/test_points_at_stake.py`, `tools/bench.py`, `tools/_bench_common.py`, `tools/crash_test.py`, `Makefile`, `tools/mcat_label_tool.py`, `tools/mcat-label-tool.html`
- **Docs:** `DEMO.md`, `docs/rust-change.md`, `docs/benchmarks.md`, `docs/mcat/*`
- **Config:** `.env.example`, `.gitignore`, `CONTRIBUTORS`

## License and credit

**AGPL-3.0-or-later.** This is a fork of **Anki** by Ankitects Pty Ltd and contributors
(<https://github.com/ankitects/anki>) — see [LICENSE](./LICENSE). Some upstream components are
BSD-3-Clause. All MCAT additions in this repo are likewise AGPL-3.0-or-later.

Upstream build/dev reference: <https://dev-docs.ankiweb.net>.
