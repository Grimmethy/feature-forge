(function (root) {
  // Buckets every feature into exactly one pill: a defined status, or Other.
  // All is always the sum of the pills, so the header count cannot drift.
  function featureCounts(features, statuses) {
    const counts = {};
    statuses.forEach(s => counts[s] = 0);
    counts.Other = 0;
    (features || []).forEach(f => {
      const s = f && f.status;
      if (typeof s === 'string' && statuses.includes(s)) counts[s]++;
      else counts.Other++;
    });
    counts.All = statuses.reduce((n, s) => n + counts[s], 0) + counts.Other;
    return counts;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { featureCounts };
  else root.featureCounts = featureCounts;
})(typeof window !== 'undefined' ? window : globalThis);
