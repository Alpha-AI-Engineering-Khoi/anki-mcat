---
title: "AI Note — what we built, why, and what we skipped"
exam: "MCAT (472–528)"
date: "July 3, 2026"
---

# What the AI does (lower-order work only)

The AI only does **lower-order** work — surfacing and drafting candidate material
that a human then judges, edits, or rejects. It never does the thinking that
produces learning. Every AI touchpoint, all in `qt/aqt/`:

- **Draft** (`mcat_ai.py`) — from a bundled MCAT source, extract terms and draft
  candidate flashcards, each linked to the source span it came from.
- **Encode helpers** (`mcat_ai.py`) — scope/skim points (Prime), candidate
  keywords (Connect), and candidate concepts (Build): suggestions the learner
  curates. The AI never answers the inquiry questions or builds the map.
- **Paraphrase questions** (`mcat_ai.py`) — reword a card into exam-style
  questions for the Performance test. The graded answer key is always the card's
  own back, never the model's free text.
- **Card Check judge** (`mcat_cardcheck.py`) — an LLM judges a drafted card
  against the source.

Each has a deterministic **AI-off** fallback, so nothing hard-depends on the
model. Live calls use OpenAI (`gpt-4o-mini` by default; per-task overridable via
`MCAT_OPENAI_MODEL_<TASK>`, e.g. a stronger model for the judge).

# Why this split

The BrainLift's core claim: AI should remove the grunt work of *making* study
material, never do the *thinking* that produces learning. So the AI drafts and
screens candidates; the human accepts/edits/rejects them and alone builds the
relationship map (Prime → Connect → Build). The AI never answers inquiry
questions and never auto-builds the map.

# What we deliberately skipped

- **No AI tutor / chatbot** — it invites passive Q&A, the opposite of the
  generation effect.
- **No AI-written relationship maps** — that encoding is the learner's job.
- **No LLM in the scores** — Memory / Performance / Readiness are statistical
  (FSRS + measured accuracy), not model opinions. An LLM readiness number is
  exactly the "guess in a nice font" the spec forbids.
- **No AI during review** — the review loop is pure engine.

# Traceability, eval, baseline, safety (challenges 6, 7e, 7f)

- **Named source (6):** every drafted card carries a `source_span`, and
  provenance is *gated*, not assumed. A card whose span isn't a real span in the
  loaded source is never silently tagged: the add path blocks or requires
  explicit confirmation, the offline drafter returns an empty span instead of
  manufacturing one, and the live drafter drops cards it cannot ground.
- **Real, cited sources:** the grounding corpus is **10 real source documents**
  (one per topic, `qt/aqt/mcat_data/source_*.md`), each paraphrased from
  **Wikipedia (CC BY-SA 4.0)** and, where needed, **LibreTexts (CC BY-NC-SA
  4.0)**, with a `sources:` header listing every title, URL, and license.
  `load_source(topic_tag=...)` serves each topic its own cited source. OpenStax
  was deliberately avoided (its pages carry a no-AI-ingestion notice).
- **Card Check (7f):** deterministic **structural** rules first (no-answer,
  over-long, multi-question, overloaded, list-dump, off-topic). **Factual**
  judging is the **live LLM judge only** — it grounds the answer against the
  card's cited span and **fails closed** (an unusable response is never
  auto-passed). Offline there is deliberately **no factual judge**: keyword regex
  cannot verify truth (an earlier attempt was circular — fit to its own labels —
  and leaked ~45% of genuinely wrong cards, so we deleted it). Offline runs the
  structural screen only, and the eval says so.
- **Held-out eval:** `mcat_eval.py` is a **re-runnable pre-ship harness**
  (`python mcat_eval.py --live`) — it is **not** auto-invoked inside the app. It
  classifies Draft output, reports accuracy + wrong-answer (leaked-wrong) rate
  against a curated reference set, and applies a cutoff **pre-registered before
  looking** (`MAX_LEAKED_WRONG_RATE=0.10`, `MIN_JUDGE_PRECISION=0.75`,
  `MAX_LEAKAGE=0`), blocking failures (VERDICT FAIL). Latest live run
  (Jul 3, 2026): **VERDICT PASS** — judge **accuracy 0.833, leaked-wrong 0.0,
  precision 1.0** (n=18); Draft 23/23 correct-useful, 0 wrong; leakage 0.
- **Beats a simpler method:** the same eval pits Draft against a **fair**
  keyword-cloze baseline (short stem, key-term blank — not a length-rigged
  strawman). Latest live run: **Draft quality 1.0 vs baseline 0.611** — a
  genuine win, not a format artifact.
- **Leakage (7e):** the eval scans the source against the gold items by whole-span
  Jaccard **or** sentence-level containment (so an embedded/reworded near-copy is
  caught, not just a verbatim block); the real source reports **0**.
- **AI-off:** every score still computes with AI off. A real kill-switch
  (`MCAT_OFFLINE` / `MCAT_AI_DISABLED` / an explicitly-empty `OPENAI_API_KEY`)
  forces AI off, and the `.env` key search is scoped to the repo (it no longer
  harvests a key from a parent directory).

# Safety / robustness

- **Content sanitized:** source spans and card fields strip HTML tags
  (`<script>`, `on*=` handlers) and invisible / RTL-override characters, so
  untrusted content can't inject markup into a rendered card. Scientific `<`/`>`
  inequalities are preserved.
- **Injection-hardened live prompts:** instructions live in a `system` message;
  the untrusted source (and, for the judge, the card) are wrapped in nonce-fenced
  data blocks the model is told to treat strictly as data. This is a structural
  defense; a live jailbreak test is the final confirmation.
- **Broken-AI resilient:** errors / timeouts / 429 / non-JSON degrade cleanly to
  the offline path; malformed-but-successful output is validated (empty/garbage →
  offline; the judge fails closed); live calls carry a timeout so a stalled
  network can't hang the UI.

# Traceability audit — live web-search path (Jul 3, 2026)

The held-out eval above grades the **fixed-doc** Draft path (deterministic,
re-runnable). The **live web-search generator** (`mcat_websearch.py`: OpenAI
`web_search`, forced, domain-filtered to Wikipedia + LibreTexts) was separately
audited end-to-end: 10 independent checkers generated **400 cards across all 50
MCAT topics** and **re-fetched every cited page themselves** (not the app's own
verifier) to confirm each quote is really on the page. Results:

- **0 hallucinated quotes** — every checkable card's quote was genuinely present
  on the exact page it cited (~100% across all 50 subjects).
- **The "verified" flag is trustworthy: 369/370** cards the app marked verified
  were truly on-page (1 false positive — a stitched LaTeX *formula* snippet). All
  other flag errors run the safe direction (~6.5% conservative false-negatives
  that ship *without* a highlight, never a wrong highlight).
- **Sources resolve: 599/600** cited/Prime URLs return 200, ~59/60 on-topic (1
  dead link, 1 off-topic journal stub, 1 non-English page — data nits to clean).

Honesty caveats: this is a **live** audit, so it is deliberately *not*
re-runnable-identical (web pages change) — which is exactly why the **graded**
eval stays on the fixed docs. The single false positive is a known
formula-matcher bug (being fixed); it never fabricates a source, only mis-anchors
a highlight.

# Honest limits (as of Friday)

- **Factual** eval numbers require `--live` (a key). Offline the eval reports only
  what it can stand behind (structural screen + leakage + baseline) and
  explicitly defers the factual verdict to `--live`.
- Card Check is a pre-ship harness + a judge, **not** an automatic in-app gate.
  The app's one card-add path (encode overflow) is deterministic
  source-extraction with human review + the provenance gate above.
- Injection **resistance** and judge **grounding quality** are hardened
  structurally but need a live model run to fully confirm.
