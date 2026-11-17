'use strict';
// Lane logger for 'plan-pass degenerate' events.
// Appends one JSON line per event to a caller-supplied path. Writes go through a
// lazily opened append stream, so the caller never awaits disk I/O. Write errors
// are reported to stderr and never thrown back into the lane.

const fs = require('node:fs');

const FIELDS = [
  'lane_id',
  'model',
  'task_id',
  'output_length',
  'prompt_size',
  'thinking_mode',
  'is_biggest_lane',
];

// logPath -> WriteStream
const streams = new Map();

function reportError(message) {
  try {
    process.stderr.write('lane-logger: ' + message + '\n');
  } catch (_) {
    // stderr unavailable; nothing else we can do without throwing into the lane.
  }
}

function getStream(logPath) {
  let stream = streams.get(logPath);
  if (stream) return stream;
  stream = fs.createWriteStream(logPath, { flags: 'a' });
  stream.on('error', (err) => {
    reportError('write error on ' + logPath + ': ' + (err && err.message));
    // Drop the broken stream so a later call can reopen the path.
    if (streams.get(logPath) === stream) streams.delete(logPath);
  });
  streams.set(logPath, stream);
  return stream;
}

function orNull(value) {
  return value === undefined ? null : value;
}

// Map caller fields onto the log contract. Exactly FIELDS keys are produced.
function toRow(event) {
  const e = event || {};
  const promptSize = e.plan_prompt_size !== undefined ? e.plan_prompt_size : e.prompt_size;
  return {
    lane_id: orNull(e.lane_id),
    model: orNull(e.model),
    task_id: orNull(e.task_id),
    output_length: orNull(e.output_length),
    prompt_size: orNull(promptSize),
    thinking_mode: Boolean(e.thinking_mode),
    is_biggest_lane: Boolean(e.is_biggest_lane),
  };
}

/**
 * Record one 'plan-pass degenerate' event as a JSON line.
 * @param {object} event  Caller-supplied fields (see FIELDS).
 * @param {string} logPath  Path of the JSON-lines file to append to.
 * Never throws; failures are written to stderr.
 */
function logPlanPassDegenerate(event, logPath) {
  try {
    if (typeof logPath !== 'string' || logPath === '') {
      reportError('no log path given; event dropped');
      return;
    }
    const line = JSON.stringify(toRow(event)) + '\n';
    getStream(logPath).write(line);
  } catch (err) {
    reportError('failed to log event: ' + (err && err.message));
  }
}

/** Flush and close all open streams. Intended for tests and shutdown. */
function close() {
  const pending = [];
  for (const stream of streams.values()) {
    pending.push(new Promise((resolve) => stream.end(resolve)));
  }
  streams.clear();
  return Promise.all(pending).then(() => undefined);
}

module.exports = { logPlanPassDegenerate, close, FIELDS };
