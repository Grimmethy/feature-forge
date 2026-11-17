#!/usr/bin/env node
// One-shot diagnostic for 'plan-pass degenerate' draft-attempt failures on worker-3090 (ornith:35b).
// Usage: node scripts/diagnose-plan-pass-degenerate.js <store-path> [--jsonl]
// Reads the draft-attempt store only and prints to stdout. No model calls, no timers.
'use strict';

const fs = require('node:fs');

const FAILURE_MODE = 'plan-pass degenerate';
const WORKER = 'worker-3090';
const MODEL = 'ornith:35b';

function firstPresent(rec, names) {
  for (const n of names) {
    if (rec[n] !== undefined && rec[n] !== null && rec[n] !== '') return rec[n];
  }
  return null;
}

function toNumber(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function toThinking(v) {
  if (v === true || v === 'true') return 'true';
  if (v === false || v === 'false') return 'false';
  return 'unknown';
}

function readRecords(text) {
  const trimmed = text.trim();
  if (!trimmed) return { records: [], badLines: 0 };
  if (trimmed.charAt(0) === '[') return { records: JSON.parse(trimmed), badLines: 0 };
  const records = [];
  let badLines = 0;
  for (const line of trimmed.split('\n')) {
    if (!line.trim()) continue;
    try {
      records.push(JSON.parse(line));
    } catch (e) {
      badLines += 1;
    }
  }
  return { records, badLines };
}

function isMatch(rec) {
  const mode = firstPresent(rec, ['failure_mode', 'failureMode', 'failure']);
  const worker = firstPresent(rec, ['worker_id', 'workerId', 'worker']);
  const model = firstPresent(rec, ['model']);
  return typeof mode === 'string' && mode.indexOf(FAILURE_MODE) !== -1 &&
    worker === WORKER && model === MODEL;
}

function extract(rec) {
  return {
    task_id: firstPresent(rec, ['task_id', 'taskId']),
    timestamp: firstPresent(rec, ['timestamp', 'at']),
    lane_id: firstPresent(rec, ['lane_id', 'laneId', 'lane']),
    model: firstPresent(rec, ['model']),
    output_length: toNumber(firstPresent(rec, ['output_length', 'outputLength'])),
    output_cap: toNumber(firstPresent(rec, ['output_cap', 'outputCap'])),
    thinking_mode: toThinking(firstPresent(rec, ['thinking_mode', 'thinkingMode'])),
    prompt_size: toNumber(firstPresent(rec, ['plan_prompt_size', 'prompt_size', 'promptSize'])),
    is_biggest_lane: firstPresent(rec, ['is_biggest_lane', 'isBiggestLane']),
  };
}

function median(sorted) {
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function summarise(rows) {
  const withCap = rows.filter((r) => r.output_cap !== null && r.output_length !== null);
  const over = withCap.filter((r) => r.output_length > 0.9 * r.output_cap);
  const missingCap = rows.filter((r) => r.output_cap === null).length;
  const thinking = { true: 0, false: 0, unknown: 0 };
  for (const r of rows) thinking[r.thinking_mode] += 1;
  const sizes = rows.map((r) => r.prompt_size).filter((v) => v !== null).sort((a, b) => a - b);
  return {
    withCap: withCap.length,
    over: over.length,
    missingCap,
    thinking,
    sizes,
  };
}

function main() {
  const args = process.argv.slice(2);
  const jsonl = args.indexOf('--jsonl') !== -1;
  const storePath = args.filter((a) => a !== '--jsonl')[0];
  if (!storePath) {
    process.stderr.write('usage: node scripts/diagnose-plan-pass-degenerate.js <store-path> [--jsonl]\n');
    process.exit(2);
  }

  let text;
  try {
    text = fs.readFileSync(storePath, 'utf8');
  } catch (e) {
    process.stderr.write('cannot read store: ' + storePath + ' (' + e.message + ')\n');
    process.exit(1);
  }

  let parsed;
  try {
    parsed = readRecords(text);
  } catch (e) {
    process.stderr.write('store is neither a JSON array nor JSON lines: ' + e.message + '\n');
    process.exit(1);
  }

  const rows = parsed.records.filter(isMatch).map(extract);
  const s = summarise(rows);
  const pct = s.withCap ? (s.over / s.withCap * 100).toFixed(1) + '%' : 'n/a';
  const min = s.sizes.length ? s.sizes[0] : 'n/a';
  const max = s.sizes.length ? s.sizes[s.sizes.length - 1] : 'n/a';
  const med = median(s.sizes);

  const out = [];
  out.push('store: ' + storePath);
  out.push('records read: ' + parsed.records.length + ' (unparseable lines skipped: ' + parsed.badLines + ')');
  out.push('matches (' + FAILURE_MODE + ' / ' + WORKER + ' / ' + MODEL + '): ' + rows.length);
  out.push('output_length > 90% of output_cap: ' + s.over + ' of ' + s.withCap + ' (' + pct + ')');
  out.push('records missing output_cap: ' + s.missingCap);
  out.push('thinking_mode: true=' + s.thinking.true + ' false=' + s.thinking.false + ' unknown=' + s.thinking.unknown);
  out.push('plan_prompt_size min/median/max: ' + min + ' / ' + (med === null ? 'n/a' : med) + ' / ' + max);
  out.push('per-failure:');
  for (const r of rows) {
    out.push('  ' + r.timestamp + ' ' + r.task_id + ' output ' + r.output_length + '/' + r.output_cap +
      ' thinking=' + r.thinking_mode + ' prompt=' + r.prompt_size);
  }
  process.stdout.write(out.join('\n') + '\n');

  if (jsonl) {
    for (const r of rows) {
      process.stdout.write(JSON.stringify({
        lane_id: r.lane_id,
        model: r.model,
        task_id: r.task_id,
        output_length: r.output_length,
        prompt_size: r.prompt_size,
        thinking_mode: r.thinking_mode === 'unknown' ? null : r.thinking_mode === 'true',
        is_biggest_lane: r.is_biggest_lane,
      }) + '\n');
    }
  }
}

main();
