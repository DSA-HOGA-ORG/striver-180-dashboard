# 🚀 Striver 180 — Team Dashboard

Progress of all tracked members through the Striver SDE Sheet, updated
automatically from each member's repository every time new solutions land.

> **Live tracker:** the full per-problem board is
> [generated/board.md](generated/board.md).
> The same data is mirrored into the org's "Striver 180 Tracker" project.

## Overall Progress

**TEAM:** 20 / 895 completed-signals (2.2%)

░░░░░░░░░░░░░░░░░░░░

> Each member individually attempts all 179 problems on the sheet.

## Leaderboard

| Rank | Member | Solved | Remaining | Progress | Bar |
|------|--------|--------|-----------|----------|-----|
| 1 | Shaunak | 11/179 | 168 | 6.1% | █░░░░░░░░░░░░░░░░░░░ |
| 2 | Smruti Ranjan | 8/179 | 171 | 4.5% | █░░░░░░░░░░░░░░░░░░░ |
| 3 | Pratik | 1/179 | 178 | 0.6% | ░░░░░░░░░░░░░░░░░░░░ |
| 4 | Dibya | 0/179 | 179 | 0.0% | ░░░░░░░░░░░░░░░░░░░░ |
| 5 | Saksham | 0/179 | 179 | 0.0% | ░░░░░░░░░░░░░░░░░░░░ |

## Topic Progress

| Topic | Shaunak | Dibya | Saksham | Pratik | Smruti Ranjan |
|------|------|------|------|------|------|
| Arrays | 11 | 0 | 0 | 1 | 8 |
| Hashing | 0 | 0 | 0 | 0 | 0 |
| Binary Search | 0 | 0 | 0 | 0 | 0 |
| Sliding Window and Two Pointers | 0 | 0 | 0 | 0 | 0 |
| Recursion and Backtracking | 0 | 0 | 0 | 0 | 0 |
| Linked List | 0 | 0 | 0 | 0 | 0 |
| Stack and Queues | 0 | 0 | 0 | 0 | 0 |
| Greedy Algorithms | 0 | 0 | 0 | 0 | 0 |
| Heaps | 0 | 0 | 0 | 0 | 0 |
| Binary Trees | 0 | 0 | 0 | 0 | 0 |
| Binary Search Trees | 0 | 0 | 0 | 0 | 0 |
| Graphs | 0 | 0 | 0 | 0 | 0 |
| Dynamic Programming | 0 | 0 | 0 | 0 | 0 |
| Tries | 0 | 0 | 0 | 0 | 0 |
| Strings | 0 | 0 | 0 | 0 | 0 |
| Bit Manipulation | 0 | 0 | 0 | 0 | 0 |
| Mathematics | 0 | 0 | 0 | 0 | 0 |

> Topics come from `data/problems.json` (the canonical Striver SDE Sheet).

## Full board

Open the **[per-problem progress board](generated/board.md)** for the complete
status of all 179 problems (Day · Topic · Difficulty · who solved it).

## Recent Activity

- **Shaunak** solved *Majority Element-I* (1)
- **Shaunak** solved *Kadane's Algorithm* (1)
- **Shaunak** solved *Majority Element-II* (1)
- **Shaunak** solved *Maximum Product Subarray in an Array* (1)
- **Shaunak** solved *Sort an array of 0's 1's and 2's* (1)
- **Shaunak** solved *3 Sum* (1)
- **Shaunak** solved *Next Permutation* (1)
- **Shaunak** solved *4 Sum* (1)

## Repositories

- **Shaunak** — [SDESheetChallenge](https://github.com/DSA-HOGA-ORG/SDESheetChallenge)
- **Dibya** — [SDESheetChallengeDIBYA](https://github.com/DSA-HOGA-ORG/SDESheetChallengeDIBYA)
- **Saksham** — [SDESheetChallengeSaksham](https://github.com/DSA-HOGA-ORG/SDESheetChallengeSaksham)
- **Pratik** — [SDESheetChallengePratik](https://github.com/DSA-HOGA-ORG/SDESheetChallengePratik)
- **Smruti Ranjan** — [SDESheetChallengeSMRUTI](https://github.com/DSA-HOGA-ORG/SDESheetChallengeSMRUTI)

## How it updates

- The GitHub Action in this repo runs hourly + on every push to this repo + manually.
- It clones the three member repos (public), reads `main.py` / `main.cpp`
  registrations, solution files and `logs/daily_log.md`, maps everything to the
  canonical 179-problem sheet, deduplicates, and regenerates this page.
- No manual updates needed.

## Canonical sheet

- Sheet: Striver 180 — 179 distinct problems tracked in
  `data/problems.json` (synced from the live takeUforward sheet).
- Unmatched slugs (please flag these to adjust the alias map):
_None._

---

_Generated at 2026-09-26T11:12:13Z (UTC) by `scripts/generate_dashboard.py`._
