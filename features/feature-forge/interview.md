# Interview: Feature Forge

## Session 2026-11-13 (claude, Claude Code)
Four rounds of grilling; decisions are recorded in `../../Docs/DESIGN.md`. Owner corrections: the manager loop must not duplicate verify/merge loops; dry runs are 15 minutes tops; richer library views (board, graph, by repo) are in v1; completed features stay referenceable with a Done filter; no polls ever.

## Session 2026-11-19 03:54 (FF-4, chat chat-1795085463-a4751e9f)

**Grill:**

I read the cloud lane doc, `lanes.js`, the cloud-providers README, `DESIGN.md` and Feature Forge's `filing.py`. 4c is too big for one task, and several of its decisions are open.

What I found:
- **One model per gateway.** The gateway picks its model from the `CLOUD_MODEL` env var and never from the caller. Sonnet 5.5 therefore needs a second gateway process, not a new model entry in the existing one.
- **Lanes filter by task source.** A lane's `taskClasses` allowlist matches task source names. Every Feature Forge task is source `adhoc`, and the Haiku lane `worker-cloud` already claims `adhoc`. A Sonnet lane allowlisting `adhoc` would only compete with it.
- **The cloud flag does nothing yet.** In `filing.py` the cloud flag is stored in `checklist.md` only. Nothing stamps a class on the task, so the Cloud button has no effect on routing today.
- **Local lanes would still claim cloud-class tasks.** A lane with no allowlist claims any source, so a tagged task could still land on a local lane.

Round 1:

**Q1 - Repos:** Which repos does 4c touch?
-> Three. `cloud-providers` (second gateway instance), `agent-manager` (lane entry, class routing, docs) and `feature-forge` (toggle wiring). Each piece below is confined to one repo, and `agent-manager` is the primary.

**Q2 - Second gateway:** How is Sonnet 5.5 served?
-> A second process of the same gateway code on port 7451 (`CLOUD_PROVIDERS_PORT=7451`, `CLOUD_MODEL=claude-sonnet-5-5`), with its own spend ledger. It is registered as plugin `cloud-providers-sonnet` and started the same way as the Haiku one. Billing follows the Haiku gateway's setup, with API key as the supported route.

**Q3 - Class name:** What identifies the cloud class?
-> A new task source name, `feature-forge-cloud`. Lane `worker-cloud-ff` allowlists only that. The Haiku lane stays `["adhoc"]`.

**Q4 - How a task gets the class:** How does the toggle change routing?
-> The cloud toggle sets or clears a `cloudClass` field on each unclaimed task through a dashboard `/api/task...` route, not by editing `queue/`. In-progress tasks are left alone, as `DESIGN.md` says. The event is the button click, so there is no timer.

**Q5 - Keeping local lanes off tagged tasks:** What stops local lanes claiming a task while it is tagged?
-> `next-claimable-task.js` skips any task with `cloudClass` unless the lane's allowlist includes that class. Clearing the tag (toggle off) puts the task back in the local pipeline.

**Q6 - Spend:** How does Sonnet spend show up?
-> The Cloud spend panel lists each gateway separately (Haiku, Sonnet), each with its own price variables and optional cap in `warn` mode. A spent hourly budget on the Sonnet gateway uses the existing `gateway-budget.js` check, so the lane pauses instead of burning drafts on 429s.

**Q7 - Default state:** Is the lane on by default?
-> No. `lanes.example.json` gets `worker-cloud-ff` with `"enabled": false`, and `docs/agents/cloud-lane.md` documents turning it on. The owner enables it, because it spends money.

**Q8 - Triggers vs polls:** Does any part of 4c need a timer?
-> No. The toggle click stamps the tag. The existing worker claim loop picks up tagged tasks, and the budget check runs inside the existing breaker. A new poll or timer would need a written justification, and none is proposed.

**Q9 - Split:** How is 4c split into tasks?
-> Four tasks, each finishable inside one repo:
- 4c1 (`cloud-providers`): the second gateway instance, with a port and model run script, tests, and README.
- 4c2 (`agent-manager`): the `worker-cloud-ff` entry in `lanes.example.json`, a "Sonnet lane" section in `cloud-lane.md`, and the Cloud spend panel listing both gateways.
- 4c3 (`agent-manager`): the `cloudClass` task field, the dashboard set/clear route, and the claim-time skip rule, with tests.
- 4c4 (`feature-forge`): the Cloud button calls that route on a feature's unclaimed tasks, with tests and a browser check.

Say "yes" to accept all nine, or give the numbers you want changed.

---

**Owner:**

[Owner decision relayed by the Claude Code session on 2026-11-19, not a bot answer] Do not split or build 4c. It is superseded by the Cloud agent pool entry (cloud agents claim any class, with a dial in the Workers tab), which covers a cloud lane and class routing. Propose a checklist change that drops 4c as superseded by the cloud-agent-pool entry, so FF-4 closes with 4a and 4b merged.

---

**Grill:**

Understood. The owner has decided 4c is superseded by the Cloud agent pool entry, so I'm dropping it and not splitting it. 4c has no task, filed or merged tag, so a piece `supersede` is allowed. Once 4a and 4b are merged and 4c is ticked, FF-4 closes.

Two notes on the diff:
- I use `supersede`, not `remove`. That ticks 4c as done by other means and keeps it in the history with the reason. The step then closes on its own, since every remaining piece is ticked.
- Nothing is built, so there is no new polling or timer to justify.

```checklist-diff
{"ops": [
  {"op": "supersede", "id": "FF-4", "piece": "4c", "reason": "superseded by the Cloud agent pool entry (cloud agents claim any class, with a dial in the Workers tab), which covers the cloud lane and class routing; owner decision 2026-11-19"}
]}
```

---

**Owner:**

[Relayed owner session] The review refused your diff: the reason must be at most 120 characters, no comment marks, no word ending in a colon. Resend the same supersede op for 4c with a reason under 100 characters, for example: superseded by the cloud agent pool entry

---

**Grill:**

Here is the same supersede op for 4c with a shorter reason. The reason has no comment marks and no word ending in a colon.

```checklist-diff
{"ops": [
  {"op": "supersede", "id": "FF-4", "piece": "4c", "reason": "superseded by the cloud agent pool entry"}
]}
```

## Session 2026-11-19 03:59 (FF-7, chat chat-1795085719-892ad00e)

**Grill:**

I've read what 7a–7c built and how the other workers are wired, so here is the first round.

**What I found**
- **The manager exists as a library.** `feature-forge/server/core/manager.py` has `decide()` and `tick()`. It has a write-ahead ledger at `<features root>/.manager-ledger.jsonl`, its own 24-hour dedup, and modes read from `FEATUREFORGE_MANAGER_MODE`. Nothing calls `tick()` yet, and `feature-forge/register.js` is a no-op.
- **The trigger and drain machinery is Node, in `agent-manager-pipeline-ops`.** It is `src/trigger.js` plus `src/worker-kit.js`, with `bin/<name>-trigger.js` and `bin/<name>-tick.js` per worker. The `am-loop-builder` skill says not to write a second mechanism. Worker names must match `^[a-z]+$`.
- **The Workers card is data in core.** `agent-manager/python/dashboard/routes/pipeline_ops_workers.py` has a `WORKERS` tuple, and `static/js/pipeline-ops-workers-panel.js` has a label and an order list. The atomizer was added as just a name there.
- **That card reads a different ledger.** It reads `~/.local/state/pipeline-ops/<name>-ledger.jsonl`, in worker-kit row format. The manager writes its own format elsewhere.
- **There is no deadline trigger.** `trigger.js` wakes only when a watched file's signature changes. "Unclaimed for 30 minutes" is the absence of a change, so no file event fires.
- **`DESIGN.md` conflicts with the skill.** `DESIGN.md` says the code lives in feature-forge. The skill says script workers live in pipeline-ops.

7d is too big for one task: it spans three repos plus a live-config step. I propose splitting it.

---

**Q1 - Home (the open owner decision):** Where do the trigger, the drain and the tick wrapper live?
-> `agent-manager-pipeline-ops`, as worker `featuremanager`, with `bin/featuremanager-trigger.js` and `bin/featuremanager-tick.js` built on `trigger.js` and `worker-kit.js`. The Python decision logic stays in `feature-forge`. This changes the `DESIGN.md` line "code lives in this repo". A second Node mechanism inside feature-forge would duplicate `trigger.js`, and Feature Forge has no Node tooling.

**Q2 - Python entry point:** How does the Node tick call the manager?
-> `feature-forge` gets a CLI, `python -m server.core.manager --tick`. It prints one JSON line (the existing `tick()` result) and exits 0. It also gets a `watch_paths()` function that lists the files the manager reads. The Node tick runs it as a child process with `.venv/bin/python`, and the path is overridable with `FEATUREMANAGER_PYTHON`.

**Q3 - Ledger:** Which ledger does the card read?
-> The tick wrapper mirrors each `handled` result into the worker-kit ledger (`featuremanager-ledger.jsonl`): `key` is `slug/item/task`, `outcome` and `reason` come from the manager, and `mode` is passed through. The manager's own `.manager-ledger.jsonl` stays the write-ahead source of truth. Only result rows count as decisions on the card.

**Q4 - Dry-run rule:** Does the "five dry-run decisions per item" settle rule apply?
-> No. `manager.py` already dedups the same decision for 24 hours, so five repeats never happen. The 15-minute dry run is judged on distinct decisions in the ledger, and the owner flips it to `on` by editing `~/.config/pipeline-ops/featuremanager.env` and restarting the drain.

**Q5 - What wakes it (triggers, not polls):** Which events trigger a tick?
-> Two kinds.
- **File changes.** `featuremanagerPaths()` in `trigger.js` lists each feature's `checklist.md`, the queue folders of each filed target repo's pipeline dir (`adhoc`, `pending`, `blocked`, `needs-clarification`, `done`), and the `.manager-disabled` marker.
- **Deadlines.** The Python side exposes `next_due()`, the earliest future time any filed task crosses the 30-minute unclaimed, 120-minute stalled or deadline thresholds. The existing once-a-minute watchdog trigger compares the clock to it and wakes the drain once when it passes. No new timer or sleep loop is added. The idle cost is one stat plus one number compare per watchdog call.

**Q6 - Card:** What does the Workers card need?
-> A core piece in `agent-manager`: add `featuremanager` to `WORKERS` in `pipeline_ops_workers.py`, plus a label and a place in `poWorkerOrder` in `pipeline-ops-workers-panel.js`. Add tests, a codebase-map row, and a browser check on a scratch dashboard. No new route.

**Q7 - Live registration and dry run:** Who adds the worker to `plugins.json` and runs the 15-minute dry run?
-> It is not a worker task, because `plugins.json` is host-local and gitignored. The last piece is an operator step, marked manual. The steps are: back up `plugins.json`, add `bin/featuremanager-trigger.js` to the pipeline-ops entry's `watchdogScripts`, write `featuremanager.env` with `FEATUREMANAGER_MODE=dry-run`, fast-forward the pipeline-ops checkout, then watch the card for 15 minutes. The owner flips it to `on`. I would not use `POST /api/plugins/add`.

**Q8 - Split:** How is 7d split into tasks?
-> Four pieces, each inside one repo:
- **7d1 (`feature-forge`):** the `--tick` CLI, `watch_paths()`, `next_due()` and tests.
- **7d2 (`agent-manager-pipeline-ops`):** `featuremanagerPaths` including the deadline signature, `bin/featuremanager-trigger.js`, `bin/featuremanager-tick.js`, the ledger mirroring, `docs/running-the-featuremanager.md`, and a smoke test as a child process with `HOME=<temp>`.
- **7d3 (`agent-manager`):** the card entry, tests and codebase-map row.
- **7d4 (manual operator step):** registration, the dry run and the flip to `on`.

Order is 7d1, then 7d2, then 7d3, then 7d4. 7d1 and 7d3 do not depend on each other, but the card has nothing to show until 7d2 lands.

Say "yes" to accept all eight, or give the numbers you want changed.

---

**Owner:**

[Owner decision relayed by the Claude Code session on 2026-11-19, not a bot answer] Yes to all eight. The home for 7d is agent-manager-pipeline-ops, as you assumed, so the owner decision gate is cleared. Propose the checklist change that splits 7d into 7d1 to 7d4 with the gate removed. Keep every reason and text under the review limits (reason under 100 characters, no comment marks).

---

**Grill:**

Here is the change. It drops the gated 7d, which has no task, filed or merged tag, and adds the four pieces to FF-7. Each piece is confined to one repo, and 7d4 is an operator step.

Triggers instead of timers: wake-ups come from file-signature changes plus one deadline compare in the existing once-a-minute watchdog call. No new timer or sleep loop is added.

```checklist-diff
{"ops": [
  {"op": "remove", "id": "FF-7", "piece": "7d"},
  {"op": "change", "id": "FF-7", "title": "Manager loop (15 min dry run) and repo-creation button", "body": "Wire the finished manager decisions into a trigger plus drain worker named featuremanager. Home is agent-manager-pipeline-ops (owner decision 2026-11-19). Python decision logic stays in feature-forge.",
   "pieces": [
    {"title": "7d1 Manager CLI tick, watch paths and next due time (feature-forge)", "body": "Repo feature-forge. In server/core/manager.py add three things. First, a command line entry, python -m server.core.manager --tick, which runs tick() once and prints exactly one JSON line then exits 0 even on error (put the error in the JSON). Second, watch_paths(root=None), returning the list of files the manager reads: each feature's checklist.md, the queue folders adhoc, pending, blocked, needs-clarification and done of each filed target repo's pipelineDir, and the .manager-disabled marker. Third, next_due(root=None, now=None), returning the earliest future ISO time at which any filed unticked task crosses UNCLAIMED_MIN, STALLED_MIN or the deadline from deadline_minutes(), or null when none. All three are pure reads and write nothing. Add tests in tests/test_manager.py for the CLI line, the path list and next_due, including the null case and a task already past its threshold. Acceptance is the new tests passing with the existing test_manager.py tests unchanged. Trigger note. Nothing here polls; the CLI is called by the watchdog-started drain on a file change, and next_due gives the deadline trigger its single wake time."},
    {"title": "7d2 featuremanager trigger, drain and ledger mirror (agent-manager-pipeline-ops)", "body": "Repo agent-manager-pipeline-ops. Build worker featuremanager on src/trigger.js and src/worker-kit.js, copying the shape of bin/merger-trigger.js and bin/merger-tick.js. Add featuremanagerPaths(env) to src/trigger.js and export it. It runs the feature-forge CLI python -m server.core.manager --watch-paths if present, otherwise reads the path list the tick last stored, and adds the deadline signature, which is the next_due time bucketed so the signature changes once when it passes. Add bin/featuremanager-trigger.js and bin/featuremanager-tick.js. The tick runs python -m server.core.manager --tick in the feature-forge checkout using .venv/bin/python, overridable by FEATUREMANAGER_PYTHON, and passes FEATUREFORGE_MANAGER_MODE from FEATUREMANAGER_MODE (dry-run default, read from ~/.config/pipeline-ops/featuremanager.env). Each handled result is mirrored into the worker-kit ledger featuremanager-ledger.jsonl with key slug/item/task, the outcome, the reason and the mode, as an intent row then a result row. The off marker featuremanager-disabled is read first. The five-decision dry-run settle rule is not used because manager.py dedups for 24 hours. Add docs/running-the-featuremanager.md with the env file, the restart-after-mode-change rule and the go-live steps. Tests use a temp HOME and temp ledger, never the real state directory; smoke-test the bins only as child processes. Acceptance is the new tests passing, the existing suite unchanged, and a child-process run printing one line. Trigger note. Wakes are file-signature changes plus one deadline compare in the existing watchdog call; no timer, no sleep loop, idle cost is one stat set and one number compare."},
    {"title": "7d3 Workers tab card for featuremanager (agent-manager)", "body": "Repo agent-manager. In python/dashboard/routes/pipeline_ops_workers.py add featuremanager to the WORKERS tuple. In python/dashboard/static/js/pipeline-ops-workers-panel.js add a label and a does line for it and put it in poWorkerOrder after atomizer. Follow the atomizer entry exactly; no new route. Extend pipeline-ops-workers-panel.test.js and the route test with a case for the new name, including the hidden card when configured is false. Add a row to docs/agents/codebase-map.md. Check the card in a real browser on a scratch dashboard with a fixture ledger, trigger state and marker in a temp HOME, never the live dashboard. Acceptance is the new tests passing, the existing tests unchanged and a screenshot reviewed. Trigger note. The card reads files once per Workers tab refresh and adds no timer."},
    {"title": "7d4 Register, 15 minute dry run and flip (operator step, manual)", "body": "Manual operator step, not a worker task, because plugins.json is host-local and gitignored. After 7d1, 7d2 and 7d3 are merged. Copy plugins.json to a dated backup and add bin/featuremanager-trigger.js to the watchdogScripts of the agent-manager-pipeline-ops entry, then check the file still parses. Do not use POST /api/plugins/add. Fast-forward the live checkouts of agent-manager-pipeline-ops and feature-forge with a clean tree first. Write ~/.config/pipeline-ops/featuremanager.env with FEATUREMANAGER_MODE=dry-run. Wait for the first watchdog tick, confirm one drain process and lingering true in featuremanager-trigger.json. Watch the card for 15 minutes at most and read the ledger decisions against the real queue. The owner then flips the mode to on and the drain is restarted by exact pid. Trigger note. No timer is added; the existing watchdog call is the only clock."}
   ]}
]}
```

---

**Owner:**

[Relayed owner session] Do not apply this yet. The review refused your item op because it altered merged piece 7c, and the only op left is a drop of 7d, which would tick FF-7 with nothing built. Resend as separate ops: append each new piece (the four 7d pieces, using the next free labels) with its text, leave 7c and every merged piece untouched, and drop 7d only after the appends in the same diff. FF-7 must stay unticked while the new pieces are open.

---

**Grill:**

Here is the diff as separate ops. Each `change` carries only the item id and one new piece. It sends no title or body, so the existing pieces, 7c included, are not touched. The drop of 7d comes last, so FF-7 stays unticked while the four new pieces are open. The pieces get the next free labels, so their titles carry no numbers, and their bodies refer to each other by order.

```checklist-diff
{"ops": [
  {"op": "change", "id": "FF-7", "pieces": [
    {"title": "Manager CLI tick, watch paths and next due time (feature-forge)", "body": "Repo feature-forge. First of the four manager wiring pieces. In server/core/manager.py add three things. First, a command line entry, python -m server.core.manager --tick, which runs tick() once and prints exactly one JSON line then exits 0 even on error (put the error in the JSON). The same entry accepts --watch-paths, which prints one JSON line holding the list from watch_paths, and --next-due, which prints one JSON line holding the value from next_due. Second, watch_paths(root=None), returning the list of files the manager reads. These are each feature's checklist.md, the queue folders adhoc, pending, blocked, needs-clarification and done of each filed target repo's pipelineDir, and the .manager-disabled marker. Third, next_due(root=None, now=None), returning the earliest future ISO time at which any filed unticked task crosses UNCLAIMED_MIN, STALLED_MIN or the deadline from deadline_minutes(), or null when none. All three are pure reads and write nothing. Add tests in tests/test_manager.py for the three command line outputs, the path list and next_due, including the null case and a task already past its threshold. Acceptance is the new tests passing with the existing test_manager.py tests unchanged. Trigger note. Nothing here polls. The CLI is called by the watchdog-started drain on a file change, and next_due gives the deadline trigger its single wake time."}
  ]},
  {"op": "change", "id": "FF-7", "pieces": [
    {"title": "featuremanager trigger, drain and ledger mirror (agent-manager-pipeline-ops)", "body": "Repo agent-manager-pipeline-ops. Second of the four manager wiring pieces; it needs the feature-forge CLI piece merged first. Build worker featuremanager on src/trigger.js and src/worker-kit.js, copying the shape of bin/merger-trigger.js and bin/merger-tick.js. Add featuremanagerPaths(env) to src/trigger.js and export it. It runs python -m server.core.manager --watch-paths in the feature-forge checkout and adds the deadline signature, which is the --next-due time bucketed so the signature changes once when it passes. Add bin/featuremanager-trigger.js and bin/featuremanager-tick.js. The tick runs python -m server.core.manager --tick in the feature-forge checkout using .venv/bin/python, overridable by FEATUREMANAGER_PYTHON, and passes FEATUREFORGE_MANAGER_MODE from FEATUREMANAGER_MODE (dry-run default, read from ~/.config/pipeline-ops/featuremanager.env). Each handled result is mirrored into the worker-kit ledger featuremanager-ledger.jsonl with key slug/item/task, the outcome, the reason and the mode, as an intent row then a result row. The off marker featuremanager-disabled is read first. The five-decision dry-run settle rule is not used because manager.py dedups for 24 hours. Add docs/running-the-featuremanager.md with the env file, the restart-after-mode-change rule and the go-live steps. Tests use a temp HOME and temp ledger, never the real state directory; smoke-test the bins only as child processes. Acceptance is the new tests passing, the existing suite unchanged, and a child-process run printing one line. Trigger note. Wakes are file-signature changes plus one deadline compare in the existing watchdog call. There is no timer and no sleep loop, and the idle cost is one stat set and one number compare."}
  ]},
  {"op": "change", "id": "FF-7", "pieces": [
    {"title": "Workers tab card for featuremanager (agent-manager)", "body": "Repo agent-manager. Third of the four manager wiring pieces. In python/dashboard/routes/pipeline_ops_workers.py add featuremanager to the WORKERS tuple. In python/dashboard/static/js/pipeline-ops-workers-panel.js add a label and a does line for it and put it in poWorkerOrder after atomizer. Follow the atomizer entry exactly; no new route. Extend pipeline-ops-workers-panel.test.js and the route test with a case for the new name, including the hidden card when configured is false. Add a row to docs/agents/codebase-map.md. Check the card in a real browser on a scratch dashboard with a fixture ledger, trigger state and marker in a temp HOME, never the live dashboard. Acceptance is the new tests passing, the existing tests unchanged and a screenshot reviewed. Trigger note. The card reads files once per Workers tab refresh and adds no timer."}
  ]},
  {"op": "change", "id": "FF-7", "pieces": [
    {"title": "Register, 15 minute dry run and flip (operator step, manual)", "body": "Manual operator step, not a worker task, because plugins.json is host-local and gitignored. Do it after the three pieces before this one are merged. Copy plugins.json to a dated backup and add bin/featuremanager-trigger.js to the watchdogScripts of the agent-manager-pipeline-ops entry, then check the file still parses. Do not use POST /api/plugins/add. Fast-forward the live checkouts of agent-manager-pipeline-ops and feature-forge with a clean tree first. Write ~/.config/pipeline-ops/featuremanager.env with FEATUREMANAGER_MODE=dry-run. Wait for the first watchdog tick, confirm one drain process and lingering true in featuremanager-trigger.json. Watch the card for 15 minutes at most and read the ledger decisions against the real queue. The owner then flips the mode to on and the drain is restarted by exact pid. Trigger note. No timer is added; the existing watchdog call is the only clock."}
  ]},
  {"op": "remove", "id": "FF-7", "piece": "7d"}
]}
```
