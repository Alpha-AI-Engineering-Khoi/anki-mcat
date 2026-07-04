# MCAT app — end-to-end test guide (submission readiness)

Four layers, fastest/strongest proof first. If you only have 15 minutes, do
Layers 1–2 (they're the graded AI evidence) and spot-check 3 panels in Layer 3.

All commands are run from the repo root:
`/Users/khoilam/Documents/Crossover/coding-projects/anki.nosync/anki-desktop/main`

---

## 0. Running the app

Two modes — same app, AI on vs off:

```bash
# LIVE AI (Draft / Paraphrase / eval call OpenAI). Key read from a file
# OUTSIDE iCloud; never printed, never committed.
cd anki.nosync/anki-desktop/main
OPENAI_API_KEY="$(cat ~/.mcat_openai_key)" ./run

# AI OFF (deterministic offline fallbacks everywhere)
cd anki.nosync/anki-desktop/main
./run
```

- The app is a normal Anki build. All new features are under the **Tools → MCAT** menu.
- Only the **Enzymes** topic (`MCAT::BioBiochem::Enzymes`) ships a bundled source
  document, so AI Draft / scope / keywords are richest there. Other topics fall
  back to topic-name scaffolds (by design).
- Sync errors in the terminal (`sync status check failed: network error`) are
  Anki's AnkiWeb check with no login — harmless, unrelated to MCAT/AI.

---

## 1. Layer 1 — automated self-tests (~2 min, offline, no key)

Proves the pure logic + the whole AI pipeline offline (scoring math, program
state, draft/sanitize/paraphrase, the judge, the eval, calendar, ablation math,
recall cap policy).

```bash
cd anki.nosync/anki-desktop/main/qt/aqt
for m in mcat_models mcat_program mcat_ai mcat_cardcheck mcat_eval \
         mcat_paraphrase mcat_today mcat_ablation mcat_recall; do
  echo "=== $m ==="; ../../out/pyenv/bin/python "$m.py" | tail -2
done
```

**PASS =** every module prints its `... self-test: OK` (or eval `VERDICT: PASS`)
line and exits 0. Any traceback = fail.

---

## 2. Layer 2 — the graded AI proof (the headline deliverable)

The evaluation harness scores the AI Draft against a human-labeled gold set with
a pre-registered cutoff. Run it **live** (real OpenAI) and **offline** (honest
structural-only screen):

```bash
# LIVE — real factual judgment
OPENAI_API_KEY="$(cat ~/.mcat_openai_key)" out/pyenv/bin/python qt/aqt/mcat_eval.py --live

# OFFLINE — structural screen only (honestly labeled as such)
out/pyenv/bin/python qt/aqt/mcat_eval.py
```

**What to verify in the live run:**

- `VERDICT: PASS`
- `Beats baseline: YES` (Draft quality > the fair baseline's)
- `Judge vs human labels: accuracy` high, `leaked-wrong rate <= 10%`,
  `precision(correct-useful) >= 0.75`
- `Leakage (7e) ... : 0`

Last verified live run: Draft quality **0.957** (22/23 correct-useful, 0 wrong)
vs baseline 0.778; judge accuracy **1.0**, leaked-wrong **0.0**, precision
**1.0**, leakage **0** → **PASS**.

**Honesty note (say this in the submission):** offline mode does *structural*
screening only (it never claims to judge facts); live mode is the real factual
judge. The two verdicts are labeled differently on purpose.

---

## 3. Layer 3 — hand-test every panel (Tools → MCAT)

### First, give the scoring panels some data
A fresh profile has no cards, so Readiness/Coverage/Weak-Topics will *honestly*
abstain ("not enough data") — that's the honesty gate working, not a bug. To
exercise scoring:

- **Easiest:** **Tools → MCAT → Library** → import a curated deck (needs
  internet). Adds `MCAT::`-tagged cards with scheduling on.
- **Or:** add cards via **Encode → Build → Send to cards…**.
- **Memory needs review history:** actually *study/answer* some cards first, or
  Memory will (correctly) stay unscored.

### The 10 entries

1. **Today…** — the front door. Expect a header `Day N of 28 · <phase>`,
   today's topic, five stage rows (Prime / Connect / Build / Study now / Check
   readiness) each with a time budget and a ✓/— marker, a one-line reflection, a
   readiness snapshot, and **Set exam date…**. Click *Set exam date* → enter
   `YYYY-MM-DD` → the day/horizon updates. Each stage button opens its feature.
   ⚠ crash or blank topic.

2. **Readiness…** — three separate scores (Memory / Performance / Readiness) as
   *ranges*, or an honest abstain with a "best next thing". After you've reviewed
   cards **and** done ≥10 paraphrase answers, Performance flips to "measured
   (paraphrase test)" and you see the memory→performance gap. ⚠ a bare single
   number with no range, or a score shown on almost no data.

3. **Coverage…** — % of the 50 AAMC topics with ≥1 card, per section/topic, with
   an abstain banner below threshold. ⚠ >100%, crash.

4. **Focus Weak Topics…** — due MCAT review topics ranked weakest-first
   (weakness = 1 − FSRS recall). Needs due, `MCAT::`-tagged review cards; else it
   shows the "no due cards yet" note. ⚠ wrong ordering, crash.

5. **Recall: interleaved Focus session…** — builds/rebuilds one filtered deck
   `MCAT Focus (interleaved)` from due MCAT cards in random order and opens it.
   ⚠ duplicate filtered decks piling up, crash.

6. **Recall: apply phase-aware cap** — sets the current deck's new-cards/day cap
   (5 during Encode/Consolidate weeks, lifted in the Recall week). Confirm the
   tooltip names the cap + phase, and Deck options → new cards/day reflects it.
   Fully reversible.

7. **Encode (Prime · Connect · Build)…** — the core encode workflow **and the
   live-AI surface**. Pick **BioBiochem · Enzymes** for the richest source.
   - **Prime:** scope/skim bullets (AI live; offline = source lead clauses), 4
     checkboxes + a hypotheses box; *Mark primed* enables only when all boxes are
     checked and a hypothesis is typed.
   - **Connect:** 4 editable inquiry prompts seeded from AI keywords — you edit
     and *Save* (the AI never answers them).
   - **Build:** outline tree; **Draft (AI)** adds candidate concepts (live
     OpenAI on the Enzymes source); add links + relationship labels; the 2–4
     linter shows non-blocking warnings; **Send to cards…** drafts an overflow
     detail into an add-note dialog tagged `MCAT::BioBiochem::Enzymes` +
     `mcat::src::S#`.
   - **AI-honesty checks here (important):**
     - Pick a topic *other than Enzymes* → **Send to cards is disabled** (no
       bundled source → can't trace provenance). Expected.
     - In *Send to cards*, use a detail that doesn't match the source → it warns
       *"no verified source span … add anyway?"* (the provenance gate).
     - Put `<script>alert(1)</script>` in a card front → after *Add card* the
       markup is stripped (sanitize), but a scientific `ΔG < 0` survives.

8. **Paraphrase check…** — the reworded-question transfer test on the **current
   deck's** cards (needs ≥1 basic card). Per card: 2 reworded exam-style stems
   (AI live; offline = deterministic reword), *Show answer* → *Got it / Missed
   it* → *Next card*. After ≥10 graded answers it computes measured Performance
   (Wilson CI) and Readiness shows the memory→performance gap. ⚠ the answer key
   isn't the card's own back; not exactly 2 stems.

9. **Study-feature ablation…** — a read-only pre-registration panel: the
   hypothesis, the 3 builds (A plain Anki / B ablated / C full), and "not enough
   data yet" until real weekend study accrues. It must **never** show invented
   numbers. (CLI `out/pyenv/bin/python qt/aqt/mcat_ablation.py` prints a
   clearly-labeled SIMULATED demo just to prove the ranking math.)

10. **Library…** — browse + one-tap import curated decks from Supabase (needs
    internet). Read-only against the backend; import brings cards in with
    scheduling so the scoring panels have data.

---

## 4. Layer 4 — AI honesty & robustness spot-checks

```bash
# Kill-switch: forces AI OFF even with a valid key present.
MCAT_OFFLINE=1 OPENAI_API_KEY="$(cat ~/.mcat_openai_key)" \
  out/pyenv/bin/python qt/aqt/mcat_eval.py            # runs offline, no network

# Broken-key resilience: no crash, no hang (20s timeout), degrades to offline.
OPENAI_API_KEY=sk-bogus out/pyenv/bin/python qt/aqt/mcat_eval.py --live
```

- **AI-off in the app:** relaunch with plain `./run` (no key) — every panel still
  works via offline fallbacks (Encode still drafts, Paraphrase still rewords).
- **Prompt injection:** the untrusted source is nonce-fenced as *data* in a
  separate user message; the `mcat_ai` self-test asserts the role split + nonce
  fencing, and the live eval exercises the grounded prompts.

---

## 5. Submission checklist

- [ ] Layer 1 self-tests all green
- [ ] Layer 2 live eval `VERDICT: PASS` (paste/screenshot the numbers)
- [ ] Every Tools → MCAT panel opens and behaves (Layer 3)
- [ ] AI-off + broken-key degrade cleanly (Layer 4)
- [ ] Key hygiene: `git -C anki.nosync/anki-desktop/main status` clean;
      `git -C anki.nosync/anki-desktop/main grep -l sk-proj` → nothing; key lives
      only in `~/.mcat_openai_key`
- [ ] Docs present: `docs/mcat/AI-NOTE.md`, `ablation-preregistration.md`, `sync-7b.md`
- [ ] (Deferred) iOS build + two-way sync recording
- [ ] **Rotate the OpenAI key after submitting**
