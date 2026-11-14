'use strict';

// Feature Forge dashboard tab (manifest-driven, see the plugin docs in agent-manager).
// Asks core to lazy-start the local server, then embeds it as an iframe. No timers and no polling: it runs once per tab open.
registerPluginTabRenderer('featureforge', async function renderFeatureForgeTab() {
  const main = document.getElementById('main');
  const url = 'http://' + location.hostname + ':7466/';
  if (main.querySelector('iframe.featureforge-frame') || main.querySelector('[data-featureforge-starting]')) return;
  main.innerHTML = '<div data-featureforge-starting style="padding:16px;color:var(--muted,#9a9aa2)">Starting the Feature Forge server...</div>';
  let ok = false, why = '';
  try {
    const r = await fetch('/api/plugins/featureforge/ensure-started', { method: 'POST' });
    const j = await r.json().catch(() => ({}));
    ok = r.ok && j.healthy !== false; why = r.ok ? 'the server did not become healthy in time' : (j.error || r.status);
  } catch (e) { why = String(e); }
  if (!ok) {
    main.innerHTML = `<div style="padding:16px"><strong>Feature Forge server did not start</strong><p>${escapeAttr(String(why))}</p><p>Start it by hand: <code>cd /media/model-cache/github/feature-forge &amp;&amp; ./run.sh</code></p></div>`;
    return;
  }
  main.innerHTML = `<iframe class="viz featureforge-frame" src="${escapeAttr(url)}" style="width:100%;height:calc(100vh - 120px);border:2px solid var(--border);border-radius:8px"></iframe>`;
});
