'''Parse the answerer's reply, flag hard-stop topics, and decide bot or owner.

Pure functions, standard library only, no timers or threads.

- parse_answer: pull the first JSON object out of the model text, validate it,
  drop unknown citations and cap the level when nothing valid is cited.
- hard_stop: keyword families (money, outward-facing or irreversible,
  approval-list repos, an explicit owner-only marker) that mark a question for
  the owner's attention in review.
- final_decision: who answers, from the stated level, the level bar and the
  parse flags. Hard-stop reasons are returned as a flag, they do not by
  themselves send the question to the owner (owner decision 2026-11-15).
'''

import json
import re

MIN_LEVEL = 1
MAX_LEVEL = 5
NO_CITATION_CAP = 2

FLAG_UNPARSEABLE = 'unparseable'
FLAG_UNKNOWN_CITATION = 'unknown-citation'
FLAG_NO_CITATION = 'no-citation'

# Keyword families for hard_stop. Whole words or phrases, matched case-insensitively.
MONEY_WORDS = (
    'price', 'prices', 'cost', 'costs', 'budget', 'pay', 'pays', 'payment', 'purchase',
    'subscription', 'plan limit', 'spend', 'spending',
)
OUTWARD_WORDS = (
    'publish', 'send', 'post', 'email', 'delete', 'drop', 'force push',
    'credentials', 'token', 'password', 'secret',
)
OWNER_ONLY_PHRASE = 'owner-only'


def _empty_result():
    return {'answer': '', 'level': MIN_LEVEL, 'citations': [], 'flags': [FLAG_UNPARSEABLE]}


def _first_json_object(text):
    '''Return the first JSON object (a dict) found anywhere in text, or None.'''
    decoder = json.JSONDecoder()
    start = text.find('{')
    while start != -1:
        try:
            value, _end = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, dict):
            return value
        start = text.find('{', start + 1)
    return None


def parse_answer(text, rule_ids, example_titles):
    '''Parse the model text into {answer, level, citations, flags}. Never raises.'''
    try:
        obj = _first_json_object(text if isinstance(text, str) else '')
        if obj is None:
            return _empty_result()
        answer = obj.get('answer')
        level = obj.get('level')
        citations = obj.get('citations')
        if not isinstance(answer, str) or not answer.strip():
            return _empty_result()
        if isinstance(level, bool) or not isinstance(level, int) or not MIN_LEVEL <= level <= MAX_LEVEL:
            return _empty_result()
        if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
            return _empty_result()
        known = set(rule_ids) | set(example_titles)
        kept = [c for c in citations if c in known]
        flags = []
        if len(kept) != len(citations):
            flags.append(FLAG_UNKNOWN_CITATION)
        if not kept:
            level = min(level, NO_CITATION_CAP)
            flags.append(FLAG_NO_CITATION)
        return {'answer': answer, 'level': level, 'citations': kept, 'flags': flags}
    except Exception:  # the contract is "never raise"
        return _empty_result()


def _word_pattern(term):
    '''Whole-word, case-insensitive pattern; a name with dashes or dots is not split by them.'''
    return re.compile(r'(?<![\w-])' + re.escape(term) + r'(?![\w-])', re.IGNORECASE)


def _question_text(question):
    return ' '.join(str(question.get(k) or '') for k in ('title', 'body', 'recommended'))


def hard_stop(question, repos_needing_approval=()):
    '''List the reasons this question touches a hard-stop topic (empty list = none).'''
    text = _question_text(question)
    reasons = []
    for word in MONEY_WORDS:
        if _word_pattern(word).search(text):
            reasons.append('money or plan spend: %s' % word)
    for word in OUTWARD_WORDS:
        if _word_pattern(word).search(text):
            reasons.append('outward-facing or irreversible: %s' % word)
    for name in repos_needing_approval:
        if name and _word_pattern(name).search(text):
            reasons.append('repo needing approval: %s' % name)
    if _word_pattern(OWNER_ONLY_PHRASE).search(text):
        reasons.append('marked owner-only')
    return reasons


def final_decision(question, parsed, level_bar=4, repos=()):
    '''Decide who answers: {'who': 'bot'|'owner', 'reason': str, 'hard_stop': [reasons]}.

    The owner answers when the stated level is below the bar or the reply was
    unparseable. Hard-stop reasons are reported in 'hard_stop' for the review
    screen to flag; they do not by themselves hand the question to the owner.
    '''
    stops = hard_stop(question, repos)
    flags = parsed.get('flags') or []
    if FLAG_UNPARSEABLE in flags:
        return {'who': 'owner', 'reason': 'the answer could not be parsed', 'hard_stop': stops}
    level = parsed.get('level', MIN_LEVEL)
    if level < level_bar:
        return {'who': 'owner', 'reason': 'level %d is below the bar %d' % (level, level_bar), 'hard_stop': stops}
    return {'who': 'bot', 'reason': 'level %d meets the bar %d' % (level, level_bar), 'hard_stop': stops}
