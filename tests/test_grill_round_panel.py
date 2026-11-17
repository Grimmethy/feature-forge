"""Unit tests for the pure grill round helpers in grill_round_panel.py.

Written as unittest.TestCase classes so they run under both
`python -m unittest` (the repo convention) and `python -m pytest tests -q`.
"""
import unittest

from grill_round_panel import parse_recommended, render_diff_details, split_rounds


ROUND_TEXT = (
    "Which database should we use?\n"
    "  Postgres\n"
    "-> Postgres\n"
    "Should we add caching?\n"
    "  Not yet\n"
    "Who owns the migration?\n"
    "  The platform team\n"
)


class SplitRoundsTests(unittest.TestCase):
    def test_round_with_three_questions_yields_three_blocks(self):
        blocks = split_rounds(ROUND_TEXT)
        self.assertEqual(len(blocks), 3)
        for block in blocks:
            self.assertIsInstance(block, dict)
            self.assertIn("question", block)
            self.assertIn("answer_lines", block)
            self.assertIsInstance(block["answer_lines"], list)

    def test_questions_are_the_unindented_lines(self):
        blocks = split_rounds(ROUND_TEXT)
        self.assertEqual(
            [b["question"] for b in blocks],
            [
                "Which database should we use?",
                "Should we add caching?",
                "Who owns the migration?",
            ],
        )

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(split_rounds(""), [])
        self.assertEqual(split_rounds("   \n  "), [])


class ParseRecommendedTests(unittest.TestCase):
    def test_arrow_line_is_recommended(self):
        self.assertEqual(parse_recommended("-> Postgres"), "Postgres")

    def test_indented_arrow_line_is_recommended(self):
        self.assertEqual(parse_recommended("  -> Postgres"), "Postgres")

    def test_plain_answer_line_returns_none(self):
        self.assertIsNone(parse_recommended("Postgres"))

    def test_empty_line_returns_none(self):
        self.assertIsNone(parse_recommended(""))

    def test_dash_without_greater_than_returns_none(self):
        self.assertIsNone(parse_recommended("a - b"))


class RenderDiffDetailsTests(unittest.TestCase):
    DIFF_JSON = '{"a": 1}'

    def test_wrapped_in_closed_details_element(self):
        out = render_diff_details(self.DIFF_JSON)
        self.assertTrue(out.startswith("<details>"))
        self.assertTrue(out.endswith("</details>"))
        self.assertNotIn("open", out.split(">", 1)[0])

    def test_has_proposed_changes_summary(self):
        out = render_diff_details(self.DIFF_JSON)
        self.assertIn("<summary>Proposed changes</summary>", out)

    def test_diff_content_is_inside_details(self):
        out = render_diff_details(self.DIFF_JSON)
        inner = out[len("<details>"):-len("</details>")]
        self.assertIn("&quot;a&quot;: 1", inner)
        self.assertIn("<summary>Proposed changes</summary>", inner)

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            render_diff_details("{not json")


if __name__ == "__main__":
    unittest.main()
