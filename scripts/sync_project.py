#!/usr/bin/env python3
"""
Sync dashboard progress into a GitHub Projects v2 board (org-level).

This is OPTIONAL. The dashboard repository (README.md + generated/dashboard.json)
is the source of truth; this script mirrors a summary into GitHub Project #2 so
the team gets an interactive tracker.

The script is fully idempotent:
  * ensures the projected fields exist
  * creates one draft item per canonical problem (title = "N. Problem name"),
    reusing existing items by title
  * updates each item's Topic / Difficulty / Status / per-member / Last-Updated

Requires a token with admin/read/write access to both the dashboard repository's
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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com/graphql"

MEMBER_LABEL = "solved"
STATUS_OPTIONS = ["Not Started", "In Progress", "Solved"]

HEADERS = {"Accept": "application/vnd.github+json"}


class Gh:
    def __init__(self, token: str, dry: bool = False):
        self.token = token
        self.dry = dry

    def _req(self, query: str, variables: dict):
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(
            API, data=body, method="POST",
            headers={**HEADERS, "Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read().decode())
        if data.get("errors"):
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data.get("data")

    def mutate(self, query: str, variables: dict):
        if self.dry:
            print("[dry-run] would run:", query.splitlines()[-2].strip()[:60], variables)
            return {"ok": True}
        return self._req(query, variables)


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
          id name dataType
          options { id name }
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
mutation($projectId: ID!, $name: String!, $kind: String!) {
  createProjectV2Field(input: {projectId: $projectId, name: $name, dataType: $kind}) {
    projectV2Field { id name }
  }
}
"""

M_UPDATE_VALUES = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
  updateProjectV2ItemFieldValues(
    input: {projectId: $projectId, itemId: $itemId, fieldId: $fieldId, value: $value}
  ) { projectV2Item { id } }
}
"""

M_ADD_OPTION = """
mutation($fieldId: ID!, $option: String!) {
  updateProjectV2SingleSelectFieldOption(
    input: {fieldId: $fieldId, singleSelectFieldId: $fieldId, name: $option}
  ) { singleSelectField { id } }
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--owner", required=True)
    ap.add_argument("--project-number", type=int, required=True)
    ap.add_argument("--dashboard", default="generated/dashboard.json")
    ap.add_argument("--problems", default="data/problems.json")
    ap.add_argument("--members", default="data/members.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gh = Gh(args.token, args.dry)

    problems = json.loads(Path(args.problems).read_text())
    members = json.loads(Path(args.members).read_text())["members"]
    dash = json.loads(Path(args.dashboard).read_text())

    data = gh._req(Q_PROJECT, {"owner": args.owner, "number": args.project_number})
    project = (data or {}).get("organization", {}).get("projectV2")
    if not project:
        print(f"Project #{args.project_number} not found for {args.owner} — skipping.")
        return 0
    pid = project["id"]
    print(f"Project: {project['title']} (id {pid}, items {project['items']['totalCount']})")

    fields = gh._req(Q_FIELDS, {"projectId": pid})["node"]["fields"]["nodes"]
    field_ids = {f["name"]: f for f in fields}
    name2sid = {}
    for f in fields:
        if f["dataType"] == "SingleSelect":
            name2sid[f["name"]] = {o["name"]: o["id"] for o in f.get("options", [])}

    def ensure_field(name, kind):
        if name in field_ids:
            return field_ids[name]["id"]
        gh.mutate(M_CREATE_FIELD, {"projectId": pid, "name": name, "kind": kind})
        return None  # refetch below

    # fields we want
    field_kinds = {
        "Problem": "TEXT",
        "Topic": "TEXT",
        "Difficulty": "TEXT",
        "Status": "SINGLE_SELECT",
        "Last Updated": "DATE",
    }
    for m in members:
        field_kinds[m["display"]] = "TEXT"

    ensure_field("Problem", "TEXT")
    ensure_field("Topic", "TEXT")
    ensure_field("Difficulty", "TEXT")
    ensure_field("Status", "SINGLE_SELECT")
    ensure_field("Last Updated", "DATE")
    for m in members:
        ensure_field(m["display"], "TEXT")

    # refetch to get fresh ids
    fields = gh._req(Q_FIELDS, {"projectId": pid})["node"]["fields"]["nodes"]
    field_ids = {f["name"]: f for f in fields}
    fid = {f["name"]: f["id"] for f in fields}
    ss_options = {}
    for f in fields:
        if f["dataType"] == "SingleSelect":
            ss_options[f["id"]] = {o["name"]: o["id"] for o in f.get("options", [])}

    # ensure Status options
    status_fid = fid.get("Status")
    if status_fid:
        have = set(ss_options.get(status_fid, {}))
        for opt in STATUS_OPTIONS:
            if opt not in have:
                gh.mutate(M_ADD_OPTION, {"fieldId": status_fid, "option": opt})
        # refetch status options after adding
        fields = gh._req(Q_FIELDS, {"projectId": pid})["node"]["fields"]["nodes"]
        ss_options = {}
        for f in fields:
            if f["dataType"] == "SingleSelect":
                ss_options[f["id"]] = {o["name"]: o["id"] for o in f.get("options", [])}

    # existing items by title
    existing = {}
    cursor = None
    while True:
        it = gh._req(Q_ITEMS, {"projectId": pid, "cursor": cursor})["node"]["items"]
        for node in it["nodes"]:
            content = node.get("content") or {}
            title = content.get("title") or ""
            existing[title] = node["id"]
        if not it["pageInfo"]["hasNextPage"]:
            break
        cursor = it["pageInfo"]["endCursor"]

    # member solved index: member display -> set of problem names
    solved_by = {m["id"]: set() for m in members}
    for m in dash["members"]:
        info = dash["by_member"].get(m["id"], {})
        for pid_ in info.get("solved_ids", []):
            problem = next((p["name"] for p in problems if p["id"] == pid_), None)
            if problem:
                solved_by[m["id"]].add(problem)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for p in problems:
        title = f"{p['id']:03d}. {p['name']}"
        item_id = existing.get(title)
        if item_id is None:
            res = gh.mutate(M_ADD_DRAFT, {"projectId": pid, "title": title})
            if res is None:
                continue
            item_id = (res.get("addProjectV2DraftIssue") or {}).get("projectItem", {}).get("id")
            if not item_id:
                print(f"  ! failed to create item for {title}")
                continue
        # decide status + member marks
        member_marks = []
        for m in members:
            member_marks.append((m["display"], "Solved" if p["name"] in solved_by[m["id"]] else "Not started"))
        any_solved = any(flag == "Solved" for _, flag in member_marks)
        status = "Solved" if any_solved else "In Progress" if False else "Not Started"
        # single select value
        status_opt = ss_options.get(status_fid, {}).get(status)
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
            if not f:
                continue
            gh.mutate(M_UPDATE_VALUES, {
                "projectId": pid, "itemId": item_id, "fieldId": f, "value": value,
            })
    print("Project sync complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())