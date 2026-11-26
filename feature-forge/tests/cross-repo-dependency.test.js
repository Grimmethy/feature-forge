const test = require('node:test');
const assert = require('node:assert');

// Mock getTaskById to simulate cross-repo task lookup
// In production, this would query the shared task database across all repos
function createMockGetTaskById(taskMap) {
  return function getTaskById(taskId) {
    return taskMap[taskId] || null;
  };
}

// Stub isClaimable that accepts a lookup function for testability
function isClaimable(task, { lookup = () => null } = {}) {
  // If no dependsOn field or it's empty, task is claimable
  if (!task.dependsOn || !Array.isArray(task.dependsOn) || task.dependsOn.length === 0) {
    return { claimable: true };
  }

  // Check each dependency across all repos
  for (const taskId of task.dependsOn) {
    const prerequisite = lookup(taskId);

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

// Test fixtures
const taskA = {
  id: 'task-uuid-a',
  title: 'Task A',
  dependsOn: ['task-uuid-b'],
  status: 'pending'
};

const taskB = {
  id: 'task-uuid-b',
  title: 'Task B',
  status: 'pending'
};

const taskBCompleted = {
  id: 'task-uuid-b',
  title: 'Task B',
  status: 'done'
};

const taskC = {
  id: 'task-uuid-c',
  title: 'Task C',
  status: 'pending'
};

const taskD = {
  id: 'task-uuid-d',
  title: 'Task D',
  status: 'pending'
};

// Test Group 1: Cross-repo prereq blocks
test('task with prereq in another repo is not claimable until done', () => {
  const taskMap = {
    'task-uuid-b': taskB
  };
  const lookup = createMockGetTaskById(taskMap);

  const result = isClaimable(taskA, { lookup });

  assert.strictEqual(result.claimable, false);
  assert.ok(result.reason.includes('not yet resolved'));
  assert.ok(result.reason.includes('pending'));
});

// Test Group 2: Cross-repo prereq unblocks
test('task becomes claimable after prereq completes', () => {
  const taskMap = {
    'task-uuid-b': taskBCompleted
  };
  const lookup = createMockGetTaskById(taskMap);

  const result = isClaimable(taskA, { lookup });

  assert.strictEqual(result.claimable, true);
  assert.strictEqual(result.reason, undefined);
});

// Test Group 3: Missing prereq fails clearly
test('missing prereq blocks with clear reason', () => {
  const taskMap = {}; // Empty map - task B doesn't exist
  const lookup = createMockGetTaskById(taskMap);

  const result = isClaimable(taskA, { lookup });

  assert.strictEqual(result.claimable, false);
  assert.ok(result.reason.includes('not found'));
  assert.ok(result.reason.includes('task-uuid-b'));
});

// Test Group 4: Same-repo dependencies still work
test('same-repo dependencies still work', () => {
  // Simulate both tasks in the same repo
  const taskMap = {
    'task-uuid-d': taskD
  };
  const lookup = createMockGetTaskById(taskMap);

  const taskWithSameRepoDep = {
    id: 'task-uuid-c',
    title: 'Task C',
    dependsOn: ['task-uuid-d'],
    status: 'pending'
  };

  // Test blocking case
  const blockedResult = isClaimable(taskWithSameRepoDep, { lookup });
  assert.strictEqual(blockedResult.claimable, false);
  assert.ok(blockedResult.reason.includes('not yet resolved'));

  // Test unblocking case
  const taskDCompleted = { ...taskD, status: 'done' };
  const taskMapCompleted = {
    'task-uuid-d': taskDCompleted
  };
  const lookupCompleted = createMockGetTaskById(taskMapCompleted);

  const unblockedResult = isClaimable(taskWithSameRepoDep, { lookup: lookupCompleted });
  assert.strictEqual(unblockedResult.claimable, true);
});
