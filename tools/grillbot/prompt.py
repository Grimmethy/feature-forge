'''Build the prompt sent to the answerer model.

The prompt instructs the model to answer as the owner would, grounded only in
the provided rules and worked examples, and to emit a single JSON object with
``answer``, ``level`` and ``citations``.
'''


# ---------------------------------------------------------------------------
# Prompt text constants
# ---------------------------------------------------------------------------

PREAMBLE = (
    'You are answering AS the owner of this project would answer, '
    'based ONLY on the rules and worked examples below. '
    'Do not use outside knowledge. Do not invent rules or examples.'
)

RULES_HEADING = 'RULES'

EXAMPLES_HEADING = 'HOW THE OWNER ANSWERED BEFORE'

JSON_OUTPUT_INSTRUCTION = (
    'Respond with ONE JSON object in this exact schema:\n'
    '{"answer": <string>, "level": <integer 1-5>, '
    '"citations": [<string>]}\n'
    'Each citation must be a rule id (e.g. R3) or an example title. '
    'An answer with no citation will be treated as level 2 at most.'
)

NO_PRECEDENT_RULE = (
    'If the rules and examples give no precedent for answering this '
    'question, answer level 1 and cite nothing.'
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_answer_prompt(question, rules_text, examples, context=None):
    '''Build the full prompt string for the answerer model.

    Args:
        question: dict with keys ``title``, ``body``, ``recommended``.
        rules_text: verbatim rules block (e.g. from rules.render_for_prompt).
        examples: list of example dicts with keys ``title``, ``body``,
            ``recommended``, ``owner_answer``. An empty list is accepted.
        context: optional extra context string; included only when truthy.

    Returns:
        The assembled prompt as a string.
    '''
    parts = []

    # Preamble
    parts.append(PREAMBLE)

    # Rules
    parts.append(RULES_HEADING)
    parts.append(rules_text)

    # Examples (worked answers)
    parts.append(EXAMPLES_HEADING)
    if examples:
        for example in examples:
            parts.append(_render_example(example))

    # Optional context
    if context:
        parts.append(context)

    # No-precedent rule
    parts.append(NO_PRECEDENT_RULE)

    # JSON output instruction
    parts.append(JSON_OUTPUT_INSTRUCTION)

    # The question itself (last)
    parts.append(_render_question(question))

    return '\n\n'.join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_question(question):
    lines = []
    if question.get('title'):
        lines.append('QUESTION: %s' % question['title'])
    if question.get('body'):
        lines.append(question['body'])
    if question.get('recommended'):
        lines.append('RECOMMENDED: %s' % question['recommended'])
    return '\n'.join(lines)


def _render_example(example):
    sections = []
    if example.get('title'):
        sections.append('Example: %s' % example['title'])
    if example.get('body'):
        sections.append('Question:\n%s' % example['body'])
    if example.get('recommended'):
        sections.append('Recommended answer:\n%s' % example['recommended'])
    if example.get('owner_answer'):
        sections.append('Owner answer:\n%s' % example['owner_answer'])
    return '\n\n'.join(sections)
