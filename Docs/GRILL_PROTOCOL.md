# Feature grill protocol

Written so any model can run it. Goal: a shared understanding of one feature (or one checklist item), recorded close to verbatim in that node's `interview.md`.

1. **Read first.** Read the target repo's CONTEXT.md, CLAUDE.md, AGENTS.md, Docs/ and relevant code with the read-only tools. Never ask the owner for a fact you can look up. You may read; you must never write.
2. **First round, first question: the repo.** Recommend an existing repo or a new one (with a proposed name) and say why. The owner decides.
3. **Map a design tree.** The frontier is every decision whose prerequisites are settled. Ask the whole frontier in one round, numbered, each with a recommended answer worded so "yes" accepts it:

   ```
   Q1 - <title>: <question>
   -> <recommended answer>
   ```
4. Wait for answers, recompute the frontier, ask the next round. A question depending on one still open in this round belongs to a later round.
5. **Triggers, not polls.** For every task-sized unit ask: what event could trigger this instead of a timer? A poll needs a written justification.
6. **Scope down.** Prefer more, smaller, self-contained tasks. An item grill may end by proposing a split.
7. **Done when the frontier is empty.** Summarise and get the owner's confirmation before writing anything.

## Output (after confirmation)
- `interview.md`: answers close to verbatim.
- `plan.md`: the agreed design.
- `checklist.md`: proposed as a DIFF against the current list (new, changed, split items). Filed items are locked.

## Checklist output format (item and feature grills)

When the owner has confirmed the plan, end your reply with ONE fenced block tagged `checklist-diff` holding JSON, and nothing after it:

```checklist-diff
{"ops": [
  {"op": "add", "title": "...", "body": "what this step is for, in a few lines", "deps": ["FF-2"],
   "pieces": [{"title": "first task", "body": "full self-contained task text, files, acceptance"}, {"title": "second task", "body": "..."}]},
  {"op": "change", "id": "FF-3", "title": "...", "body": "...", "pieces": [{"title": "one more task", "body": "..."}]},
  {"op": "split", "id": "FF-4", "into": [{"title": "...", "body": "..."}, {"title": "...", "body": "..."}]},
  {"op": "remove", "id": "FF-5"},
  {"op": "remove", "id": "FF-4", "piece": "4c"},
  {"op": "supersede", "id": "FF-4", "piece": "4c", "reason": "done by another step"}
]}
```

Rules for the block:
- A step is a heading for the owner; the TASKS are its `pieces`. Any step that needs more than one task gets `pieces`, one per task, in the order they will be built (labelled 4a, 4b... for you). Each piece's `body` is the full task text a worker will see: it must stand alone. A step that is a single task may have no pieces and put its task text in `body`. `change` with `pieces` appends new pieces; it never touches existing ones.
- Prefer more, smaller tasks. Each task text must stand alone: a worker sees only its own repo, so name the files, the tests and the acceptance check in the body.
- Filed items (their line has a task or filed key) can only be reworded with `change`; never split or remove them.
- To close ONE piece nobody will build, use the piece ops, not a step `remove`: `remove` with `piece` drops it, `supersede` (with a one-line `reason`) ticks it as done by hand. A piece with a task, filed or merged tag is never dropped or superseded. When every piece left in the step is ticked, the step is ticked too.
- Every dependency must be an existing item; no cycles. A split's parts chain one after another unless you give `deps`.
- For every task answer "what event could trigger this instead of a timer?" and say so in the body; a poll or timer needs a written justification there.
- Propose nothing the owner has not confirmed. The page shows the block as a preview; the owner accepts each operation before anything is written.

