"""Tests for tools/grillbot/prompt.py: building the answer prompt.
Plain unittest, standard library only. No filesystem fixtures required."""
import copy
import sys
import unittest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from tools.grillbot.prompt import (
    JSON_OUTPUT_INSTRUCTION,
    NO_PRECEDENT_RULE,
    build_answer_prompt,
)


RULES_TEXT = (
    'RULES\n'
    'R1 Always be polite.\n'
    'R2 Never fabricate.\n'
    'R3 Keep it concise.\n'
)


QUESTION = {
    'title': 'How do I restart the service?',
    'body': 'I tried systemctl restart but it failed.',
    'recommended': 'Use `sudo systemctl restart myapp`.',
}

EXAMPLES = [
    {
        'title': 'R1 restart',
        'body': 'How do I restart the service?',
        'recommended': 'Use `systemctl restart myapp`.',
        'owner_answer': 'Run `sudo systemctl restart myapp`.',
    },
    {
        'title': 'R2 config change',
        'body': 'Can I change the log level?',
        'recommended': 'Set LOG_LEVEL=debug in .env.',
        'owner_answer': 'Add `LOG_LEVEL=debug` to `.env` and restart.',
    },
]

CONTEXT = 'The project uses systemd for process management.'


class BuildPromptTests(unittest.TestCase):
    def test_every_rule_line_appears_in_output(self):
        out = build_answer_prompt(QUESTION, RULES_TEXT, [])
        for line in RULES_TEXT.strip().splitlines():
            with self.subTest(line=line):
                self.assertIn(line, out)

    def test_every_example_title_body_owner_answer_appear(self):
        out = build_answer_prompt(QUESTION, RULES_TEXT, EXAMPLES)
        for ex in EXAMPLES:
            with self.subTest(title=ex['title']):
                self.assertIn(ex['title'], out)
                self.assertIn(ex['body'], out)
                self.assertIn(ex['owner_answer'], out)

    def test_question_is_last_content_block(self):
        out = build_answer_prompt(QUESTION, RULES_TEXT, EXAMPLES)
        # The question block is appended last, so the output must end with it.
        question_block = 'QUESTION: %s\n%s\nRECOMMENDED: %s' % (
            QUESTION['title'], QUESTION['body'], QUESTION['recommended'],
        )
        self.assertTrue(out.strip().endswith(question_block))

    def test_json_output_instruction_present(self):
        out = build_answer_prompt(QUESTION, RULES_TEXT, [])
        self.assertIn(JSON_OUTPUT_INSTRUCTION, out)

    def test_no_precedent_rule_present(self):
        out = build_answer_prompt(QUESTION, RULES_TEXT, [])
        self.assertIn(NO_PRECEDENT_RULE, out)

    def test_no_precedent_rule_before_json_instruction(self):
        out = build_answer_prompt(QUESTION, RULES_TEXT, [])
        self.assertLess(out.index(NO_PRECEDENT_RULE), out.index(JSON_OUTPUT_INSTRUCTION))

    def test_empty_examples_runs_without_error(self):
        out = build_answer_prompt(QUESTION, RULES_TEXT, [])
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_empty_body_runs_without_error(self):
        q = dict(QUESTION)
        q['body'] = ''
        out = build_answer_prompt(q, RULES_TEXT, [])
        self.assertIsInstance(out, str)
        self.assertIn('QUESTION:', out)

    def test_empty_recommended_runs_without_error(self):
        q = dict(QUESTION)
        q['recommended'] = ''
        out = build_answer_prompt(q, RULES_TEXT, [])
        self.assertIsInstance(out, str)
        self.assertNotIn('RECOMMENDED:', out)

    def test_question_without_title_or_body_runs_without_error(self):
        q = {'title': '', 'body': '', 'recommended': 'fallback'}
        out = build_answer_prompt(q, RULES_TEXT, [])
        self.assertIsInstance(out, str)

    def test_context_included_when_truthy(self):
        out = build_answer_prompt(QUESTION, RULES_TEXT, [], context=CONTEXT)
        self.assertIn(CONTEXT, out)

    def test_context_omitted_when_falsy(self):
        for falsy in (None, '', 0, [], {}):
            with self.subTest(context=falsy):
                out = build_answer_prompt(QUESTION, RULES_TEXT, [], context=falsy)
                self.assertNotIn(CONTEXT, out)

    def test_question_unchanged_after_call(self):
        q = copy.deepcopy(QUESTION)
        build_answer_prompt(QUESTION, RULES_TEXT, [])
        self.assertEqual(q, QUESTION)

    def test_examples_unchanged_after_call(self):
        ex = copy.deepcopy(EXAMPLES)
        build_answer_prompt(QUESTION, RULES_TEXT, EXAMPLES)
        self.assertEqual(ex, EXAMPLES)

    def test_context_unchanged_after_call(self):
        ctx = copy.deepcopy(CONTEXT)
        build_answer_prompt(QUESTION, RULES_TEXT, [], context=CONTEXT)
        self.assertEqual(ctx, CONTEXT)

    def test_empty_rules_text_runs_without_error(self):
        out = build_answer_prompt(QUESTION, '', [])
        self.assertIsInstance(out, str)

    def test_single_example_included(self):
        single = [dict(EXAMPLES[0])]
        out = build_answer_prompt(QUESTION, RULES_TEXT, single)
        self.assertIn(single[0]['title'], out)
        self.assertIn(single[0]['body'], out)
        self.assertIn(single[0]['owner_answer'], out)

    def test_example_with_empty_owner_answer_skipped(self):
        ex = {
            'title': 'R3 no answer',
            'body': 'What?',
            'recommended': 'Nothing',
            'owner_answer': '',
        }
        out = build_answer_prompt(QUESTION, RULES_TEXT, [ex])
        self.assertIn(ex['title'], out)
        self.assertIn(ex['body'], out)
        self.assertNotIn('Owner answer:', out)


if __name__ == '__main__':
    unittest.main()
