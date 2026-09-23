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
    "majority-element": ("Arrays.LinearScan", "MajorityElementI", "majorityElement"),
    "next-permutation": ("Arrays.LinearScan", "NextPermutation", "nextPermutation"),
    "maximum-subarray": ("Arrays.LinearScan", "Kadane", "maxSubArray"),
    "two-sum": ("Arrays.TwoPointers", "TwoSum", "twoSum"),
    "3-sum": ("Arrays.TwoPointers", "ThreeSum", "threeSum"),
    "merge-sorted-array": ("Arrays.TwoPointers", "MergeSortedArray", "merge"),
    "reverse-pairs": ("Arrays.DivideAndConquer", "ReversePairs", "reversePairs"),
    "kth-largest-element-in-an-array": ("Heaps.Heap", "KthLargestElementInArray", "findKthLargest"),
    "kth-largest-element-in-an-unsorted-array": ("Heaps.Heap", "KthLargestUnsorted", "findKthLargest"),
    "median-of-two-sorted-arrays": ("BinarySearch.BinarySearch", "MedianTwoSorted", "findMedianSortedArrays"),
    "find-median-from-a-data-stream": ("Heaps.Heap", "MedianStream", "addNum"),
    "rotten-oranges": ("Graph.BFS", "RottenOranges", "orangesRotting"),
    "custom-extra-problem": ("Arrays.LinearScan", "ExtraThing", "solve"),
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
    {"trapping-rainwater", run_trapping_rainwater},
    // {"next-permutation", run_next_permutation},  // still unsolved, ignore me
};
'''

DAILY_LOG = '''\
# Daily log

## Day 01 — Wednesday, 23 Sep 2026

**Topic:** Arrays
**Problems solved:** 2

### Problem: Sort Colors
- **Link:** [LeetCode](https://leetcode.com/problems/sort-colors/)
- **Status:** Solved

### Problem: Longest Common Subsequence
- **Link:** [LeetCode](https://leetcode.com/problems/longest-common-subsequence/)
- **Status:** Solved
'''

FILES = {
    "Arrays/LinearScan/MajorityElement.py": "class Solution:\n    def majorityElement(self, n): pass\n",
    "Arrays/LinearScan/Kadane.py": "class Solution:\n    def maxSubArray(self, n): pass\n",
    "Arrays/LinearScan/SortColors.py": "class Solution:\n    def sortColors(self, n): pass\n",
    "Arrays/LinearScan/TwoSum.py": "class Solution:\n    def twoSum(self, n, t): pass\n",
    "Arrays/LinearScan/ThreeSum.cpp": "namespace three_sum { class Solution {}; }",
    "Arrays/LinearScan/NextPermutation.cpp": "namespace next_permutation { class Solution {}; }",
    "Arrays/LinearScan/MergeSortedArray.py": "class Solution:\n    def merge(self, n, m): pass\n",
    "Arrays/LinearScan/LCS.py": "class Solution:\n    def longestCommonSubsequence(self, a, b): pass\n",
    "Arrays/DivideAndConquer/ReversePairs.cpp": "namespace reverse_pairs { class Solution {}; }",
    "Arrays/Hashing/LongestConsecutive.py": "class Solution:\n    def longestConsecutive(self, n): pass\n",
    "BinarySearch/SearchAnswer/BookAllocation.cpp": "namespace book_allocation { class Solution {}; }",
    "Heaps/Heap/KthLargest.cpp": "namespace kth_largest { class Solution {}; }",
    "Heaps/Heap/MedianFinder.py": "class MedianFinder:\n    def addNum(self, n): pass\n",
    "Design/LRUCache.cpp": "namespace lru_cache { class LRUCache {}; }",
    "Graph/BFS/RottenOranges.cpp": "namespace rotten_oranges { class Solution {}; }",
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
    1,   # majority-element        (file + main.py)
    2,   # maximum-subarray/Kadane (main.py + file)
    5,   # sort colors             (daily log + file)
    6,   # 3 sum                   (main.py + file)
    7,   # next-permutation        (main.py + cpp file)
    9,   # merge-sorted-array      (main.py + file)
    10,  # trapping-rainwater      (main.cpp)
    12,  # reverse-pairs           (main.py + file)
    13,  # two-sum                 (main.py + file)
    14,  # longest-consecutive-sequence (file)
    27,  # book allocation         (file, fuzzy name)
    30,  # median-of-two-sorted-arrays (main.py)
    78,  # lru-cache               (file)
    91,  # kth-largest-element-in-an-array (main.py)
    92,  # find-median-from-data-stream (main.py)
    120, # rotten oranges          (main.py + file)
    157, # longest common subsequence (daily log + file)
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