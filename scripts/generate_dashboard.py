#!/usr/bin/env python3
"""
Striver 180 — Team Dashboard generator.

Reads the three member solution repositories and computes per-member progress
against the canonical Striver SDE Sheet (data/problems.json).

Signals read from each repo (strongest first):
  main.py                      KNOWN_PROBLEMS dict keys (the team's own registry)
  main.cpp                     PROBLEMS map slugs
  Topic/Subtopic/*.{py,cpp,...}  solution files (module names -> canonical match)
  logs/daily_log.md            "### Problem: <name>" + LeetCode links

Every matched problem is reduced to its unique canonical id, so duplicate or
multi-language solutions never over-count. Non-solution files (runners, logs,
README, __init__ files, tests, config) are ignored.

Writes:
  README.md                    human dashboard
  generated/dashboard.json     machine-readable full snapshot
  generated/history.jsonl      append-only history of snapshots

Usage:
  python3 generate_dashboard.py --repo-root ./repos
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
GEN = ROOT / "generated"

IGNORED_DIRS = {
    ".git", ".github", "logs", "__pycache__", ".venv", "venv", "node_modules",
    "generated", "scripts", "data", ".trash", ".obsidian", "dist", "build",
}
IGNORED_ROOT_FILES = {
    "main.py", "main.cpp", "log.py", "readme.md", "readme", "a.out", "main",
    ".gitignore", "license", "makefile",
}
IGNORED_FILENAMES = {"__init__.py", "__init__.pyc"}
SOLUTION_EXT = {".py", ".cpp", ".c", ".cc", ".java", ".kt", ".js", ".go", ".rs"}

BAR_WIDTH = 20


# ---------------------------------------------------------------- text utils

def slugify(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("’", "'")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def camel_to_kebab(s: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "-", s)
    return slugify(s)


def normalize_tokens(s: str):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def word_cover(a: set, b: set) -> float:
    """Fraction of the smaller token set present in the larger."""
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    if not small:
        return 0.0
    return len(small & large) / len(small)


# ------------------------------------------------------------ canonical index

class SheetIndex:
    def __init__(self, problems):
        self.problems = problems
        self.by_id = {p["id"]: p for p in problems}
        self.exact = {}          # slug -> pid
        self.name_tokens = {}    # pid -> token set (name + slug)
        self._build()

    def _build(self):
        day_base = self._day_bases()
        for p in self.problems:
            pid = p["id"]
            keys = [p["slug"], slugify(p["name"])] + list(p.get("aliases", []))
            # kebab of a camel-case module class name form of the name
            keys.append(camel_to_kebab(p["name"]))
            for k in keys:
                k = slugify(k)
                if k and k not in self.exact:
                    self.exact[k] = pid
            self.name_tokens[pid] = normalize_tokens(
                p["name"] + " " + p["slug"] + " " + " ".join(p.get("aliases", []))
            )
        # high-value shorthand -> problem NAME, resolved against the current sheet
        shorthand = {
            "kadane": "Kadane's Algorithm", "kadanes": "Kadane's Algorithm",
            "two-sum": "Two Sum", "2-sum": "Two Sum",
            "four-sum": "4 Sum", "4-sum": "4 Sum",
            "three-sum": "3 Sum", "3-sum": "3 Sum",
            "lis": "Longest Increasing Subsequence",
            "longest-increasing-subsequence": "Longest Increasing Subsequence",
            "lcs": "Longest Common Subsequence",
            "longest-common-subsequence": "Longest Common Subsequence",
            "mcm": "Matrix chain multiplication",
            "matrix-chain-multiplication": "Matrix chain multiplication",
            "lru": "LRU Cache", "lru-cache": "LRU Cache",
            "lfu": "LFU Cache", "lfu-cache": "LFU Cache",
            "n-queen": "N Queen", "nqueens": "N Queen",
            "topological-sort": "Topological sort or Kahn's algorithm",
            "coinchange": "Coin change II", "coin-change": "Coin change II",
            "power-set": "Power Set", "powerset": "Power Set",
            "subsets": "Power Set",
        }
        for k, name in shorthand.items():
            k = slugify(k)
            if not k or k in self.exact:
                continue
            pid = self._by_name(name)
            if pid is not None:
                self.exact[k] = pid

    def _by_name(self, name):
        """Resolve a problem NAME to its pid via slug, exact token or fuzzy match."""
        k = slugify(name)
        if k and k in self.exact:
            return self.exact[k]
        nt = normalize_tokens(name)
        best, best_conf = None, 0.0
        for pid, toks in self.name_tokens.items():
            conf = max(jaccard(nt, toks), word_cover(nt, toks))
            if conf > best_conf:
                best, best_conf = pid, conf
        return best if best_conf >= 0.6 else None

    def _day_bases(self):
        bases = {}
        start = 1
        prev_day = None
        for p in self.problems:
            if p["day"] not in bases:
                bases[p["day"]] = start
            start += 1
        return bases

    def match(self, raw: str):
        """Return (pid, confidence, exact). Exact returns conf 1.0."""
        k = slugify(raw)
        if not k:
            return None
        if k in self.exact:
            return (self.exact[k], 1.0, True)
        cand_tokens = normalize_tokens(raw)
        best, best_conf = None, 0.0
        for pid, toks in self.name_tokens.items():
            j = jaccard(cand_tokens, toks)
            w = word_cover(cand_tokens, toks)
            conf = max(j, w)
            if conf > best_conf:
                best, best_conf = pid, conf
        if best is not None and best_conf >= 0.6:
            return (best, best_conf, False)
        return None


# ------------------------------------------------------------ repo inspection

def parse_known_problems_main_py(text: str) -> list[str]:
    # drop whole-line comments (hash-only) before parsing
    clean = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    m = re.search(r"KNOWN_PROBLEMS\s*=\s*(\{)", clean)
    if not m:
        return []
    start = m.end(1) - 1
    depth = 0
    i = start
    slugs = []
    while i < len(clean):
        c = clean[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        elif c == '"':
            # read string literal; capture only dict KEYS (followed by ':')
            j = i + 1
            buf = []
            while j < len(clean) and clean[j] != '"':
                if clean[j] == "\\":
                    buf.append(clean[j + 1] if j + 1 < len(clean) else "")
                    j += 2
                else:
                    buf.append(clean[j])
                    j += 1
            k = j + 1
            while k < len(clean) and clean[k] in " \t":
                k += 1
            if depth == 1 and k < len(clean) and clean[k] == ":":
                slugs.append("".join(buf).strip())
            i = j
        i += 1
    return [s for s in slugs if s]


def parse_problem_slugs_main_cpp(text: str) -> list[str]:
    strip = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    strip = re.sub(r"//[^\n]*", "", strip)
    return [s for s in re.findall(r'"([a-z0-9-]+)"\s*,\s*run_', strip)]


def parse_daily_log(text: str) -> list[dict]:
    entries = []
    # split into per-problem blocks so each carries its own status line
    blocks = re.split(r"\n(?=###\s*Problem:)", text)
    for block in blocks:
        m = re.match(r"###\s*Problem:\s*(.+?)\s*$", block, re.M)
        if not m:
            continue
        name = m.group(1).strip()
        status_m = re.search(r"\*\*Status:\*\*\s*([^\n]*)", block)
        st = status_m.group(1) if status_m else ""
        solved = ("Solved" in st and "Unsolved" not in st
                  and "Need Review" not in st)
        if not solved:
            continue  # Unsolved / Need Review is not "done"
        entries.append({"name": name, "link": _lc_slug_from_line(name)})
        for lm in re.finditer(r"leetcode\.com/problems/([a-zA-Z0-9-]+)/?[\"'\s)]", block):
            entries.append({"name": "", "link": lm.group(1)})
    return entries


def _lc_slug_from_line(name: str) -> str:
    return slugify(name) or ""


def solution_files(repo_root: Path) -> list[Path]:
    found = []
    for path in sorted(repo_root.rglob("*")):
        if path.is_dir():
            continue
        parts = path.relative_to(repo_root).parts
        if any(p in IGNORED_DIRS for p in parts[:-1]):
            continue
        if path.suffix.lower() not in SOLUTION_EXT:
            continue
        if path.name in IGNORED_ROOT_FILES or path.name.lower() in IGNORED_FILENAMES:
            continue
        if len(parts) == 1 and path.name in IGNORED_ROOT_FILES:
            continue
        # must sit inside at least one topic folder
        if len(parts) < 2:
            continue
        found.append(path)
    return found


def extract_file_slugs(path: Path) -> list[str]:
    stem = path.stem
    cands = [slugify(stem), camel_to_kebab(stem)]
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        text = ""
    m = re.search(r"class\s+(\w+)", text or "")
    if m:
        cands.append(slugify(m.group(1)))
        cands.append(camel_to_kebab(m.group(1)))
    # C++ namespaces / Python Solution class inside the file
    for m in re.finditer(r"namespace\s+([a-z0-9_]+)", text or ""):
        cands.append(slugify(m.group(1)))
    # strip trailing digits/words like 'solution'
    out = []
    for c in cands:
        c = re.sub(r"(^|-)(solution|sol)\b", "", c)
        out.append(c.strip("-"))
    return [c for c in out if c]


def is_stub(path: Path) -> bool:
    """A clean (non-stub) file counts as a real solution.

    Empty bodies, `pass`-only Python methods and bare class/namespace
    declarations are treated as stubs so that merely pushing a header
    does not mark a problem as done.
    """
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        text = ""
    if not text.strip():
        return True
    # strip comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)   # block comments (C-style)
    text = re.sub(r"//[^\n]*", "", text)                 # line comments (C-style)
    text = re.sub(r"#[^\n]*", "", text)                  # python comments / cpp directives
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    if path.suffix.lower() in (".py",):
        # a python solution must contain a real statement outside of
        # pass/.../raise NotImplementedError placeholders
        real = [
            ln for ln in lines
            if ln
            and not ln.startswith(("@", "def ", "class "))
            and ln not in ("pass", "...")
            and not ln.startswith(('"""', "'''"))
            and not re.match(r"raise\s+NotImplementedError\b", ln)
        ]
        return not real

    # C-family: stub iff every function-like body is empty.
    # Find `) {` (method signature) then balance braces; any non-empty body == code.
    pos = 0
    n = len(text)
    while True:
        m = re.search(r"\)\s*\{", text[pos:])
        if not m:
            break
        start = pos + m.end() - 1
        depth = 1
        j = start + 1
        while j < n and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[start + 1:j - 1] if depth == 0 else text[start + 1:]
        if body.strip():
            return False  # at least one implemented method
        pos = j
    return True


# ------------------------------------------------------------- solved section

def solve_member(repo_root: Path, index: SheetIndex) -> dict:
    solved: dict[int, dict] = {}
    matched_slugs: set[str] = set()
    unmapped: list[str] = []
    recent: list[dict] = []

    main_py = repo_root / "main.py"
    main_cpp = repo_root / "main.cpp"
    daily_log = repo_root / "logs" / "daily_log.md"

    def record(pid, source, raw):
        solved.setdefault(pid, {"pid": pid, "sources": set(), "raws": set()})
        solved[pid]["sources"].add(source)
        solved[pid]["raws"].add(raw)

    signals = []

    if main_py.exists():
        for s in parse_known_problems_main_py(main_py.read_text(errors="ignore")):
            signals.append(("main_py", s, 1.0, True))
    if main_cpp.exists():
        for s in parse_problem_slugs_main_cpp(main_cpp.read_text(errors="ignore")):
            signals.append(("main_cpp", s, 1.0, True))
    if daily_log.exists():
        for e in parse_daily_log(daily_log.read_text(errors="ignore")):
            sig = "daily_log"
            if e["link"]:
                signals.append((sig, e["link"], 1.0, True))
            if e["name"]:
                signals.append((sig, e["name"], 1.0, True))
    for f in solution_files(repo_root):
        for s in extract_file_slugs(f):
            signals.append(("solution_file", s, None, None))

    # every pid that is already matched to a stubbed file AND has no other
    # real source must be dropped — pushing only a header is not "done"
    stub_pids: set[int] = set()
    real_file_pids: set[int] = set()
    for f in solution_files(repo_root):
        if is_stub(f):
            for s in extract_file_slugs(f):
                res = index.match(s)
                if res is None:
                    continue
                stub_pids.add(res[0])
        else:
            for s in extract_file_slugs(f):
                res = index.match(s)
                if res is None:
                    continue
                real_file_pids.add(res[0])

    prev_sources = {}
    for sig, raw, conf, exact in signals:
        res = index.match(raw)
        if res is None:
            if sig in ("main_py", "main_cpp"):
                unmapped.append(raw)
            continue
        pid, got_conf, got_exact = res
        if sig == "solution_file" and not got_exact and got_conf < 0.75:
            continue  # fuzzy file matches need strong confidence
        if sig in ("main_py", "main_cpp") and pid in stub_pids and pid not in real_file_pids:
            # registered slug backed only by a stubbed file — not a real solve
            continue
        record(pid, sig, raw)
        prev_sources.setdefault(pid, sig)

    # solution_file signals that only came from stub files are not evidence
    for pid in [p for p in solved if p in stub_pids and p not in real_file_pids]:
        del solved[pid]

    for pid, info in solved.items():
        info["sources"] = sorted(info["sources"])
        info["raws"] = sorted(info["raws"])
        info["problem"] = index.by_id[pid]
        if info["sources"]:
            info["primary"] = "main_py" if "main_py" in info["sources"] else \
                              "main_cpp" if "main_cpp" in info["sources"] else \
                              "daily_log" if "daily_log" in info["sources"] else "files"

    result = {
        "solved": {str(pid): {"pid": pid,
                              "problem": index.by_id[pid]["name"],
                              "topic": index.by_id[pid]["topic"],
                              "day": index.by_id[pid]["day"],
                              "difficulty": index.by_id[pid]["difficulty"],
                              "sources": info["sources"],
                              "matched": sorted(info["raws"])}
                  for pid, info in solved.items()},
        "solved_ids": sorted(int(p) for p in solved),
        "unmapped": sorted(set(unmapped)),
    }
    return result


# ------------------------------------------------------------------ dashboard

def pct(n, d) -> float:
    return (n / d * 100.0) if d else 0.0


def bar(filled_frac: float) -> str:
    filled = int(round(filled_frac * BAR_WIDTH))
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def fmt(n: float) -> str:
    return f"{n:.1f}"


def read_meta(cfg: dict, members_path: Path):
    members = json.loads(members_path.read_text()).get("members", [])
    total = cfg.get("target_total") or _count_problems()
    return members, total


def _count_problems() -> int:
    probs = json.loads((DATA / "problems.json").read_text())
    return len(probs)


def generate_readme(dash: dict, cfg: dict, members: list[dict], generated_at: str) -> str:
    total = dash["total"]
    team_total = total * len(members)
    team_solved = sum(m["solved"] for m in dash["members"])
    tc = fmt(pct(team_solved, team_total)) if team_total else "0.0"
    label = cfg.get("advertised_sheet_label", "Striver 180")

    rows = []
    for i, m in enumerate(
            sorted(dash["members"], key=lambda x: (-x["solved"], x["display"])), 1):
        rem = total - m["solved"]
        p = pct(m["solved"], total)
        rows.append(
            f"| {i} | {m['display']} | {m['solved']}/{total} | {rem} | {fmt(p)}% | {bar(p/100)} |"
        )
    leaderboard = "\n".join(rows) or "_No members configured._"

    topics = [t for t in dash["topic_order"]]
    trows = []
    for t in topics:
        cells = [dash["by_member"][mb["id"]]["topics"].get(t, 0) for mb in dash["members"]]
        trows.append(f"| {t} | " + " | ".join(str(c) for c in cells) + " |")
    topic_table = "\n".join(trows)

    recent_lines = []
    for r in dash["recent_activity"][: cfg.get("recent_activity_limit", 8)]:
        recent_lines.append(f"- **{r['member']}** solved *{r['problem']}* ({r['day']})")
    recent_block = "\n".join(recent_lines) or "_Nothing yet — the first commit to any member repo will show up here automatically._"

    repo_lines = "\n".join(
        f"- **{mb['display']}** — [{mb['repo']}]({mb['repo_url']})"
        for mb in members
    )

    unmapped_lines = []
    for m in dash["members"]:
        if m.get("unmapped"):
            unmapped_lines.append(f"- {m['display']}: {', '.join(m['unmapped'])}")
    unmapped_block = "\n".join(unmapped_lines) or "_None._"

    return f"""# 🚀 {label} — Team Dashboard

Progress of all tracked members through the Striver SDE Sheet, updated
automatically from each member's repository every time new solutions land.

> **Live tracker:** the full per-problem board is
> [generated/board.md](generated/board.md).
> The same data is mirrored into the org's "Striver 180 Tracker" project.

## Overall Progress

**TEAM:** {team_solved} / {team_total} completed-signals ({tc}%)

{bar(pct(team_solved, team_total) / 100.0)}

> Each member individually attempts all {total} problems on the sheet.

## Leaderboard

| Rank | Member | Solved | Remaining | Progress | Bar |
|------|--------|--------|-----------|----------|-----|
{leaderboard}

## Topic Progress

| Topic | {' | '.join(mb['display'] for mb in dash['members'])} |
|{'|'.join(['------'] * (len(dash['members']) + 1))}|
{topic_table}

> Topics come from `data/problems.json` (the canonical Striver SDE Sheet).

## Full board

Open the **[per-problem progress board](generated/board.md)** for the complete
status of all {total} problems (Day · Topic · Difficulty · who solved it).

## Recent Activity

{recent_block}

## Repositories

{repo_lines}

## How it updates

- The GitHub Action in this repo runs hourly + on every push to this repo + manually.
- It clones the three member repos (public), reads `main.py` / `main.cpp`
  registrations, solution files and `logs/daily_log.md`, maps everything to the
  canonical {total}-problem sheet, deduplicates, and regenerates this page.
- No manual updates needed.

## Canonical sheet

- Sheet: {label} — {total} distinct problems tracked in
  `data/problems.json` (synced from the live takeUforward sheet).
- Unmatched slugs (please flag these to adjust the alias map):\n{unmapped_block}

---

_Generated at {generated_at} (UTC) by `scripts/generate_dashboard.py`._
"""


def generate_board(dash: dict, problems: list, members: list) -> str:
    """Full per-problem markdown table — the reliable 'board' view."""
    solved = {
        m["id"]: set(dash["by_member"][m["id"]]["solved_ids"])
        for m in dash["members"]
    }
    name_by_id = {p["id"]: p for p in problems}
    order = [p for p in problems if p["id"] in name_by_id]
    order.sort(key=lambda p: p["id"])
    day_index = {}   # day -> counter for the day's sequential number
    day_slots = defaultdict(int)

    rows = []
    team_done = 0
    for p in order:
        day_slots[p["day"]] += 1
        flags = [p["id"] in solved[m["id"]] for m in members]
        team = any(flags)
        team_done += int(team)
        flags_s = ["✅" if f else "—" for f in flags]
        rows.append(
            f"| {p['day']:>2} | {day_slots[p['day']]:>2} | {p['name']} | {p['topic']} | "
            f"{p['difficulty'] or '—'} | {'✅' if team else '—'} | "
            f"{' | '.join(flags_s)} |"
        )

    header = (
        f"| Day | # | Problem | Topic | Difficulty | Team | "
        f"{' | '.join(m['display'] for m in members)} |"
    )
    sep = "|---|--|---|----|------|----|" + "---|" * len(members)
    legend = " — ".join(f"**{m['display']}**" for m in members)
    return (
        f"# Progress Board — full per-problem status\n\n"
        f"Members: {legend}. ✅ = solved by that member on their own repo.\n\n"
        f"**Team:** {team_done} / {len(order)} problems solved by at least one member.\n\n"
        f"{header}\n{sep}\n" + "\n".join(rows) + "\n"
    )


def build_dashboard(members, cfg, repos_root: Path, index: SheetIndex, generated_at: str) -> dict:
    total = cfg.get("target_total") or len(index.problems)

    dash_members = []
    topic_counter_all = Counter()
    recent = []

    for mb in members:
        mrepo = repos_root / mb["repo"]
        if not mrepo.exists():
            dash_members.append({
                "id": mb["id"], "display": mb["display"], "repo": mb["repo"],
                "solved": 0, "solved_ids": [], "topics": {}, "unmapped": [],
                "note": "repo not cloned",
            })
            continue
        res = solve_member(mrepo, index)
        pid_list = res["solved_ids"]
        counts = Counter(index.by_id[p]["topic"] for p in pid_list)
        topic_counter_all.update(counts)
        for pid in pid_list:
            p = index.by_id[pid]
            recent.append({
                "member": mb["display"],
                "pid": pid,
                "problem": p["name"],
                "day": p["day"],
                "topic": p["topic"],
                "difficulty": p["difficulty"],
                "when": generated_at,
            })
        dash_members.append({
            "id": mb["id"],
            "display": mb["display"],
            "repo": mb["repo"],
            "repo_url": mb.get("repo_url", ""),
            "github": mb.get("github"),
            "solved": len(pid_list),
            "solved_ids": pid_list,
            "topics": dict(counts),
            "unmapped": res["unmapped"],
            "note": None,
        })

    recent.sort(key=lambda r: (r.get("when") or generated_at), reverse=True)

    dash = {
        "generated_at": generated_at,
        "org": cfg["org"],
        "sheet_total": total,
        "total": total,
        "members": dash_members,
        "recent_activity": recent[:50],
        "topic_order": _topic_order(index, topic_counter_all),
    }
    # convenience: solved sets stored in solved_ids above
    dash["by_member"] = {m["id"]: m for m in dash_members}
    return dash


def _topic_order(index, counts) -> list[str]:
    """Canonical topic order = first-appearance in the sheet."""
    order = []
    seen = set()
    for p in index.problems:
        t = p["topic"]
        if t not in seen:
            seen.add(t)
            order.append(t)
    return order


# ------------------------------------------------------------------ main flow

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=str(ROOT / "repos"),
                    help="directory containing the member repos (default: ./repos)")
    ap.add_argument("--data", default=str(DATA), help="data directory")
    ap.add_argument("--out", default=str(ROOT), help="output root (README + generated/)")
    args = ap.parse_args()

    data_dir = Path(args.data)
    out_root = Path(args.out)
    repos_root = Path(args.repo_root)
    gen_dir = out_root / "generated"

    cfg = json.loads((data_dir / "config.json").read_text())
    members, _ = read_meta(cfg, data_dir / "members.json")
    problems = json.loads((data_dir / "problems.json").read_text())
    index = SheetIndex(problems)

    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    missing = [mb["repo"] for mb in members if not (repos_root / mb["repo"]).exists()]
    if missing:
        print(f"[warn] repos not found under {repos_root}: {missing}", file=sys.stderr)

    dash = build_dashboard(members, cfg, repos_root, index, generated_at)

    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "dashboard.json").write_text(
        json.dumps(dash, indent=2) + "\n")

    # append history
    hist = {
        "generated_at": generated_at,
        "team_solved": sum(m["solved"] for m in dash["members"]),
        "total": dash["total"],
        "members": {m["id"]: {"solved": m["solved"]} for m in dash["members"]},
    }
    with (gen_dir / "history.jsonl").open("a") as fh:
        fh.write(json.dumps(hist) + "\n")

    readme = generate_readme(dash, cfg, members, generated_at)
    (out_root / "README.md").write_text(readme)

    board = generate_board(dash, problems, members)
    (gen_dir / "board.md").write_text(board)

    print("=== DASHBOARD ===")
    for m in dash["members"]:
        print(f"{m['display']:>10}: {m['solved']}/{dash['total']} solved "
              f"({m.get('unmapped') or 'all matched'})")
    print(f"TEAM: {sum(m['solved'] for m in dash['members'])} / "
          f"{dash['total'] * len(members)}")
    print(f"Wrote {out_root / 'README.md'}, {gen_dir / 'board.md'}, {gen_dir / 'dashboard.json'}, history.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())