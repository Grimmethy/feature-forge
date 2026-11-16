// Stale-proposals state module.
// Assumption: a checklist-diff block is a fenced block tagged `checklist-diff`,
// the same marker used by PROPOSAL_RE in server/core/grill.py.

const PROPOSAL_RE = /```checklist-diff[ \t]*\n([\s\S]*?)\n[ \t]*```/;
const NOTICE = 'A newer proposal is in the chat: press Review proposal.';

let proposals = [];
let stale = false;

// Called for each assistant message. If it carries a checklist-diff block,
// the current proposals are cleared, the list is marked stale, and the
// notice text is returned. Otherwise state is unchanged and null is returned.
export function onAssistantMessage(text) {
  if (typeof text !== 'string') return null;
  if (!PROPOSAL_RE.test(text)) return null;
  proposals = [];
  stale = true;
  return NOTICE;
}

// Called when the Review proposal action supplies a new list.
export function onReviewProposal(newList) {
  proposals = [...newList];
  stale = false;
}

// Returns false while stale, true otherwise.
export function applyEnabled(state) {
  return !(state && state.stale === true);
}

// Read-only snapshot of the current state.
export function getState() {
  return { proposals: [...proposals], stale };
}
