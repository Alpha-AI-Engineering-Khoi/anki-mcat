---
title: "Two-way sync (7b) — procedure and conflict rule"
exam: "MCAT (472–528)"
date: "July 3, 2026"
---

# Approach

We use **Anki's existing sync** (allowed by spec §3), pointed at a self-hosted
`syncserver` so nothing depends on AnkiWeb. Both the desktop app and the iOS
companion talk to the same server through the shared Rust backend, so the sync
protocol, USN bookkeeping, and merge logic are the real thing, not a reimplementation.

# The 7b procedure

1. Sign both apps into the same sync account and do a baseline sync (equal USN).
2. Go offline on both.
3. **Phone:** review 10 cards. **Desktop:** review 10 *different* cards.
4. Reconnect and sync both.
5. **Assert:** all 20 reviews are present on both devices, none lost, none
   double-counted; scheduling state for all 20 cards reflects the review.

Then the conflict case:

6. Offline again, review the **same** card on both devices (e.g. Again on the
   phone, Good on the desktop).
7. Sync. **Assert:** the documented winner below is the state that survives, and
   both raw review-log entries are still present.

# Why reviews never double-count

Each review is a **revlog** row keyed by a unique millisecond-epoch `id`.
Revlog is **append-only**, so merging two devices is a set union on `id`: the 10
phone rows and 10 desktop rows have disjoint ids and all 20 land exactly once.
A review is never mutated, so it cannot be counted twice.

# The conflict rule (same card, both devices, offline)

Card scheduling state (`due`, `ivl`, `reps`, `lapses`, `factor`) is a single
mutable record per card. When both devices change it offline:

- **Winner: last write by higher card `mod` timestamp.** The later review's
  resulting card state overwrites the earlier one. This is Anki's native
  object-level last-writer-wins.
- **History is preserved:** both revlog entries survive (append-only, above), so
  no study history is lost — only the *forward schedule* follows the later review.
- **Schema divergence fallback:** if the collection schema changed on one side
  (`scm`), Anki requires a one-directional **full sync** (one side uploads, the
  other downloads wholesale). We avoid this in the test by not changing schema
  mid-run.

# Proof artifact

Live verification is a Friday demo recording: a card graded on the phone
appearing on the desktop after sync, plus the same-card conflict resolving to
the higher-`mod` winner with both revlog rows intact. The rule above is what we
assert the recording shows.
