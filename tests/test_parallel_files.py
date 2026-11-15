"""Tests for server/core/parallel_files.py: files_of parsing and depends_transitively reachability,
including cycles and missing keys. Plain unittest, standard library only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core.parallel_files import depends_transitively, files_of


class FilesOfTests(unittest.TestCase):
    def test_no_files_line_returns_empty_set(self):
        self.assertEqual(files_of("Title: x\nSome description only.\n"), set())

    def test_empty_text_returns_empty_set(self):
        self.assertEqual(files_of(""), set())

    def test_single_path(self):
        self.assertEqual(files_of("Files: src/a.py"), {"src/a.py"})

    def test_comma_separated_paths(self):
        self.assertEqual(
            files_of("Files: src/a.py, src/b.py,docs/c.md"),
            {"src/a.py", "src/b.py", "docs/c.md"},
        )

    def test_whitespace_is_stripped(self):
        self.assertEqual(
            files_of("   Files:   src/a.py ,   src/b.py  \n"),
            {"src/a.py", "src/b.py"},
        )

    def test_files_line_found_among_other_lines(self):
        text = "Title: x\n- [ ] item\nFiles: src/a.py, src/b.py\nAcceptance: it works\n"
        self.assertEqual(files_of(text), {"src/a.py", "src/b.py"})


class DependsTransitivelyTests(unittest.TestCase):
    def test_direct_edge_forward(self):
        deps = {"a": {"b"}}
        self.assertTrue(depends_transitively("a", "b", deps))

    def test_direct_edge_reverse(self):
        deps = {"a": {"b"}}
        self.assertTrue(depends_transitively("b", "a", deps))

    def test_transitive_chain(self):
        deps = {"a": {"b"}, "b": {"c"}}
        self.assertTrue(depends_transitively("a", "c", deps))
        self.assertTrue(depends_transitively("c", "a", deps))

    def test_unrelated_pair_is_false(self):
        deps = {"a": {"b"}, "c": {"d"}}
        self.assertFalse(depends_transitively("a", "c", deps))
        self.assertFalse(depends_transitively("b", "d", deps))

    def test_two_node_cycle_terminates(self):
        deps = {"a": {"b"}, "b": {"a"}, "x": set()}
        self.assertTrue(depends_transitively("a", "b", deps))
        self.assertFalse(depends_transitively("a", "x", deps))

    def test_three_node_cycle_terminates(self):
        deps = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
        self.assertTrue(depends_transitively("a", "c", deps))
        self.assertFalse(depends_transitively("a", "d", deps))

    def test_missing_key_in_deps(self):
        self.assertFalse(depends_transitively("a", "b", {}))
        deps = {"a": {"b"}}
        self.assertFalse(depends_transitively("b", "c", deps))

    def test_same_node_is_false(self):
        deps = {"a": {"b"}, "b": {"a"}}
        self.assertFalse(depends_transitively("a", "a", deps))
        self.assertFalse(depends_transitively("z", "z", {}))


if __name__ == "__main__":
    unittest.main()
