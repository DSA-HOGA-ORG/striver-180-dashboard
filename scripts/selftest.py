#!/usr/bin/env python3
"""
Self-test for the dashboard generator.

Builds a synthetic member repository that mimics the team's repo layout
(runners + topic/subtopic folders + logs), populates it with a known set of
solved problems (including duplicates, variant names, commented registrations,
non-solution files), runs the generator, and asserts the exact expected count.

Usage:
    python3 scripts/selftest.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MAIN_PY = '''\
"""
Runner. KNOWN_PROBLEMS lives here.
"""

# "slug": ("topic.subtopic", "module", "method")
KNOWN_PROBLEMS = {
    "set-matrix-zeroes": ("Arrays.LinearScan", "SetMatrixZeroes", "setZeroes"),
    "next-permutation": ("Arrays.LinearScan", "NextPermutation", "nextPermutation"),
    "maximum-subarray": ("Arrays.LinearScan", "MaximumSubarray", "maxSubArray"),
    "best-time-to-buy-and-sell-stock": ("Arrays.LinearScan", "BestTimeToBuyAndSell", "maxProfit"),
    "two-sum": ("Arrays.TwoPointers", "TwoSum", "twoSum"),
    "3-sum": ("Arrays.TwoPointers", "ThreeSum", "threeSum"),
    "reverse-pairs": ("Arrays.DivideAndConquer", "ReversePairs", "reversePairs"),
    "kth-largest-element-in-an-array": ("BinarySearch.BinarySearch", "KthLargestElementInArray", "findKthLargest"),
    "kth-largest-element-in-an-unsorted-array": ("Heaps.Heap", "KthLargestUnsorted", "findKthLargest"),
    "median-of-two-sorted-arrays": ("BinarySearch.PartitionSearch", "MedianTwoSorted", "findMedianSortedArrays"),
    "allocate-minimum-number-of-pages": ("BinarySearch.SearchOnAnswer", "AllocatePages", "allocatePages"),
    "find-median-in-a-stream-of-running-integers": ("Heaps.Heap", "MedianStream", "addNum"),
    "rotten-oranges": ("Graph.BFS", "RottenOranges", "orangesRotting"),
    "set-matrix-zeros": ("Arrays.LinearScan", "SetMatrixZeroesAlt", "setZeroes"),
    "custom-extra-problem": ("Arrays.LinearScan", "ExtraThing", "solve"),
    # "count-and-say" would be registered here later
}

TEST_CASES = {
}
'''

MAIN_CPP = '''\
// C++ runner
#include <functional>
#include <map>
#include <string>

static const std::map<std::string, std::function<void()>> PROBLEMS = {
    {"merge-intervals", run_merge_intervals},
    // {"count-and-say", run_count_and_say},      // still unsolved, ignore me
    {"trapping-rainwater", run_trapping_rainwater},
};
'''

DAILY_LOG = '''\
# Daily log

## Day 01 — Wednesday, 23 Sep 2026

**Topic:** Arrays
**Problems solved:** 2

### Problem: Pascal's Triangle
- **Link:** [LeetCode](https://leetcode.com/problems/pascals-triangle/)
- **Status:** Solved

### Problem: Sort Colors
- **Link:** [LeetCode](https://leetcode.com/problems/sort-colors/)
- **Status:** Solved
'''

FILES = {
    "Arrays/LinearScan/SetMatrixZeroes.py": "class Solution:\n    def setZeroes(self, m): pass\n",
    "Arrays/LinearScan/MaximumSubarray.py": "class Solution:\n    def maxSubArray(self, n): pass\n",
    "Arrays/LinearScan/PascalsTriangle.py": "class Solution:\n    def generate(self, n): pass\n",
    "Arrays/TwoPointers/TwoSum.py": "class Solution:\n    def twoSum(self, n, t): pass\n",
    "Arrays/TwoPointers/SortColors.py": "class Solution:\n    def sortColors(self, n): pass\n",
    "Arrays/TwoPointers/NextPermutation.cpp": "namespace next_permutation { class Solution {}; }",
    "tests/test_dummy.py": "def test_x(): pass\n",
    "main.py": MAIN_PY,
    "main.cpp": MAIN_CPP,
    "README.md": "# repo\n",
    "logs/daily_log.md": DAILY_LOG,
    ".gitignore": "*.pyc\n",
    "Arrays/__init__.py": "",
    "Arrays/LinearScan/__init__.py": "",
}

# problems that must be counted for the synthetic member (ids from data/problems.json)
EXPECTED_PIDS = {
    1,   # set-matrix-zeroes (+ alias "set-matrix-zeros")
    2,   # pascal's triangle        (daily log + solution file)
    3,   # next-permutation         (main.py + cpp file)
    4,   # maximum-subarray/Kadane  (main.py + file)
    5,   # sort colors              (daily log + file)
    6,   # best-time-to-buy-and-sell-stock (main.py)
    8,   # merge-intervals          (main.cpp)
    18,  # reverse-pairs            (main.py)
    19,  # two-sum                  (main.py + file)
    39,  # 3-sum                    (main.py)
    40,  # trapping-rainwater       (main.cpp)
    65,  # median-of-two-sorted-arrays (main.py)
    67,  # allocate-minimum-number-of-pages (main.py)
    70,  # kth-largest-element-in-an-array (main.py)
    88,  # rotten oranges           (main.py)
    147,  # find-median-in-a-stream-of-running-integers (main.py)
    150,  # kth-largest-element-in-an-unsorted-array (main.py)
}

if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp(prefix="dash-selftest-"))
    try:
        repo = tmp / "SDESheetChallenge"
        repo.mkdir(parents=True)
        for rel, content in FILES.items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

        out = tmp / "out"
        out.mkdir()
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_dashboard.py"),
             "--repo-root", str(tmp), "--data", str(ROOT / "data"),
             "--out", str(out)],
            check=True,
        )
        dash = json.loads((out / "generated" / "dashboard.json").read_text())
        actual = set(dash["by_member"]["shaunak"]["solved_ids"])

        missing = EXPECTED_PIDS - actual
        extra = actual - EXPECTED_PIDS
        if missing or extra:
            print("MISMATCH")
            print("  expected-but-missing:", sorted(missing))
            print("  actual-but-not-expected:", sorted(extra))
            print("  actual:", sorted(actual))
            sys.exit(1)
        assert len(actual) == len(EXPECTED_PIDS)
        # custom-extra-problem must be reported as unmapped
        un = dash["by_member"]["shaunak"]["unmapped"]
        assert "custom-extra-problem" in un, un
        print(f"SELFTEST OK — {len(actual)} unique problems detected, "
              f"duplicates and comments ignored, unmapped reported.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)