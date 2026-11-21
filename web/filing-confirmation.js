(function (root) {
  // Pure helpers for the filing confirmation UI.
  // Driven by the POST /api/features/<slug>/checklist/<item_id>/file response
  // shape confirmed in server/app.py (the `checklist_file` route) and
  // server/core/filing.py (the `file_item` function that builds it).
  //
  // Successful response (server/app.py ~612):
  //   { id, task, premium, warnings, pieces }
  //   pieces: array of { piece, status, repo, task }
  //   status is one of 'filed', 'blocked', 'failed'
  //
  // Error response (server/app.py ~607, FilingError handler):
  //   { error: '<text>' }  with HTTP 400/404
  //
  // Piece count is pieces.length; 0 or absent counts as one task.
  // Filed task ids are the `task` values of entries whose `status` is 'filed',
  // in order.

  var STATUS_FILED = 'filed'; // server/app.py:610 checklist_file assigns status='filed' on success per piece

  function filedMessage(result) {
    if (!result || typeof result !== 'object') return '';
    var pieces = result.pieces || [];
    var filedIds = [];
    for (var i = 0; i < pieces.length; i++) {
      var p = pieces[i];
      if (p && p.status === STATUS_FILED && typeof p.task === 'string') {
        filedIds.push(p.task);
      }
    }
    var count = pieces.length || 1;
    if (filedIds.length === 0) {
      return 'Filed: ' + count + ' piece' + (count === 1 ? '' : 's') + ' queued';
    }
    return 'Filed: ' + count + ' piece' + (count === 1 ? '' : 's') + ' queued (' + filedIds.join(', ') + ')';
  }

  function badgeText(count) {
    if (typeof count !== 'number' || count < 1) return '';
    if (count === 1) return '1 piece queued';
    return count + ' pieces queued';
  }

  function errorMessage(result) {
    if (!result || typeof result !== 'object') return '';
    return result.error || '';
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { filedMessage: filedMessage, badgeText: badgeText, errorMessage: errorMessage };
  } else if (typeof globalThis !== 'undefined') {
    globalThis.filedMessage = filedMessage;
    globalThis.badgeText = badgeText;
    globalThis.errorMessage = errorMessage;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
