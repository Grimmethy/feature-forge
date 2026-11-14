"""The dashboard tab script (ui/featureforge-tab.js).

The script runs inside agent-manager's dashboard, which this repo does not carry, so the behavioural cases execute the real script under node's `vm`
against stubs (a fake #main, fetch, location and the dashboard's escapeAttr). Without node the behavioural cases are skipped.
Run: python -m pytest tests/test_tab_script.py
"""
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPT = os.path.join(ROOT, "ui", "featureforge-tab.js")
NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const sc = JSON.parse(process.env.FF_SCENARIO);
const calls = [];
let renderer = null;
const main = { innerHTML: '', querySelector: () => null };
const ctx = {
  document: { getElementById: () => main },
  location: { hostname: sc.hostname },
  escapeAttr: s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  registerPluginTabRenderer: (key, fn) => { calls.push('register ' + key); renderer = fn; },
  URL,
  fetch: async (url, opts) => {
    calls.push(((opts && opts.method) || 'GET') + ' ' + url);
    if (url === '/api/plugins') {
      if (sc.pluginsMode === 'throw') throw new Error('network down');
      if (sc.pluginsMode === 'http500') return { ok: false, status: 500, json: async () => ({}) };
      if (sc.pluginsMode === 'badjson') return { ok: true, status: 200, json: async () => { throw new SyntaxError('bad json'); } };
      return { ok: true, status: 200, json: async () => ({ plugins: sc.plugins }) };
    }
    if (sc.ensureOk === false) return { ok: false, status: 500, json: async () => ({ error: sc.ensureError }) };
    return { ok: true, status: 200, json: async () => ({ healthy: true }) };
  },
};
vm.runInNewContext(fs.readFileSync(process.env.FF_SCRIPT, 'utf8'), ctx);
renderer().then(() => console.log(JSON.stringify({ calls, html: main.innerHTML })));
"""


def run_tab(plugins=None, hostname="grimm.local", **extra):
    scenario = dict(hostname=hostname, plugins=plugins if plugins is not None else [], **extra)
    env = dict(os.environ, FF_SCENARIO=json.dumps(scenario), FF_SCRIPT=SCRIPT)
    out = subprocess.run([NODE, "-e", HARNESS], env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    m = re.search(r'src="([^"]*)"', result["html"])
    result["src"] = m.group(1) if m else None
    return result


ENSURE = "POST /api/plugins/featureforge/ensure-started"
LOCAL_SRC = "http://grimm.local:7466/"


class TabScriptSourceTest(unittest.TestCase):
    def setUp(self):
        with open(SCRIPT, encoding="utf-8") as f:
            self.src = f.read()

    def test_registers_under_the_plugin_key(self):
        self.assertIn("registerPluginTabRenderer('featureforge',", self.src)

    def test_every_interpolated_value_goes_through_the_escaper(self):
        self.assertEqual(len(re.findall(r"escapeAttr\(", self.src)), 2)


@unittest.skipUnless(NODE, "node is not installed")
class TabScriptBehaviourTest(unittest.TestCase):
    def assertLocal(self, r):
        self.assertEqual(r["calls"].count(ENSURE), 1)
        self.assertEqual(r["src"], LOCAL_SRC)

    def test_no_entry_keeps_the_local_behaviour(self):
        self.assertLocal(run_tab(plugins=[]))

    def test_entry_without_a_url_keeps_the_local_behaviour(self):
        self.assertLocal(run_tab(plugins=[{"name": "featureforge"}]))

    def test_loopback_urls_keep_the_local_behaviour(self):
        for url in ("http://localhost:7466", "http://127.0.0.1:7466", "http://[::1]:7466"):
            with self.subTest(url=url):
                self.assertLocal(run_tab(plugins=[{"name": "featureforge", "url": url}]))

    def test_unusable_urls_keep_the_local_behaviour(self):
        for url in ("not a url", "javascript:alert(1)", "ftp://100.80.1.14:7466"):
            with self.subTest(url=url):
                self.assertLocal(run_tab(plugins=[{"name": "featureforge", "url": url}]))

    def test_a_failing_plugins_call_keeps_the_local_behaviour(self):
        for mode in ("throw", "http500", "badjson"):
            with self.subTest(mode=mode):
                self.assertLocal(run_tab(pluginsMode=mode))

    def test_a_remote_entry_is_embedded_without_starting_anything_locally(self):
        r = run_tab(plugins=[{"name": "featureforge", "url": "http://100.80.1.14:7466"}])
        self.assertNotIn(ENSURE, r["calls"])
        self.assertEqual(r["src"], "http://100.80.1.14:7466/")

    def test_a_remote_url_ends_in_exactly_one_slash_and_keeps_a_path_prefix(self):
        for url, want in (("http://100.80.1.14:7466/", "http://100.80.1.14:7466/"), ("http://wok:7466/ff//", "http://wok:7466/ff/")):
            with self.subTest(url=url):
                r = run_tab(plugins=[{"name": "featureforge", "url": url}])
                self.assertEqual(r["src"], want)

    def test_other_plugins_urls_are_ignored(self):
        self.assertLocal(run_tab(plugins=[{"name": "mailroom", "url": "http://100.96.112.78:7464"}]))

    def test_a_hostile_remote_url_never_puts_a_raw_quote_or_tag_in_the_markup(self):
        r = run_tab(plugins=[{"name": "featureforge", "url": 'http://100.80.1.14:7466/"><script>alert(1)</script>'}])
        self.assertNotIn("<script", r["html"])
        self.assertNotIn('"><', r["html"].split("<iframe", 1)[1].split("</iframe>", 1)[0].split(' style=')[0])
        self.assertTrue(r["src"].startswith("http://100.80.1.14:7466/"))

    def test_the_local_failure_message_is_kept_and_escaped(self):
        r = run_tab(plugins=[], ensureOk=False, ensureError="<b>boom</b>")
        self.assertIn("Feature Forge server did not start", r["html"])
        self.assertIn("&lt;b&gt;boom&lt;/b&gt;", r["html"])
        self.assertNotIn("<iframe", r["html"])


if __name__ == "__main__":
    unittest.main()
