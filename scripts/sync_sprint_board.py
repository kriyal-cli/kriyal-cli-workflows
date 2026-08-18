#!/usr/bin/env python3
"""Sync each org's Sprint Board (GitHub Projects v2) CI + Status fields
from live PR state - one paginated GraphQL query per org, one mutation per
field that actually changed. No per-repo CI wiring, no per-push webhook
cost: this runs on a schedule (or on-demand via workflow_dispatch) and only
writes what's actually stale, so API/token cost scales with drift, not with
push volume.

CI field: Passing/Failing/Pending, derived from the PR's head commit
statusCheckRollup.

Status field: Ready to Merge / Changes Requested, derived from
reviewDecision - only applied when the current Status is one of the states
this script owns (Todo/In Progress/Ready to Merge/Changes Requested), never
touching Done or any other custom value a human set by hand. Closed/merged
PRs are skipped entirely, on the same principle.

Usage: GH_TOKEN=<pat with project scope> python3 sync_sprint_board.py [org ...]
       (no args = every org listed in orgs.txt, next to this script's repo
       root - the same file kriyal-cli-workflows/sync-dependabot.yml reads,
       kept as one shared list rather than a second copy that can drift)
"""
import json
import os
import subprocess
import sys

DEFAULT_ORGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "orgs.txt")


def load_default_orgs():
    path = os.environ.get("ORGS_FILE", DEFAULT_ORGS_FILE)
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]

# Status values this script is allowed to set/overwrite - anything else
# (Done, or a custom value a human picked) is left alone.
STATUS_OWNED = {"Todo", "In Progress", "Ready to Merge", "Changes Requested"}

ITEMS_QUERY = """
query($org: String!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: 1) {
      id
      ci: field(name: "CI") { ... on ProjectV2SingleSelectField { id options { id name } } }
      status: field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } }
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          ciValue: fieldValueByName(name: "CI") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          statusValue: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          content {
            __typename
            ... on PullRequest {
              number
              state
              reviewDecision
              repository { name }
              commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
            }
          }
        }
      }
    }
  }
}
"""

MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field,
    value: { singleSelectOptionId: $option }
  }) { projectV2Item { id } }
}
"""


def gh_graphql(query, **fields):
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in fields.items():
        args += ["-f", f"{k}={v}"]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        print(f"  ! graphql call failed: {out.stderr.strip()}", file=sys.stderr)
        return None
    return json.loads(out.stdout)


def rollup_to_ci(state):
    if state == "SUCCESS":
        return "Passing"
    if state in ("FAILURE", "ERROR"):
        return "Failing"
    return "Pending"  # PENDING, EXPECTED, or no checks at all yet


def decision_to_status(decision):
    if decision == "APPROVED":
        return "Ready to Merge"
    if decision == "CHANGES_REQUESTED":
        return "Changes Requested"
    return None  # REVIEW_REQUIRED / null - not this script's call to make


def sync_org(org):
    print(f"=== {org} ===")
    project_id = None
    ci_field = None
    status_field = None
    cursor = None
    changed = 0
    scanned = 0

    while True:
        resp = gh_graphql(ITEMS_QUERY, org=org, cursor=cursor or "")
        if resp is None or resp.get("errors"):
            if resp and resp.get("errors"):
                print(f"  ! {resp['errors']}", file=sys.stderr)
            break
        proj = (resp.get("data") or {}).get("organization", {}).get("projectV2")
        if not proj:
            print("  (no project #1 - skipping)")
            return
        project_id = proj["id"]
        ci_field = proj["ci"]
        status_field = proj["status"]
        if not ci_field or not status_field:
            print("  ! missing CI or Status field - run the field-setup step first")
            return
        ci_opt_by_name = {o["name"]: o["id"] for o in ci_field["options"]}
        status_opt_by_name = {o["name"]: o["id"] for o in status_field["options"]}

        items = proj["items"]
        for node in items["nodes"]:
            content = node.get("content") or {}
            if content.get("__typename") != "PullRequest":
                continue
            if content.get("state") != "OPEN":
                continue  # closed/merged - not this script's concern
            scanned += 1

            commits = content.get("commits", {}).get("nodes", [])
            rollup = commits[0]["commit"]["statusCheckRollup"] if commits else None
            desired_ci = rollup_to_ci(rollup["state"] if rollup else None)
            current_ci = (node.get("ciValue") or {}).get("name")
            if desired_ci != current_ci and desired_ci in ci_opt_by_name:
                r = gh_graphql(
                    MUTATION, project=project_id, item=node["id"],
                    field=ci_field["id"], option=ci_opt_by_name[desired_ci],
                )
                ok = r is not None and not r.get("errors")
                print(f"  {'ok' if ok else 'FAIL'}: PR #{content['number']} ({content['repository']['name']}) CI {current_ci!r} -> {desired_ci!r}")
                if ok:
                    changed += 1

            desired_status = decision_to_status(content.get("reviewDecision"))
            current_status = (node.get("statusValue") or {}).get("name")
            if (desired_status and desired_status != current_status
                    and current_status in STATUS_OWNED
                    and desired_status in status_opt_by_name):
                r = gh_graphql(
                    MUTATION, project=project_id, item=node["id"],
                    field=status_field["id"], option=status_opt_by_name[desired_status],
                )
                ok = r is not None and not r.get("errors")
                print(f"  {'ok' if ok else 'FAIL'}: PR #{content['number']} ({content['repository']['name']}) Status {current_status!r} -> {desired_status!r}")
                if ok:
                    changed += 1

        if items["pageInfo"]["hasNextPage"]:
            cursor = items["pageInfo"]["endCursor"]
        else:
            break

    print(f"  {scanned} open PRs scanned, {changed} field(s) updated")


def main():
    orgs = sys.argv[1:] or load_default_orgs()
    for org in orgs:
        sync_org(org)


if __name__ == "__main__":
    main()
