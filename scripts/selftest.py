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
    "majority-element-ii": ("Arrays.LinearScan", "MajorityElementII", "majorityElement"),
    "next-permutation": ("Arrays.LinearScan", "NextPermutation", "nextPermutation"),
    "maximum-subarray": ("Arrays.LinearScan", "Kadane", "maxSubArray"),
    "two-sum": ("Arrays.TwoPointers", "TwoSum", "twoSum"),
    "3-sum": ("Arrays.TwoPointers", "ThreeSum", "threeSum"),
    "merge-sorted-array": ("Arrays.TwoPointers", "MergeSortedArray", "merge"),
    "reverse-pairs": ("Arrays.DivideAndConquer", "ReversePairs", "reversePairs"),
    "count-inversions": ("Arrays.DivideAndConquer", "CountInversion", "inversionCount"),
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

### Problem: Find The Duplicate Number
- **Link:** [LeetCode](https://leetcode.com/problems/find-the-duplicate-number/)
- **Status:** ☑ Need Review
'''

FILES = {
    "Arrays/LinearScan/MajorityElement.py": "class Solution:\n    def majorityElement(self, n):\n        return sorted(n)[len(n) // 2]\n",
    "Arrays/LinearScan/MajorityElementII.py": "class Solution:\n    def majorityElement(self, nums: list[int]) -> list[int]:\n        raise NotImplementedError\n",
    "Arrays/LinearScan/Kadane.py": "class Solution:\n    def maxSubArray(self, n):\n        cur = best = n[0]\n        for x in n[1:]:\n            cur = max(x, cur + x)\n            best = max(best, cur)\n        return best\n",
    "Arrays/LinearScan/SortColors.py": "class Solution:\n    def sortColors(self, n):\n        n.sort()\n",
    "Arrays/LinearScan/TwoSum.py": "class Solution:\n    def twoSum(self, n, t):\n        s = {}\n        for i, x in enumerate(n):\n            if t - x in s:\n                return [s[t - x], i]\n            s[x] = i\n",
    "Arrays/LinearScan/ThreeSum.cpp": "namespace three_sum {\nclass Solution {\npublic:\n    vector<vector<int>> threeSum(vector<int>& nums) {\n        sort(nums.begin(), nums.end());\n        return {{}};\n    }\n};\n}\n",
    "Arrays/LinearScan/NextPermutation.cpp": "namespace next_permutation {\nclass Solution {\npublic:\n    void nextPermutation(vector<int>& nums) {\n        nums.push_back(0);\n    }\n};\n}\n",
    "Arrays/LinearScan/MergeSortedArray.py": "class Solution:\n    def merge(self, n, m, k, b):\n        n[k:] = sorted(n[:k] + b[:m])\n",
    "Arrays/LinearScan/LCS.py": "class Solution:\n    def longestCommonSubsequence(self, a, b):\n        dp = [0] * (len(b) + 1)\n        for c in a:\n            prev = dp[:]\n            for j, d in enumerate(b, 1):\n                dp[j] = prev[j - 1] + 1 if c == d else max(dp[j - 1], prev[j])\n        return dp[-1]\n",
    "Arrays/DivideAndConquer/ReversePairs.cpp": "namespace reverse_pairs {\nclass Solution {\npublic:\n    int reversePairs(vector<int>& nums) {\n        return nums.size();\n    }\n};\n}\n",
    # stub: registered slug + header-only file must NOT count as done
    "Arrays/DivideAndConquer/CountInversion.cpp": "namespace count_inversions {\nclass Solution {\npublic:\n    long long inversionCount(vector<int>& arr) {\n    }\n};\n}\n",
    "Arrays/Hashing/LongestConsecutive.py": "class Solution:\n    def longestConsecutive(self, n):\n        return len(set(n))\n",
    "BinarySearch/SearchAnswer/BookAllocation.cpp": "namespace book_allocation {\nclass Solution {\npublic:\n    int minimumPages(vector<int>& b, int m) {\n        return b.size();\n    }\n};\n}\n",
    "Heaps/Heap/KthLargest.cpp": "namespace kth_largest {\nclass Solution {\npublic:\n    int findKthLargest(vector<int>& nums, int k) {\n        return nums[k];\n    }\n};\n}\n",
    "Heaps/Heap/MedianFinder.py": "class MedianFinder:\n    def __init__(self):\n        self.a = []\n    def addNum(self, n):\n        self.a.append(n)\n    def findMedian(self):\n        return 0\n",
    "Design/LRUCache.cpp": "namespace lru_cache {\nclass LRUCache {\npublic:\n    LRUCache(int cap) {}\n    int get(int key) { return 0; }\n    void put(int key, int value) {}\n};\n}\n",
    "Graph/BFS/RottenOranges.cpp": "namespace rotten_oranges {\nclass Solution {\npublic:\n    int orangesRotting(vector<vector<int>>& g) {\n        return g.size();\n    }\n};\n}\n",
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