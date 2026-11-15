"""Tests for tools/grillbot/answer.py: reply parsing, hard-stop flags and the bot-or-owner decision.
Plain unittest, standard library only."""
import json
import sys
import unittest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from tools.grillbot.answer import final_decision, hard_stop, parse_answer

RULES = {'R1', 'R3'}
TITLES = {'Example one'}


def reply(answer='Use the shared clock.', level=4, citations=('R3',)):
    return json.dumps({'answer': answer, 'level': level, 'citations': list(citations)})


class ParseAnswerTests(unittest.TestCase):
    def test_plain_json(self):
        out = parse_answer(reply(), RULES, TITLES)
        self.assertEqual(out, {'answer': 'Use the shared clock.', 'level': 4, 'citations': ['R3'], 'flags': []})

    def test_fenced_json(self):
        text = 'Here you go:\n```json\n%s\n```\nHope that helps.' % reply()
        out = parse_answer(text, RULES, TITLES)
        self.assertEqual(out['level'], 4)
        self.assertEqual(out['flags'], [])

    def test_prose_around_json(self):
        out = parse_answer('Sure. %s Done.' % reply(level=5, citations=('R1', 'Example one')), RULES, TITLES)
        self.assertEqual(out['level'], 5)
        self.assertEqual(out['citations'], ['R1', 'Example one'])

    def test_first_json_object_wins(self):
        text = reply(answer='first', level=4) + ' and then ' + reply(answer='second', level=2)
        self.assertEqual(parse_answer(text, RULES, TITLES)['answer'], 'first')

    def test_unknown_citation_dropped_and_flagged(self):
        out = parse_answer(reply(citations=('R3', 'R99')), RULES, TITLES)
        self.assertEqual(out['citations'], ['R3'])
        self.assertEqual(out['flags'], ['unknown-citation'])
        self.assertEqual(out['level'], 4)

    def test_no_citation_caps_level_at_two(self):
        out = parse_answer(reply(level=5, citations=()), RULES, TITLES)
        self.assertEqual(out['level'], 2)
        self.assertEqual(out['flags'], ['no-citation'])

    def test_only_unknown_citations_cap_level_and_flag_both(self):
        out = parse_answer(reply(level=5, citations=('R99',)), RULES, TITLES)
        self.assertEqual(out['citations'], [])
        self.assertEqual(out['level'], 2)
        self.assertEqual(out['flags'], ['unknown-citation', 'no-citation'])

    def test_low_level_without_citation_stays_low(self):
        out = parse_answer(reply(level=1, citations=()), RULES, TITLES)
        self.assertEqual(out['level'], 1)

    def test_bad_inputs_are_unparseable_and_never_raise(self):
        bad = [
            'no json here',
            '{"answer": "x", "level": 4',
            '{"level": 4, "citations": []}',
            '{"answer": "", "level": 4, "citations": []}',
            '{"answer": "x", "citations": []}',
            '{"answer": "x", "level": 4}',
            '{"answer": "x", "level": "4", "citations": []}',
            '{"answer": "x", "level": 0, "citations": []}',
            '{"answer": "x", "level": 6, "citations": []}',
            '{"answer": "x", "level": true, "citations": []}',
            '{"answer": "x", "level": 4, "citations": "R3"}',
            '{"answer": "x", "level": 4, "citations": [3]}',
            '[1, 2]',
            '',
            None,
        ]
        for text in bad:
            out = parse_answer(text, RULES, TITLES)
            self.assertEqual(out, {'answer': '', 'level': 1, 'citations': [], 'flags': ['unparseable']}, text)


class HardStopTests(unittest.TestCase):
    def q(self, title='', body='', recommended=''):
        return {'title': title, 'body': body, 'recommended': recommended}

    def test_clean_question_has_no_reasons(self):
        self.assertEqual(hard_stop(self.q('Which clock?', 'Use one shared clock', 'Yes')), [])

    def test_money_words(self):
        for word in ('price', 'cost', 'budget', 'pay', 'purchase', 'subscription', 'plan limit', 'spend'):
            reasons = hard_stop(self.q('Should we %s this?' % word))
            self.assertTrue(any(word in r and r.startswith('money') for r in reasons), word)

    def test_outward_words(self):
        for word in ('publish', 'send', 'post', 'email', 'delete', 'drop', 'force push', 'credentials',
                     'token', 'password', 'secret'):
            reasons = hard_stop(self.q('', 'we would %s it' % word))
            self.assertTrue(any(word in r and r.startswith('outward') for r in reasons), word)

    def test_text_is_read_from_title_body_and_recommended(self):
        self.assertTrue(hard_stop(self.q('', '', 'delete the branch')))
        self.assertTrue(hard_stop(self.q('', 'delete the branch', '')))
        self.assertTrue(hard_stop(self.q('delete the branch')))

    def test_whole_words_only_and_case_insensitive(self):
        self.assertEqual(hard_stop(self.q('The postgres sender dropdown')), [])
        self.assertTrue(hard_stop(self.q('PUBLISH it')))
        self.assertEqual(hard_stop(self.q('re-send the list')), [])

    def test_repo_name_hit(self):
        reasons = hard_stop(self.q('Change the payments-app config'), repos_needing_approval=('payments-app',))
        self.assertIn('repo needing approval: payments-app', reasons)
        self.assertEqual(hard_stop(self.q('Change the other config'), repos_needing_approval=('payments-app',)), [])

    def test_owner_only_phrase(self):
        self.assertIn('marked owner-only', hard_stop(self.q('This is owner-only')))

    def test_missing_keys_do_not_raise(self):
        self.assertEqual(hard_stop({}), [])


class FinalDecisionTests(unittest.TestCase):
    Q = {'title': 'Which clock?', 'body': '', 'recommended': ''}

    def parsed(self, level, flags=()):
        return {'answer': 'x', 'level': level, 'citations': ['R3'], 'flags': list(flags)}

    def test_level_at_bar_goes_to_bot(self):
        out = final_decision(self.Q, self.parsed(4), level_bar=4)
        self.assertEqual(out['who'], 'bot')
        self.assertEqual(out['hard_stop'], [])

    def test_level_below_bar_goes_to_owner(self):
        out = final_decision(self.Q, self.parsed(3), level_bar=4)
        self.assertEqual(out['who'], 'owner')
        self.assertIn('below', out['reason'])

    def test_bar_is_adjustable(self):
        self.assertEqual(final_decision(self.Q, self.parsed(3), level_bar=3)['who'], 'bot')
        self.assertEqual(final_decision(self.Q, self.parsed(5), level_bar=5)['who'], 'bot')

    def test_unparseable_goes_to_owner_even_with_high_level(self):
        out = final_decision(self.Q, self.parsed(5, flags=['unparseable']))
        self.assertEqual(out['who'], 'owner')

    def test_hard_stop_is_reported_but_does_not_force_the_owner(self):
        q = {'title': 'Publish the release?', 'body': 'spend the budget', 'recommended': ''}
        out = final_decision(q, self.parsed(5))
        self.assertEqual(out['who'], 'bot')
        self.assertTrue(any(r.startswith('outward') for r in out['hard_stop']))
        self.assertTrue(any(r.startswith('money') for r in out['hard_stop']))

    def test_hard_stop_with_low_level_still_goes_to_owner_and_lists_reasons(self):
        q = {'title': 'Delete it?', 'body': '', 'recommended': ''}
        out = final_decision(q, self.parsed(2))
        self.assertEqual(out['who'], 'owner')
        self.assertTrue(out['hard_stop'])

    def test_repos_argument_reaches_hard_stop(self):
        q = {'title': 'Edit payments-app', 'body': '', 'recommended': ''}
        out = final_decision(q, self.parsed(5), repos=('payments-app',))
        self.assertIn('repo needing approval: payments-app', out['hard_stop'])


if __name__ == '__main__':
    unittest.main()
