#!/usr/bin/env python3
"""
Create a test-case board on GitHub Projects v2, with the fields the
maintenance pipeline and the review digest expect.

Ten minutes of clicking, except reproducible -- which matters once there is a
second org, and matters more when someone needs to know why a field exists.
The config carries that reasoning beside each field.

Idempotent: run it again and it adds what is missing, leaving what is there
alone. It NEVER edits an existing field's options. Editing a single-select
field through the API means re-sending every option, and an option sent
without its current `id` is treated as new -- GitHub regenerates the ids and
every item's value for that field is orphaned, board-wide. Adding an option to
a live board is a deliberate act, not something a setup script should do on a
re-run.

Usage:
  export GH_TOKEN=...                 # needs org Projects read+write
  python3 setup-tc-board.py --owner my-org --config board-config.json
  python3 setup-tc-board.py --owner my-org --config board-config.json --dry-run

  --project-id PVT_...    add missing fields to an existing board instead of
                          creating one

Exit codes:
  0 — the board matches the config
  1 — something failed; what was already created is reported and left in place
"""

import argparse
import json
import subprocess
import sys

BUILT_IN = {"Title", "Assignees", "Labels", "Linked pull requests", "Milestone",
            "Repository", "Reviewers", "Parent issue", "Sub-issues progress",
            "Created", "Updated", "Closed"}


def gql(query, token, **variables):
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        cmd += ["-f", f"{k}={v}"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={**__import__("os").environ, "GH_TOKEN": token},
                       timeout=60)
    try:
        body = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError((r.stderr or r.stdout or "no output").strip()[:300])
    if body.get("errors"):
        raise RuntimeError(json.dumps(body["errors"])[:300])
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[:300])
    return body["data"]


def owner_id(owner, token):
    """The org's node id, falling back to a user account."""
    try:
        d = gql('query($l:String!){ organization(login:$l){ id } }', token, l=owner)
        if d.get("organization"):
            return d["organization"]["id"], "organization"
    except RuntimeError:
        pass
    d = gql('query($l:String!){ user(login:$l){ id } }', token, l=owner)
    if not d.get("user"):
        raise RuntimeError(f"no organization or user named {owner!r}")
    return d["user"]["id"], "user"


def existing_fields(project_id, token):
    """(title, url, {name: id}) for the fields already on the board."""
    d = gql('''query($p:ID!){ node(id:$p){ ... on ProjectV2 {
                 title url
                 fields(first:50){ nodes {
                   ... on ProjectV2FieldCommon { id name }
                 } } } } }''', token, p=project_id)
    node = d.get("node") or {}
    found = {f["name"]: f["id"]
             for f in (node.get("fields") or {}).get("nodes") or []
             if f and f.get("name")}
    return node.get("title"), node.get("url"), found


def create_project(oid, title, token):
    d = gql('''mutation($o:ID!,$t:String!){
                 createProjectV2(input:{ownerId:$o,title:$t}){
                   projectV2 { id title url number } } }''',
            token, o=oid, t=title)
    return d["createProjectV2"]["projectV2"]


def set_options(field_id, spec, token):
    """Replace a single-select field's options.

    Only ever called on a board this script just created, where the field is
    GitHub's default and no item carries a value yet. Replacing options on a
    populated board regenerates their ids and orphans every item's value, so
    an existing board is never touched -- see the note in the module docstring.
    """
    opts = _options_literal(spec)
    gql('''mutation($f:ID!){
             updateProjectV2Field(input:{fieldId:$f, singleSelectOptions:[%s]}){
               projectV2Field { ... on ProjectV2FieldCommon { id name } } } }''' % opts,
        token, f=field_id)


def _options_literal(spec):
    # Inline rather than a variable: `gh api -f` sends every value as a string,
    # so a JSON list passed that way arrives quoted.
    return ", ".join(
        "{{name:{n} color:{c} description:{d}}}".format(
            n=json.dumps(o["name"]),
            c=o.get("color", "GRAY"),
            d=json.dumps(o.get("description", "")))
        for o in spec["options"])


def create_field(project_id, spec, token):
    name = spec["name"]
    if (spec.get("type") or "SINGLE_SELECT") == "TEXT":
        d = gql('''mutation($p:ID!,$n:String!){
                     createProjectV2Field(input:{projectId:$p,dataType:TEXT,name:$n}){
                       projectV2Field { ... on ProjectV2FieldCommon { id name } } } }''',
                token, p=project_id, n=name)
    else:
        opts = _options_literal(spec)
        d = gql('''mutation($p:ID!,$n:String!){
                     createProjectV2Field(input:{projectId:$p,dataType:SINGLE_SELECT,
                       name:$n, singleSelectOptions:[%s]}){
                       projectV2Field { ... on ProjectV2FieldCommon { id name } } } }''' % opts,
                token, p=project_id, n=name)
    return d["createProjectV2Field"]["projectV2Field"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True, help="org (or user) login")
    ap.add_argument("--config", required=True)
    ap.add_argument("--project-id", help="add fields to this board instead of creating one")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import os
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Set GH_TOKEN to a token with org Projects read+write.", file=sys.stderr)
        return 1

    with open(a.config) as f:
        cfg = json.load(f)
    specs = [s for s in cfg.get("fields") or [] if s.get("name")]
    if not specs:
        print(f"{a.config} defines no fields.", file=sys.stderr)
        return 1

    fresh = False
    try:
        if a.project_id:
            project_id = a.project_id
            title, url, have = existing_fields(project_id, token)
            print(f"Board: {title}\n  {url}")
        else:
            oid, kind = owner_id(a.owner, token)
            title = cfg.get("title") or "Test Case Management"
            if a.dry_run:
                print(f"Would create {kind} project {title!r} under {a.owner}")
                # A real run would find the built-in Status here.
                project_id, url = None, None
                have, fresh = {"Status": "<built-in>"}, True
            else:
                p = create_project(oid, title, token)
                project_id, url = p["id"], p["url"]
                print(f"Created: {p['title']}  (#{p['number']})\n  {url}\n  id: {project_id}")
                # A new project is born with a built-in Status field holding
                # Todo / In Progress / Done, so creating one named Status is
                # refused ("Name has already been taken"). Read what is there
                # and adopt it instead.
                _, _, have = existing_fields(project_id, token)
                fresh = True

        print()
        made, skipped, adopted = 0, 0, 0
        for spec in specs:
            name = spec["name"]
            if name in have:
                # On a board we just made, a built-in single-select is ours to
                # shape: it is GitHub's default and no item has a value yet.
                # On a pre-existing board it is never touched.
                if (fresh and spec.get("options")
                        and (spec.get("type") or "SINGLE_SELECT") == "SINGLE_SELECT"):
                    if not a.dry_run:
                        set_options(have[name], spec, token)
                    print(f"  ~ {name}  ({len(spec['options'])} options — replaced the default)")
                    adopted += 1
                else:
                    print(f"  = {name}  (already present — left alone)")
                    skipped += 1
                continue
            if a.dry_run:
                n = len(spec.get("options") or [])
                print(f"  + {name}" + (f"  ({n} options)" if n else "  (text)"))
                made += 1
                continue
            create_field(project_id, spec, token)
            n = len(spec.get("options") or [])
            print(f"  + {name}" + (f"  ({n} options)" if n else "  (text)"))
            made += 1

        print()
        verb = "would add" if a.dry_run else "added"
        extra = f", {adopted} default field(s) reshaped" if adopted else ""
        print(f"{verb} {made} field(s){extra}; {skipped} left alone.")
        if not a.dry_run and project_id:
            print(f"\nBoard node id (the pipeline needs this):\n  {project_id}")
            print("\nNext: set it as BOARD_ID for the maintenance workflow, and give "
                  "the automation a token with Projects read+write on this org.")
        return 0
    except RuntimeError as e:
        print(f"\nFailed: {e}", file=sys.stderr)
        print("Anything created above is left in place; re-run to continue.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
