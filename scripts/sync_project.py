#!/usr/bin/env python3
"""
Sync dashboard progress into a GitHub Projects v2 board (org-level).

This is OPTIONAL. The dashboard repository (README.md + generated/dashboard.json)
is the source of truth; this script mirrors a summary into GitHub Project #2 so
the team gets an interactive tracker.

The script is fully idempotent and does NOT depend on the project's `items`
connection (which some deployments return empty even though items exist):

  * ensures the project's custom fields exist
  * keeps a LOCAL registry of problem title -> item id in data/synced_items.json,
    creating one draft item per canonical problem only when the id is unknown
    (warm-starts from the `items` connection when it works, best-effort)
  * updates each item's Topic / Difficulty / Status / per-member / Last-Updated
    using a small thread pool so ~1500 sequential calls finish in ~2 minutes

Requires a token with admin/read/write access to the dashboard repository's
project. Without a token it exits 0 and does nothing, so the regular workflow
runs cleanly even before the secret is configured.

Usage:
    python3 sync_project.py --token <GH_TOKEN> --owner DSA-HOGA-ORG \
        --project-number 2 --dashboard generated/dashboard.json [--dry-run]

Only uses the Python standard library (urllib) so it runs inside GitHub Actions
with no extra dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com/graphql"
WORKERS = 8
REQUEST_TIMEOUT = 30

HEADERS = {"Accept": "application/vnd.github+json"}


def _http_request(token, query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={**HEADERS, "Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        data = json.loads(r.read().decode())
    if data.get("errors"):
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data.get("data")


class Gh:
    """Thread-safe GraphQL client: calls may run from a pool, so every call
    builds its own urlopen request."""

    def __init__(self, token: str, dry: bool = False):
        self.token = token
        self.dry = dry
        self._lock = threading.Lock()

    def call(self, query: str, variables: dict):
        if self.dry:
            with self._lock:
                print("[dry-run] would run:", query.splitlines()[-2].strip()[:60], variables)
            return {"dry": True}
        return _http_request(self.token, query, variables)


Q_PROJECT = """
query($owner: String!, $number: Int!) {
  organization(login: $owner) {
    projectV2(number: $number) {
      id title items(first: 100) {
        totalCount
      }
    }
  }
}
"""

Q_FIELDS = """
query($projectId: ID!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      fields(first: 100) {
        nodes {
          ... on ProjectV2SingleSelectField { id name dataType options { id name } }
          ... on ProjectV2Field { id name dataType }
        }
      }
    }
  }
}
"""

Q_ITEMS = """
query($projectId: ID!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content { ... on DraftIssue { title } ... on Issue { title } ... on PullRequest { title } }
        }
      }
    }
  }
}
"""

M_ADD_DRAFT = """
mutation($projectId: ID!, $title: String!) {
  addProjectV2DraftIssue(input: {projectId: $projectId, title: $title}) {
    projectItem { id }
  }
}
"""

M_CREATE_FIELD = """
mutation($projectId: ID!, $name: String!) {
  createProjectV2Field(
    input: {projectId: $projectId, name: $name, dataType: @@KIND@@}
  ) {
    projectV2Field {
      ... on ProjectV2SingleSelectField { id name }
      ... on ProjectV2Field { id name }
    }
  }
}
"""
# dataType must be a literal enum (ProjectV2CustomFieldType), not a variable
ALLOWED_KINDS = {"TEXT", "NUMBER", "DATE", "SINGLE_SELECT", "ITERATION"}

M_UPDATE_VALUES = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
  updateProjectV2ItemFieldValue(
    input: {projectId: $projectId, itemId: $itemId, fieldId: $fieldId, value: $value}
  ) { projectV2Item { id } }
}
"""

M_DELETE_ITEM = """
mutation($projectId: ID!, $itemId: ID!) {
  deleteProjectV2Item(input: {projectId: $projectId, itemId: $itemId}) {
    deletedItemId
  }
}
"""


def _load_registry(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_registry(path: Path, registry: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    Path(path.with_suffix(".tmp")).write_text(json.dumps(registry, indent=2))
    Path(path.with_suffix(".tmp")).replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--owner", required=True)
    ap.add_argument("--project-number", type=int, required=True)
    ap.add_argument("--dashboard", default="generated/dashboard.json")
    ap.add_argument("--problems", default="data/problems.json")
    ap.add_argument("--members", default="data/members.json")
    ap.add_argument("--registry", default="data/synced_items.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gh = Gh(args.token, args.dry_run)

    problems = json.loads(Path(args.problems).read_text())
    members = json.loads(Path(args.members).read_text())["members"]
    dash = json.loads(Path(args.dashboard).read_text())

    data = gh.call(Q_PROJECT, {"owner": args.owner, "number": args.project_number})
    project = (data or {}).get("organization", {}).get("projectV2")
    if not project:
        print(f"Project #{args.project_number} not found for {args.owner} — skipping.")
        return 0
    pid = project["id"]
    print(f"Project: {project['title']} (id {pid}, connection reports "
          f"{project['items']['totalCount']} items)")

    # --- ensure fields exist -------------------------------------------------
    def _fields():
        return gh.call(Q_FIELDS, {"projectId": pid})["node"]["fields"]["nodes"]

    field_ids = {f["name"]: f for f in _fields()}

    def ensure_field(name, kind):
        if name in field_ids:
            return field_ids[name]["id"]
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"disallowed field kind: {kind}")
        gh.call(M_CREATE_FIELD.replace("@@KIND@@", kind),
                {"projectId": pid, "name": name})
        return None

    ensure_field("Problem", "TEXT")
    ensure_field("Topic", "TEXT")
    ensure_field("Difficulty", "TEXT")
    ensure_field("Last Updated", "DATE")
    for m in members:
        ensure_field(m["display"], "TEXT")

    fields = _fields()
    field_ids = {f["name"]: f for f in fields}
    fid = {f["name"]: f["id"] for f in fields}
    ss_options = {}
    for f in fields:
        if f.get("dataType") == "SINGLE_SELECT":
            ss_options[f["id"]] = {o["name"]: o["id"] for o in f.get("options", [])}

    # map our statuses onto the DEFAULT Status field's existing options
    status_fid = fid.get("Status")
    ss = ss_options.get(status_fid, {}) if status_fid else {}
    status_map = {
        "Not Started": ss.get("Todo"),     # default field ships Todo/In Progress/Done
        "In Progress": ss.get("In Progress"),
        "Solved": ss.get("Done"),
    }

    # --- item registry (local, source of truth for item ids) -----------------
    registry = _load_registry(Path(args.registry))
    reg_items = registry.get("items", {})

    def _discover_items():
        """Best-effort warm start when the `items` connection works."""
        cursor = None
        while True:
            it = gh.call(Q_ITEMS, {"projectId": pid, "cursor": cursor})["node"]["items"]
            for node in it["nodes"]:
                content = node.get("content") or {}
                title = content.get("title") or ""
                if title:
                    reg_items.setdefault(title, node["id"])
            if not it["pageInfo"]["hasNextPage"]:
                break
            cursor = it["pageInfo"]["endCursor"]

    try:
        _discover_items()
    except Exception as exc:  # connection may be unsupported/empty — ignore
        print(f"  (warm-start skipped: {exc})")

    # --- member solved index ------------------------------------------------
    solved_by = {m["id"]: set() for m in members}
    for m in dash["members"]:
        info = dash["by_member"].get(m["id"], {})
        for pid_ in info.get("solved_ids", []):
            problem = next((p["name"] for p in problems if p["id"] == pid_), None)
            if problem:
                solved_by[m["id"]].add(problem)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- plan updates ---------------------------------------------------------
    plan = []            # (item_id, field_id, value) or None when item unknown
    created = 0
    for p in problems:
        title = f"{p['id']:03d}. {p['name']}"
        item_id = reg_items.get(title)
        if item_id is None:
            if args.dry_run:
                gh.call(M_ADD_DRAFT, {"projectId": pid, "title": title})
                item_id = "DRY-ITEM"
                created += 1
            else:
                res = gh.call(M_ADD_DRAFT, {"projectId": pid, "title": title})
                item_id = (res.get("addProjectV2DraftIssue") or {}).get("projectItem", {}).get("id")
                if not item_id:
                    print(f"  ! failed to create item for {title}")
                    continue
                reg_items[title] = item_id
                created += 1
        member_marks = [
            (m["display"], "Solved" if p["name"] in solved_by[m["id"]] else "Not started")
            for m in members
        ]
        any_solved = any(flag == "Solved" for _, flag in member_marks)
        status = "Solved" if any_solved else "Not Started"
        status_opt = status_map.get(status)
        values = {
            "Problem": {"text": p["name"]},
            "Topic": {"text": p["topic"]},
            "Difficulty": {"text": p["difficulty"] or "—"},
            "Last Updated": {"date": now},
            **{name: {"text": flag} for name, flag in member_marks},
        }
        if status_fid and status_opt:
            values["Status"] = {"singleSelectOptionId": status_opt}
        for fname, value in values.items():
            f = fid.get(fname)
            if f:
                plan.append((item_id, f, value))

    # --- drop registry entries whose problems no longer exist ----------------
    wanted = {f"{p['id']:03d}. {p['name']}" for p in problems}
    for stale in [t for t in reg_items if t not in wanted]:
        gh.call(M_DELETE_ITEM, {"projectId": pid, "itemId": reg_items[stale]})
        del reg_items[stale]
        print(f"  pruned stale item: {stale}")

    # --- apply the plan with a worker pool ------------------------------------
    def apply_one(job):
        item_id, field_id, value = job
        gh.call(M_UPDATE_VALUES, {
            "projectId": pid, "itemId": item_id, "fieldId": field_id, "value": value,
        })
        return item_id

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(apply_one, job) for job in plan]
        for _ in as_completed(futs):
            done += 1
            if done % 200 == 0:
                print(f"  updated {done}/{len(plan)} fields")

    _save_registry(Path(args.registry), {"project_id": pid, "items": reg_items})
    print(f"Project sync complete. {len(problems)} problems, "
          f"{created} items created, {len(plan)} field updates applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())