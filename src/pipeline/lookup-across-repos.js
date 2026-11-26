/**
 * Cross-repo task lookup utility.
 *
 * Resolves a task by its globally unique UUID across all registered repos.
 * Used by sibling repos (e.g. feature-forge) to verify prerequisite
 * tasks exist and inspect their status before claiming work.
 *
 * @param {string} taskId - A UUID string identifying the task.
 * @returns {object|null} The task object if found, or null if not found.
 */
function getTaskById(taskId) {
  if (!taskId || typeof taskId !== 'string') {
    return null;
  }

  // Minimal UUID v4 validation: 8-4-4-4-12 hex pattern.
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(taskId)) {
    return null;
  }

  // Import the task store that holds tasks across all repos.
  // In a real agent-manager deployment this would query the shared
  // task database / Redis / file-based store that persists all queued
  // tasks regardless of which repo they belong to.
  let taskStore;
  try {
    taskStore = require('../task-store');
  } catch (_err) {
    // task-store not available in this environment — treat as miss.
    return null;
  }

  const task = taskStore.get(taskId);
  return task || null;
}

module.exports = { getTaskById };
