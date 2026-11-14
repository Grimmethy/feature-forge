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
  {"op": "add", "title": "...", "body": "full self-contained task text, files, acceptance", "deps": ["FF-2"]},
  {"op": "change", "id": "FF-3", "title": "...", "body": "..."},
  {"op": "split", "id": "FF-4", "into": [{"title": "...", "body": "..."}, {"title": "...", "body": "..."}]},
  {"op": "remove", "id": "FF-5"}
]}
```

Rules for the block:
- Prefer more, smaller tasks. Each task text must stand alone: a worker sees only its own repo, so name the files, the tests and the acceptance check in the body.
- Filed items (their line has a task or filed key) can only be reworded with `change`; never split or remove them.
- Every dependency must be an existing item; no cycles. A split's parts chain one after another unless you give `deps`.
- For every task answer "what event could trigger this instead of a timer?" and say so in the body; a poll or timer needs a written justification there.
- Propose nothing the owner has not confirmed. The page shows the block as a preview; the owner accepts each operation before anything is written.

