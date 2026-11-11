# GitHub test-case board

Creates a [GitHub Projects v2](https://docs.github.com/issues/planning-and-tracking-with-projects) board for managing manual test cases — reproducibly, instead of clicking through the UI and hoping the next org matches.

Ten minutes of clicking is not the reason this exists. The reason is that **the field design determines whether you can automate on top of it later**, and that design is easy to get subtly wrong.

## Quick start

```bash
export GH_TOKEN=...          # a token with Projects read+write on the owner
cp board-config.example.json board-config.json
# edit the Module options to your product's areas

python3 setup-tc-board.py --owner my-org --config board-config.json --dry-run
python3 setup-tc-board.py --owner my-org --config board-config.json
```

Works for an organisation or a personal account. Requires Python 3.8+ and the [`gh` CLI](https://cli.github.com/), authenticated.

Add fields to a board that already exists:

```bash
python3 setup-tc-board.py --owner my-org --config board-config.json --project-id PVT_...
```

## What it builds

A test case is a **draft item** — not a repository issue, so thousands of them never touch your issue tracker. The case narrative (preconditions, steps, expected result) lives in the draft's body; everything else is a field.

| Field | Type | Purpose |
|---|---|---|
| `Status` | single select | Lifecycle, including the two-stage review states |
| `Module` | single select | Which product area — **the one field you rewrite** |
| `Priority` | single select | `P0-Smoke` / `P1-Regression` / `P2-Extended` |
| `Automation Status` | single select | Links the case to your automated suite |
| `Role` | single select | Which actor performs it |
| `Review Notes` | text | Reviewer-owned; automation never touches it |

## The three design decisions that matter

### 1. `Status` has two-stage review states

```
Draft · Approved · Deprecated
Updated (Under Review) · Deprecated (Under Review)
Duplicate · Bug
```

The `(Under Review)` states let automation **propose** a change without asserting it is correct. A pipeline may set those; only a person promotes to `Approved` or `Deprecated`.

Remove them and there is no safe way to run maintenance unattended — any automated edit becomes an assertion nobody checked.

### 2. `Module` naming is load-bearing

Name options `<Category> — <Module>`:

```
Auth — Authentication
Auth — Onboarding
Billing — Subscriptions
```

The prefix is not decoration. A duplicate check can scan an entire category by it, and reporting groups by it. Pick a convention and hold it — inconsistently-named options make both useless.

### 3. `Automation Status` is the seam to your test suite

```
Not Automated · Automated · Needs Review · Blocked
```

`Needs Review` is the interesting one: set it when an **automated** case changes, meaning its spec probably no longer matches. That set is the backlog where manual QE and automation actually meet, and most teams have no name for it.

## Safety

**The script never edits an existing field's options.**

Editing a single-select through the API means re-sending every option, and an option sent without its current `id` is treated as new — GitHub regenerates the ids and **every item's value for that field is orphaned, board-wide**.

The one exception is a board this script just created, where a single-select is still GitHub's default and no item has a value yet. That is how the built-in `Status` (`Todo / In Progress / Done`) gets reshaped.

Re-running is safe: it adds what is missing and reports what it left alone.

## After the board exists

The board is the substrate. What makes it pay off is what you run on top:

- **Doc-driven maintenance** — read merged PRs that changed product documentation, and create or update the test cases that no longer match
- **A review digest** — report what is sitting in the `(Under Review)` states, oldest first, because that queue grows unseen

Both rely on the field design above, particularly the two-stage `Status`.

## Config

`board-config.example.json` carries the reasoning for each field inline, in `_why` keys the script ignores. Copy it, rewrite `Module` and `Role` for your product, and leave the rest unless you have a reason — those are what tooling reads.

## Licence

MIT.
