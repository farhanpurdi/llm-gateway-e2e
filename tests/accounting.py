"""Independent checks for bounded, default-tier text requests; no HTTP here."""
from decimal import Decimal
import math


# Official OpenAI model pages verified 2026-10-13; USD per token.
# This is a test oracle, not a runtime price override.
PRICES = {
    'company-fast': {'upstream': 'openai/gpt-5.6-terra',
                     'input_cost_per_token': 0.000002,
                     'cache_read_input_token_cost': 0.0000002,
                     'output_cost_per_token': 0.000012},
    'company-coding': {'upstream': 'openai/gpt-5.6-sol',
                       'input_cost_per_token': 0.000004,
                       'cache_read_input_token_cost': 0.0000004,
                       'output_cost_per_token': 0.000020},
}
PRICE_SOURCES = {
    'company-fast': 'https://developers.openai.com/api/docs/models/gpt-5.6-terra',
    'company-coding': 'https://developers.openai.com/api/docs/models/gpt-5.6-sol',
}


def text_cost(alias, usage):
    counts = {name: usage.get(name) for name in (
        'prompt_tokens', 'completion_tokens', 'total_tokens')}
    details = usage.get('prompt_tokens_details') or {}
    cached = details.get('cached_tokens', 0)
    for value in [*counts.values(), cached]:
        if type(value) is not int or value < 0:
            raise AssertionError('Usage counts must be non-negative integers')
    prompt, output = counts['prompt_tokens'], counts['completion_tokens']
    if counts['total_tokens'] != prompt + output or cached > prompt:
        raise AssertionError('Inconsistent token usage')
    if prompt > 272000 or details.get('cache_creation_tokens', 0):
        raise AssertionError('Scenario is outside standard short-text pricing')
    prices = PRICES[alias]
    # Reasoning tokens are already part of completion_tokens; do not add twice.
    return sum(Decimal(str(prices[field])) * count for field, count in (
        ('input_cost_per_token', prompt - cached),
        ('cache_read_input_token_cost', cached), ('output_cost_per_token', output)))


def assert_spend_record(row, *, alias, usage, request_id, user_id, team_id, token):
    identity = {'request_id': request_id, 'user': user_id,
                'team_id': team_id, 'api_key': token}
    if any(row.get(field) != value for field, value in identity.items()):
        raise AssertionError('Request/key/user/team attribution mismatch')
    if row.get('model_group') != alias:
        raise AssertionError('Logical alias attribution mismatch')
    if row.get('model') not in {PRICES[alias]['upstream'], PRICES[alias]['upstream'].removeprefix('openai/')}:
        raise AssertionError('Upstream model attribution mismatch')
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        if row.get(field) != usage[field]:
            raise AssertionError('Stored token usage differs from provider response')
    spend = row.get('spend')
    if isinstance(spend, bool) or not isinstance(spend, (int, float)) or not math.isfinite(spend):
        raise AssertionError('Spend must be a finite number')
    expected = text_cost(alias, usage)
    if expected <= 0 or abs(Decimal(str(spend)) - expected) > Decimal('0.00000001'):
        raise AssertionError('Stored cost differs from independently calculated token cost')
    return expected
