/**
 * Cross-repo dependency resolution for claimable task evaluation.
 *
 * Provides isClaimable(task) which checks dependsOn prerequisites
 * across all known pipelines using the cross-repo lookup from
 * agent-manager. This replaces the previous local-only queue check.
 *
 * @param {object} task - The task to evaluate for claimability.
 * @returns {object} { claimable: boolean, reason?: string }
 */

const { getTaskById } = require('../../src/pipeline/lookup-across-repos');

/**
 * Check if a task is claimable by verifying all dependsOn prerequisites
 * are resolved across all pipelines.
 *
 * @param {object} task - Task object with optional dependsOn array.
 * @returns {object} Result with claimable boolean and optional reason.
 */
function isClaimable(task) {
  // If no dependsOn field or it's empty, task is claimable
  if (!task.dependsOn || !Array.isArray(task.dependsOn) || task.dependsOn.length === 0) {
    return { claimable: true };
  }

  // Check each dependency across all repos
  for (const taskId of task.dependsOn) {
    const prerequisite = getTaskById(taskId);

    // If prerequisite not found in any pipeline, task is not claimable
    if (!prerequisite) {
      return {
        claimable: false,
        reason: `dependency ${taskId} not found in any pipeline`
      };
    }

    // If prerequisite exists but is not completed/claimed, task is not claimable
    // Check common status fields that indicate completion
    const isResolved = prerequisite.status === 'done' ||
                       prerequisite.status === 'completed' ||
                       prerequisite.status === 'claimed' ||
                       prerequisite.leasedTo !== undefined;

    if (!isResolved) {
      return {
        claimable: false,
        reason: `dependency ${taskId} not yet resolved (status: ${prerequisite.status})`
      };
    }
  }

  // All dependencies resolved
  return { claimable: true };
}

module.exports = { isClaimable };
