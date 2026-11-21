"""Every inline <script> block in an HTML page must parse.

A single syntax error in an inline script kills the whole page, so this extracts each inline block (no src=), writes it to a temp file
(.mjs for type=module, .js otherwise) and runs `node --check` on it. Without node the tests are skipped.
Run: python -m unittest tests.test_inline_scripts_parse
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
INDEX_HTML = os.path.join(ROOT, "web", "index.html")
NODE = shutil.which("node")
SKIP_REASON = "node not found on PATH; inline script syntax NOT checked"
JS_TYPES = {"", "text/javascript", "application/javascript", "module"}


class _ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.blocks = []  # (source, is_module) for inline JS blocks
        self.skipped_nonjs = 0
        self.skipped_external = 0
        self._attrs = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._attrs = dict((k.lower(), v) for k, v in attrs)
            self._buf = []

    def handle_data(self, data):
        if self._attrs is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or self._attrs is None:
            return
        attrs, self._attrs = self._attrs, None
        stype = (attrs.get("type") or "").strip().lower()
        if "src" in attrs:
            self.skipped_external += 1
        elif stype not in JS_TYPES:
            self.skipped_nonjs += 1
        else:
            self.blocks.append(("".join(self._buf), stype == "module"))


def extract_inline_scripts(html_path):
    """Return (blocks, skipped_nonjs, skipped_external); blocks is a list of (index, source, is_module)."""
    with open(html_path, encoding="utf-8") as f:
        text = f.read()
    parser = _ScriptCollector()
    parser.feed(text)
    parser.close()
    blocks = [(i, src, mod) for i, (src, mod) in enumerate(parser.blocks)]
    return blocks, parser.skipped_nonjs, parser.skipped_external


def check_inline_scripts(html_path):
    """Run `node --check` on every inline JS block. Returns a dict with found, failures [(index, stderr)], skipped_nonjs, skipped_external."""
    blocks, nonjs, external = extract_inline_scripts(html_path)
    print("skipped non-JS blocks: %d, external blocks: %d" % (nonjs, external))
    total = len(blocks) + nonjs + external
    assert total >= 2, "expected at least 2 <script> blocks in %s, found %d" % (html_path, total)
    assert blocks, "no inline JS script blocks to check in %s" % html_path
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, source, is_module in blocks:
            path = os.path.join(tmp, "block_%d%s" % (index, ".mjs" if is_module else ".js"))
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            proc = subprocess.run([NODE, "--check", path], capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                failures.append((index, proc.stderr))
    return {"found": len(blocks), "failures": failures, "skipped_nonjs": nonjs, "skipped_external": external}


def format_failures(result):
    return "\n".join("inline script block %d failed node --check:\n%s" % (i, err) for i, err in result["failures"])


@unittest.skipUnless(NODE, SKIP_REASON)
class InlineScriptsParse(unittest.TestCase):
    def _write(self, body):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "page.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path

    def test_index_html_inline_scripts_parse(self):
        result = check_inline_scripts(INDEX_HTML)
        self.assertEqual(result["failures"], [], format_failures(result))

    def test_broken_second_block_is_detected(self):
        path = self._write(
            "<html><body>\n<script>var a = 1;</script>\n"
            "<script>function f( {\n var s = `abc\n</script>\n</body></html>\n"
        )
        result = check_inline_scripts(path)
        self.assertEqual([i for i, _ in result["failures"]], [1])
        self.assertTrue(result["failures"][0][1].strip())
        self.assertIn("block 1", format_failures(result))

    def test_broken_module_block_is_detected(self):
        path = self._write(
            "<html><body>\n<script>var a = 1;</script>\n"
            '<script type="module">import fs from "fs";\nexport const x = ;\n</script>\n'
            '<script type="application/json">{"not": js</script>\n'
            '<script src="x.js"></script>\n</body></html>\n'
        )
        result = check_inline_scripts(path)
        self.assertEqual([i for i, _ in result["failures"]], [1])
        self.assertEqual(result["skipped_nonjs"], 1)
        self.assertEqual(result["skipped_external"], 1)

    def test_valid_module_block_passes(self):
        path = self._write(
            "<script>var a = 1;</script>\n"
            '<script type="module">import fs from "fs";\nexport const x = fs ? 1 : 2;\n</script>\n'
        )
        result = check_inline_scripts(path)
        self.assertEqual(result["failures"], [], format_failures(result))


if __name__ == "__main__":
    unittest.main()
