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
