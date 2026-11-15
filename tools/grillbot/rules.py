'''Loader, validator and prompt renderer for grillbot design rules.

A rules file holds sections headed ``### R<n> <title>``, each followed by the
labelled fields ``Rule:``, ``Why:``, ``How to apply:`` and ``Source:``.
'''
import re


class RulesError(ValueError):
    '''A rules file is malformed.'''


_HEADING = re.compile(r'^### R(\d+) (.+)$')
_LABELS = (
    ('Rule:', 'rule'),
    ('Why:', 'why'),
    ('How to apply:', 'how'),
    ('Source:', 'source'),
)
_FIELDS = ('rule', 'why', 'how', 'source')


def load_rules(path):
    '''Parse the rules file at path into a list of rule dicts, in file order.

    A missing file raises OSError unchanged.
    '''
    with open(path, encoding='utf-8') as handle:
        lines = handle.read().splitlines()

    entries = []
    current = None
    field = None
    for raw in lines:
        stripped = raw.strip()
        heading = _HEADING.match(stripped)
        if heading:
            rule_id = 'R' + heading.group(1)
            if any(entry['id'] == rule_id for entry in entries):
                raise RulesError('rule %s: repeated rule id' % rule_id)
            current = {'id': rule_id, 'title': heading.group(2).strip(), 'parts': {}}
            entries.append(current)
            field = None
            continue
        if current is None:
            continue
        matched = False
        for label, key in _LABELS:
            if raw.startswith(label):
                if key in current['parts']:
                    raise RulesError('rule %s: repeated label %s' % (current['id'], label))
                current['parts'][key] = [raw[len(label):]]
                field = key
                matched = True
                break
        if matched:
            continue
        if field is None:
            if stripped:
                raise RulesError('rule %s: text before its first label' % current['id'])
            continue
        current['parts'][field].append(raw)

    if not entries:
        raise RulesError('no rules found in %s' % path)

    rules = []
    for entry in entries:
        rule = {'id': entry['id'], 'title': entry['title']}
        for key in _FIELDS:
            rule[key] = '\n'.join(entry['parts'].get(key, [])).strip()
        for key in ('id', 'title') + _FIELDS:
            if not rule[key]:
                raise RulesError('rule %s: missing or empty %s' % (entry['id'], key))
        rules.append(rule)
    return rules


def rule_ids(rules):
    '''Return the ids of the rules, in order.'''
    return [rule['id'] for rule in rules]


def render_for_prompt(rules):
    '''Render every field of every rule as one block of prompt text.'''
    blocks = []
    for rule in rules:
        lines = ['### %s %s' % (rule['id'], rule['title'])]
        for label, key in _LABELS:
            lines.append('%s %s' % (label, rule[key]))
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)
