from copy import deepcopy
from decimal import Decimal

import pytest

from tests.accounting import PRICES, assert_spend_record, text_cost
from tests.client import LiteLLMClient, RedactedKey


pytestmark = pytest.mark.unit
USAGE = {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110,
         'prompt_tokens_details': {'cached_tokens': 20},
         'completion_tokens_details': {'reasoning_tokens': 5}}


@pytest.mark.parametrize('alias,expected', [('company-fast', '0.000284'), ('company-coding', '0.000528')])
def test_cost_discounts_cached_input_and_does_not_double_count_reasoning(alias, expected):
    assert text_cost(alias, USAGE) == Decimal(expected)


@pytest.mark.parametrize('field,value', [('prompt_tokens', -1), ('completion_tokens', True),
    ('total_tokens', 111), ('prompt_tokens', float('nan')), ('completion_tokens', None)])
def test_invalid_provider_usage_is_rejected(field, value):
    usage = deepcopy(USAGE)
    usage[field] = value
    with pytest.raises(AssertionError):
        text_cost('company-fast', usage)


@pytest.mark.parametrize('cached', [-1, 101, True])
def test_impossible_cache_usage_is_rejected(cached):
    usage = deepcopy(USAGE)
    usage['prompt_tokens_details']['cached_tokens'] = cached
    with pytest.raises(AssertionError):
        text_cost('company-fast', usage)


@pytest.mark.parametrize('case', ['long-context', 'cache-write'])
def test_nonstandard_pricing_is_not_silently_counted_as_standard(case):
    usage = deepcopy(USAGE)
    if case == 'long-context':
        usage.update(prompt_tokens=272001, total_tokens=272011)
    else:
        usage['prompt_tokens_details']['cache_creation_tokens'] = 1
    with pytest.raises(AssertionError, match='outside standard'):
        text_cost('company-fast', usage)


@pytest.mark.parametrize('field,value', [('request_id', 'wrong'), ('user', 'other'),
    ('team_id', 'other'), ('api_key', 'other'), ('model_group', 'company-coding'),
    ('model', 'wrong'), ('prompt_tokens', 99), ('completion_tokens', 9),
    ('total_tokens', 109), ('spend', 0.1), ('spend', float('nan')), ('spend', True)])
def test_wrong_attribution_tokens_and_cost_fail_the_live_assertion(field, value):
    row = {'request_id': 'request', 'user': 'user', 'team_id': 'team', 'api_key': 'token',
           'model_group': 'company-fast', 'model': 'gpt-5.6-terra',
           **{name: USAGE[name] for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
           'spend': float(text_cost('company-fast', USAGE))}
    row[field] = value
    with pytest.raises(AssertionError):
        assert_spend_record(row, alias='company-fast', usage=USAGE,
                            request_id='request', user_id='user', team_id='team', token='token')


def test_model_info_and_errors_never_return_credentials(offline_client, json_response):
    offline_client.get.side_effect = None
    offline_client.get.return_value = json_response({'data': [{
        'model_name': 'company-fast', 'litellm_params': {'model': PRICES['company-fast']['upstream'], 'api_key': 'private-key'},
        'model_info': PRICES['company-fast'],
    }]})
    assert offline_client.model_prices() == {'company-fast': PRICES['company-fast']}
    assert 'private-key' not in str(offline_client.model_prices())
    with pytest.raises(AssertionError) as error:
        offline_client.expect_json(json_response({'key': 'private-key'}, status=500))
    assert 'private-key' not in str(error.value)


def test_pytest_container_repr_hides_credentials_but_http_auth_still_works():
    key = RedactedKey('private-key')
    assert 'private-key' not in repr({'virtual_key': key})
    assert LiteLLMClient('http://unused.invalid', key).headers['Authorization'] == 'Bearer private-key'
