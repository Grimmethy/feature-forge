"""Tests for tools/grillbot/rules.py: loading and validating a design rules file, rule ids, and prompt rendering.
Every fixture is written into a temporary directory. Plain unittest, standard library only."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.grillbot.rules import RulesError, load_rules, rule_ids, render_for_prompt

LABELS = ('Rule:', 'Why:', 'How to apply:', 'Source:')


def section(rule_id, title='Title', omit=None, rule='Do the thing.', why='Because it matters.',
            how='Apply it always.', source='spec section'):
    values = [('Rule:', rule), ('Why:', why), ('How to apply:', how), ('Source:', source)]
    lines = ['### %s %s' % (rule_id, title)]
    for label, value in values:
        if label != omit:
            lines.append('%s %s' % (label, value))
    return '\n'.join(lines) + '\n'


VALID = (
    '# Design rules\n\n'
    + section('R1', 'First rule', rule='Do the first thing.', why='Reason one.', how='Apply one.', source='spec 1')
    + '\n'
    + section('R2', 'Second rule', rule='Do the second thing.', why='Reason two.', how='Apply two.', source='spec 2')
    + '\n'
    + section('R3', 'Third rule', rule='Do the third thing.', why='Reason three.', how='Apply three.', source='spec 3')
)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write_rules(self, text):
        path = self.root / 'rules.md'
        path.write_text(text, encoding='utf-8')
        return path

    def load(self, text):
        return load_rules(self.write_rules(text))


class LoadTests(Base):
    def test_valid_three_rule_file_loads_with_correct_keys_and_values(self):
        rules = self.load(VALID)
        self.assertEqual(len(rules), 3)
        self.assertEqual(
            rules[0],
            {'id': 'R1', 'title': 'First rule', 'rule': 'Do the first thing.', 'why': 'Reason one.',
             'how': 'Apply one.', 'source': 'spec 1'},
        )
        self.assertEqual(set(rules[2].keys()), {'id', 'title', 'rule', 'why', 'how', 'source'})
        self.assertEqual(rules[2]['id'], 'R3')
        self.assertEqual(rules[2]['title'], 'Third rule')
        self.assertEqual(rules[2]['rule'], 'Do the third thing.')

    def test_each_missing_label_raises_naming_the_rule_id(self):
        for label in LABELS:
            with self.subTest(label=label):
                text = section('R1') + '\n' + section('R2', omit=label)
                with self.assertRaises(RulesError) as ctx:
                    self.load(text)
                self.assertIn('R2', str(ctx.exception))

    def test_empty_field_raises_naming_the_rule_id(self):
        with self.assertRaises(RulesError) as ctx:
            self.load(section('R1', rule=''))
        self.assertIn('R1', str(ctx.exception))

    def test_repeated_id_raises(self):
        text = section('R1', 'First') + '\n' + section('R1', 'Again')
        with self.assertRaises(RulesError) as ctx:
            self.load(text)
        self.assertIn('R1', str(ctx.exception))

    def test_empty_file_raises(self):
        with self.assertRaises(RulesError):
            self.load('')

    def test_preamble_only_file_raises(self):
        with self.assertRaises(RulesError):
            self.load('# Design rules\n\nSome introduction prose with no rules in it.\n')

    def test_multi_line_field_is_joined_with_newlines(self):
        text = (
            '### R1 Multi\n'
            'Rule: first line\nsecond line\nthird line\n'
            'Why: why\n'
            'How to apply: how\n'
            'Source: src\n'
        )
        rules = self.load(text)
        self.assertEqual(rules[0]['rule'], 'first line\nsecond line\nthird line')

    def test_text_before_the_first_heading_is_ignored(self):
        text = 'Stray intro line.\nRule: not a real rule\n\n' + section('R1', 'Only')
        rules = self.load(text)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['id'], 'R1')
        self.assertEqual(rules[0]['rule'], 'Do the thing.')
        self.assertNotIn('Stray', rules[0]['rule'])
        self.assertNotIn('not a real rule', rules[0]['rule'])

    def test_id_gaps_load_with_ids_as_written(self):
        text = section('R1', 'One') + '\n' + section('R3', 'Three')
        rules = self.load(text)
        self.assertEqual([r['id'] for r in rules], ['R1', 'R3'])


class RuleIdsTests(Base):
    def test_rule_ids_returns_ids_in_document_order(self):
        rules = self.load(VALID)
        self.assertEqual(rule_ids(rules), ['R1', 'R2', 'R3'])


class RenderTests(Base):
    def test_render_includes_every_field_of_every_rule(self):
        rules = self.load(VALID)
        out = render_for_prompt(rules)
        for rule in rules:
            with self.subTest(id=rule['id']):
                self.assertIn(rule['id'], out)
                self.assertIn(rule['title'], out)
                self.assertIn(rule['rule'], out)
                self.assertIn(rule['why'], out)
                self.assertIn(rule['how'], out)
                self.assertIn(rule['source'], out)
        for label in LABELS:
            self.assertIn(label, out)


class ErrorTypeTests(unittest.TestCase):
    def test_rules_error_is_a_value_error(self):
        self.assertTrue(issubclass(RulesError, ValueError))


if __name__ == '__main__':
    unittest.main()
