"""Tests for tag support in server/core/store.py: _parse_tags, list_features tags, tag_matches and all_tags.
Plain unittest (standard library only)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import store


class TmpRootCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def make(self, title, tags_line=None):
        text = "build it" if tags_line is None else f"{tags_line}\nbuild it"
        return store.create_feature(title, text, self.root)


class ParseTagsTests(unittest.TestCase):
    def test_basic_line(self):
        self.assertEqual(store._parse_tags("# T\n\ntags: a, b\n"), ["a", "b"])

    def test_uppercase_key_and_values(self):
        self.assertEqual(store._parse_tags("TAGS: Alpha, Beta/Gamma"), ["alpha", "beta/gamma"])
        self.assertEqual(store._parse_tags("Tags: x"), ["x"])

    def test_whitespace_is_trimmed(self):
        self.assertEqual(store._parse_tags("  tags :   a  ,\t b   "), ["a", "b"])

    def test_empty_entries_are_dropped(self):
        self.assertEqual(store._parse_tags("tags: a,,b, ,"), ["a", "b"])
        self.assertEqual(store._parse_tags("tags:"), [])

    def test_duplicates_are_collapsed_in_first_seen_order(self):
        self.assertEqual(store._parse_tags("tags: b, a, B, a, c"), ["b", "a", "c"])

    def test_missing_line(self):
        self.assertEqual(store._parse_tags("# T\n\nno tags here\n"), [])
        self.assertEqual(store._parse_tags(""), [])


class ListFeaturesTagsTests(TmpRootCase):
    def test_tagged_and_untagged_rows(self):
        tagged = self.make("Tagged", "tags: a, x/y")
        plain = self.make("Plain")
        rows = {r["slug"]: r for r in store.list_features(self.root)}
        self.assertEqual(rows[tagged]["tags"], ["a", "x/y"])
        self.assertEqual(rows[plain]["tags"], [])
        for slug, title in ((tagged, "Tagged"), (plain, "Plain")):
            row = rows[slug]
            for key in ("slug", "title", "status", "ticked", "total", "repo", "updated"):
                self.assertIn(key, row)
            self.assertEqual(row["slug"], slug)
            self.assertEqual(row["title"], title)
            self.assertEqual(row["status"], "Grilling")
            self.assertEqual((row["ticked"], row["total"]), (0, 0))
            self.assertEqual(row["repo"], "")
            self.assertIsInstance(row["updated"], float)

    def test_repo_still_reported_alongside_tags(self):
        slug = store.create_feature("Both", "repo: some-repo\ntags: z\nbuild", self.root)
        (row,) = store.list_features(self.root)
        self.assertEqual((row["slug"], row["repo"], row["tags"]), (slug, "some-repo", ["z"]))


class TagMatchesTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(store.tag_matches(["x/y"], ["x/y"]))

    def test_parent_matches(self):
        self.assertTrue(store.tag_matches(["x/y"], ["x"]))

    def test_prefix_without_slash_does_not_match(self):
        self.assertFalse(store.tag_matches(["xy"], ["x"]))

    def test_child_selected_does_not_match_parent_feature(self):
        self.assertFalse(store.tag_matches(["x"], ["x/y"]))

    def test_all_selected_tags_required(self):
        self.assertFalse(store.tag_matches(["a"], ["a", "b"]))
        self.assertTrue(store.tag_matches(["a", "b/c"], ["a", "b"]))

    def test_no_selection_matches_everything(self):
        self.assertTrue(store.tag_matches([], []))
        self.assertTrue(store.tag_matches(["a"], []))


class AllTagsTests(TmpRootCase):
    def counts(self):
        return {r["tag"]: r["count"] for r in store.all_tags(self.root)}

    def test_empty_root(self):
        self.assertEqual(store.all_tags(self.root), [])
        self.make("Untagged")
        self.assertEqual(store.all_tags(self.root), [])

    def test_shared_tag_counts_each_feature(self):
        self.make("One", "tags: shared, only-one")
        self.make("Two", "tags: shared")
        counts = self.counts()
        self.assertEqual(counts["shared"], 2)
        self.assertEqual(counts["only-one"], 1)

    def test_nested_tag_counts_toward_parents(self):
        self.make("One", "tags: x/y/z")
        self.make("Two", "tags: x/w")
        self.assertEqual(self.counts(), {"x": 2, "x/w": 1, "x/y": 1, "x/y/z": 1})

    def test_feature_with_parent_and_child_counts_parent_once(self):
        self.make("One", "tags: x, x/y")
        self.assertEqual(self.counts(), {"x": 1, "x/y": 1})

    def test_result_is_sorted(self):
        self.make("One", "tags: b, a/c")
        self.assertEqual([r["tag"] for r in store.all_tags(self.root)], ["a", "a/c", "b"])


class SetTagsTests(TmpRootCase):
    def _read(self, slug):
        return (self.root / slug / "request.md").read_text(encoding="utf-8")

    def _make_with_request(self, slug, text):
        d = self.root / slug
        d.mkdir(parents=True)
        d.joinpath("plan.md").write_text(f"# Plan: {slug}\n\n_Not started._\n")
        d.joinpath("interview.md").write_text(f"# Interview: {slug}\n\n_Not started._\n")
        d.joinpath("checklist.md").write_text(f"# Checklist: {slug}\n\n")
        d.joinpath("request.md").write_text(text, encoding="utf-8")
        return slug

    def test_set_tags_adds_after_repo_line(self):
        slug = self._make_with_request("with-repo", "# My Feature\n\nrepo: some-repo\n\nbuild it\n")
        store.set_tags(slug, ["alpha", "beta"], root=self.root)
        text = self._read(slug)
        lines = text.splitlines()
        repo_idx = next(i for i, l in enumerate(lines) if l.startswith("repo:"))
        tags_idx = next(i for i, l in enumerate(lines) if l.startswith("tags:"))
        self.assertEqual(tags_idx, repo_idx + 1)
        self.assertEqual(lines[tags_idx], "tags: alpha, beta")

    def test_set_tags_adds_after_heading_when_no_repo(self):
        slug = self._make_with_request("no-repo", "# My Feature\n\nbuild it\n")
        store.set_tags(slug, ["alpha", "beta"], root=self.root)
        text = self._read(slug)
        lines = text.splitlines()
        heading_idx = next(i for i, l in enumerate(lines) if l.startswith("# "))
        tags_idx = next(i for i, l in enumerate(lines) if l.startswith("tags:"))
        self.assertEqual(tags_idx, heading_idx + 1)
        self.assertEqual(lines[tags_idx], "tags: alpha, beta")

    def test_set_tags_replaces_in_place(self):
        slug = self._make_with_request("replace", "# My Feature\n\nrepo: some-repo\ntags: old, one\ntodo\n")
        store.set_tags(slug, ["new"], root=self.root)
        text = self._read(slug)
        self.assertIn("tags: new\n", text)
        self.assertNotIn("tags: old, one", text)

    def test_set_tags_empty_list_removes_line(self):
        slug = self._make_with_request("remove", "# My Feature\n\nrepo: some-repo\ntags: a, b\ntodo\n")
        store.set_tags(slug, [], root=self.root)
        text = self._read(slug)
        self.assertNotIn("tags:", text)
        self.assertIn("todo\n", text)

    def test_set_tags_preserves_other_lines(self):
        slug = self._make_with_request("preserve", "# My Feature\n\nrepo: some-repo\ntags: a, b\nline one\nline two\n")
        store.set_tags(slug, ["x", "y"], root=self.root)
        text = self._read(slug)
        self.assertIn("line one\n", text)
        self.assertIn("line two\n", text)
        self.assertIn("repo: some-repo\n", text)

    def test_set_tags_invalid_tag_raises_valueerror(self):
        slug = self._make_with_request("invalid", "# My Feature\n\nbuild it\n")
        with self.assertRaises(ValueError):
            store.set_tags(slug, ["Bad Tag!"], root=self.root)
        with self.assertRaises(ValueError):
            store.set_tags(slug, ["a.b"], root=self.root)

    def test_set_tags_invalid_tag_file_unchanged(self):
        slug = self._make_with_request("unchanged", "# My Feature\n\nbuild it\n")
        original = self._read(slug)
        with self.assertRaises(ValueError):
            store.set_tags(slug, ["Bad Tag!"], root=self.root)
        self.assertEqual(self._read(slug), original)

    def test_set_tags_values_read_back(self):
        slug = self._make_with_request("roundtrip", "# My Feature\n\nrepo: r\ntags: a, b, c\n")
        store.set_tags(slug, ["x", "y"], root=self.root)
        text = self._read(slug)
        self.assertEqual(store._parse_tags(text), ["x", "y"])


class CreateFeatureTagsTests(TmpRootCase):
    def _read(self, slug):
        return (self.root / slug / "request.md").read_text(encoding="utf-8")

    def test_create_feature_with_tags_writes_line_after_heading(self):
        slug = store.create_feature("Tagged", "build it", self.root, tags=["alpha", "beta"])
        text = self._read(slug)
        lines = text.splitlines()
        heading_idx = next(i for i, l in enumerate(lines) if l.startswith("# "))
        tags_idx = next(i for i, l in enumerate(lines) if l.startswith("tags:"))
        self.assertEqual(tags_idx, heading_idx + 1)
        self.assertEqual(lines[tags_idx], "tags: alpha, beta")

    def test_create_feature_without_tags_same_text_as_before(self):
        slug = store.create_feature("Plain", "build it", self.root)
        text = self._read(slug)
        self.assertNotIn("tags:", text)
        self.assertTrue(text.startswith("# Plain\n\nbuild it\n"))

    def test_create_feature_tags_read_back(self):
        slug = store.create_feature("Roundtrip", "build it", self.root, tags=["p", "q/r"])
        text = self._read(slug)
        self.assertEqual(store._parse_tags(text), ["p", "q/r"])


if __name__ == "__main__":
    unittest.main()
