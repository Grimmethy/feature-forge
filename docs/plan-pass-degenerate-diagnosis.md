# plan-pass degenerate: diagnosis

## Scope and inputs

- Failure mode: `plan-pass degenerate`
- Worker: `worker-3090`
- Model: `ornith:35b`
- Draft-attempt fields: output_length, output_cap, thinking_mode (boolean), plan_prompt_size, task_id, timestamp
- Lane log format (JSON lines): lane_id, model, task_id, output_length, prompt_size, thinking_mode, is_biggest_lane

## Data source

No diagnostic data available.

Checks run for this document:

- `docs/` did not exist in the working tree (list_directory returned ENOENT).
- No diagnostic script was found. A search for "diagnos" returned only an unrelated cloud-lane note at `features/cloud-agent-pool/checklist.md:37`.
- No lane-log output exists. A search for `is_biggest_lane` returned no hits.
- HUB0049 1/3 (diagnostic script) and HUB0049 2/3 (lane logger) are not present in this checkout. The hub reports them as pending-merge, but they could not be verified on disk.

Because no data exists, no patterns, correlations, or thresholds are established. Result: no correlation established at this sample size (n=0).

## Patterns and correlations

No correlation established.

The only observed instance of this failure mode is a status note cited by the earlier read-only pass at `features/cloud-agent-pool/manager.md:93` (HUB0501-01 blocked on "plan pass degenerate" at attempt 5). That file is not present in this checkout, so the citation is unverified here.

## Recommendations

All recommendations below are blocked on HUB0049 1/3 and HUB0049 2/3. They are provisional and must not be acted on until data exists.

1. **Output budget for ornith:35b.** Review output_cap only after the observed output_length distribution is available. Any new value must come from that data.
2. **Prompt size limit.** Add an explicit plan_prompt_size limit only if a threshold is supported by logged failures. Until then, no limit is proposed.
3. **thinking_mode.** Compare the failure rate with thinking_mode true versus false once both are logged. Adjust only if the split is clear.
4. **is_biggest_lane.** Split failures by is_biggest_lane to test whether the biggest lane is associated with the failure mode.
5. **Local model changes.** Model-side settings are out of scope for this document. Any change that touches the local model must be routed through the project's local model client. That client, `src/local-client.js`, is not present in this checkout and must be confirmed first.

## Diagnostic script usage

Status: the diagnostic script is not present in this checkout. `<script-path>` is a placeholder.

Expected invocation, to be confirmed against the script's header once HUB0049 1/3 merges:

```
python3 <script-path> <lane-log.jsonl>
```

Input: a JSON-lines lane log using the lane log fields listed above.

Expected output: failure counts bucketed by plan_prompt_size, output_length as a percentage of output_cap, split by thinking_mode and is_biggest_lane.

The exact arguments are unknown until HUB0049 1/3 is available. Re-check its usage text before running it.
