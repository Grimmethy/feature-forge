# Feature Forge: design (agreed 2026-11-13 grill)

Clone of AuthorForge's shape (Flask, plain Markdown, Forges-group tab, chat-plugin grill panel), planned on 127.0.0.1:7466. Registered in Agent Manager as a pool project when released.

## Files are the product
```
features/<slug>/
  request.md     the owner's original prompt
  plan.md        agreed design; "Delivered" section appended when Done
  interview.md   every grill session, appended
  checklist.md   source of truth for items
  .history/ .grill/   git-ignored
```
Checklist line: `- [ ] FF-3 Add intake form <!-- task: adhoc-... premium: true cloud: false deps: FF-1,FF-2 filed: 2026-11-13T10:00 -->`. Per-stage timestamps are kept in the item's own log lines.

## Flow
1. Owner enters the request. First grill question = target repo: the AI recommends existing vs new and proposes a name; owner decides. New repo = a "Create repo" button after confirmation, showing the steps (git init, private GitHub repo, projects.json `pool: true`, pipeline dir). Never silent.
2. Grill opens in the existing chat-plugin panel with read-only Read/Grep/Glob rooted at the target repo (no Bash/Write/WebSearch). Needs a per-session tool allowlist in the chat plugin (separate task in agent-manager-chat-plugin).
3. After confirmation the model proposes the checklist as a diff; owner edits. Each item = one self-contained task (title, full text, files hint, acceptance test, deps, premium and polling flags). Items are also grill nodes; an item grill can end by proposing a split. Filed items are locked ("changed since filing", never silent refiling).
4. File button: all-or-nothing per feature. Prefer a dashboard route for adhoc tasks; otherwise shell out to `queue-adhoc-task.js`. Premium toggle per item; cloud toggle per feature.
5. Polling lint at filing (see below). Standard "prefer a trigger" clause appended to every filed task.
6. Status: auto-tick from AM task state (read-only), no timer; refresh on open, on Refresh and on triggers. Hand-ticks marked manual. All merged -> Done automatically; "Delivered" section with merge ids appended to plan.md. Cancel feature archives only unclaimed tasks after confirmation.

## Triggers over polls (three layers)
1. Grill asks, per item: what event could trigger this instead of a timer?
2. Every filed task carries the standard clause.
3. Lint flags `setInterval`, `cron`, `poll`, `every N minutes` without a justification; warns and needs explicit owner accept (no hard fail: watchdogs can be legitimate).

## Cloud toggle
One shared Sonnet 5.5 cloud lane `worker-cloud-ff` (lanes.json, `provider: cloud`, allowlist class `feature-forge-cloud`, gateway needs a Sonnet 5.5 model entry). Toggle tags a feature's unclaimed tasks with the class; off returns them to the local pipeline; in-progress tasks stay. Spend shows in the Cloud spend panel under the existing cap. Cloud lanes are global and never overflow, so this is a class tag, not a lane per feature.

## Timing
Timestamps for filed, claimed, each stage change, branch pushed, verdict, merged. Library shows median and slowest per stage, split by lane and premium. Default deadline 24 h. At 10+ samples per lane and stage the manager PROPOSES a new deadline (e.g. p90 x 1.5); owner accepts.

## Library views
Flat (status chips Grilling/Planned/Filed/Building/Done + progress bar), Board (read-only derived columns), Graph (per feature, hand-built layered SVG from deps, colors done/building/blocked/unfiled), By repo (roll-up). Done filter and search so finished features stay referenceable.

## Manager loop (Workers-tab card)
A manager, not a carrier: the branch verifier, Needs-Work worker and merger already verify and merge, and atomization means no duplicate abilities. Watches five "lost" conditions: vanished record; unclaimed past deadline; claimed with no stage change past deadline; unmerged branch with a verdict and no action; blocked by an archived/discarded dependency. Closed actions: flag the item, re-file a vanished record from checklist text, bump an unclaimed task to premium ONCE (with a note), write a note for the owner. Never carries, verifies, merges, discards or archives. Wakes on task-state events (AM triggers channel, ADR-0024) and per-task deadline triggers; standard watchdog trigger + one perpetual drain. Dry run 15 minutes, owner flips live. Code lives in this repo, registered like AuthorForge.

## Build slices (premium task records, build-loop)
1. Scaffold, store, library (flat list, search, Done filter).
2. Grill panel, repo intake question, read-only tools (+ chat-plugin change).
3. Checklist format, diff proposals, item grills with splitting.
4. Filing, polling lint, premium and cloud toggles, Sonnet lane entry.
5. Status sync (auto-tick) and timing data.
6. Board, Graph, By-repo views.
7. Manager loop (15 min dry run) and repo-creation button.

## To verify during the build
Port 7466 free (checked 2026-11-13: yes); chat plugin per-session tool allowlist (not found in source); dashboard adhoc-task route; gateway Sonnet 5.5 entry.
