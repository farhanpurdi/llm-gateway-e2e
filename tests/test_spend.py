import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.accounting import PRICES, assert_spend_record, text_cost


@pytest.mark.live
@pytest.mark.spend
@pytest.mark.parametrize('alias', ['company-fast', 'company-coding'])
def test_spend_is_attributed_to_user(admin_client, pilot_identity_factory, alias):
    """Match provider response to persisted tokens, cost, key, member, user and team."""
    assert admin_client.model_prices() == PRICES, 'Active prices/mapping differ from official test snapshot'
    ctx = pilot_identity_factory()
    start = (datetime.now(timezone.utc)-timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
    requests = []
    for key in (ctx['keys'][0], ctx['keys'][2]):
        response = key['client'].post('/v1/chat/completions', json={
            'model': alias, 'messages': [{'role': 'user', 'content': 'Reply with exactly: ok.'}],
            'max_tokens': 16, 'reasoning_effort': 'none', 'service_tier': 'default',
        })
        assert response.status_code == 200, f'Expected inference HTTP200, got {response.status_code}'
        body = response.json()
        assert body.get('service_tier', 'default') == 'default', 'Scenario requires standard pricing'
        usage = body['usage']
        # Pinned LiteLLM stores the provider response ID, not x-litellm-call-id.
        request_id = body.get('id')
        assert request_id, 'Provider response identifier missing'
        expected = text_cost(alias, usage)
        key_alias = admin_client.key_info(key['virtual_key'])['key_alias']
        token = next(item['token'] for item in admin_client.list_user_keys(user_id=key['user_id'])
                     if item['key_alias'] == key_alias)
        requests.append({'key': key, 'token': token, 'request_id': request_id,
                         'usage': usage, 'expected': expected})

    end = (datetime.now(timezone.utc)+timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
    deadline = time.monotonic()+45
    rows = {}
    while time.monotonic() < deadline:
        for item in requests:
            page = admin_client.list_user_spend_logs_page(
                user_id=item['key']['user_id'], start_date=start, end_date=end)
            assert not page.get('total_is_capped', False)
            assert page['total'] == len(page['data']), 'Unexpected history pagination/truncation'
            matches = [row for row in page['data'] if row.get('request_id') == item['request_id']]
            assert len(matches) <= 1, 'Duplicate request in spend history'
            if matches:
                rows[item['request_id']] = matches[0]
        if len(rows) == len(requests):
            break
        time.sleep(1)
    expected_count = len(requests)
    assert len(rows) == expected_count, 'Spend records did not persist before deadline'

    expected_total = Decimal(0)
    for item in requests:
        expected_total += assert_spend_record(
            rows[item['request_id']], alias=alias, usage=item['usage'],
            request_id=item['request_id'], user_id=item['key']['user_id'],
            team_id=ctx['team_id'], token=item['token'])

    # Request rows and aggregate counters flush asynchronously and separately.
    deadline = time.monotonic()+45
    aggregates_match = False
    while time.monotonic() < deadline:
        actual = []
        for item in requests:
            uid = item['key']['user_id']
            user = admin_client.expect_json(admin_client.get('/user/info', params={'user_id': uid}))['user_info']
            actual.extend([
                (admin_client.key_info(item['key']['virtual_key']).get('spend'), item['expected']),
                (admin_client.member_info(ctx['team_id'], uid).get('spend'), item['expected']),
                (user.get('spend'), item['expected']),
            ])
        actual.append((admin_client.team_info(ctx['team_id'])['team_info'].get('spend'), expected_total))
        aggregates_match = all(value is not None and abs(Decimal(str(value))-expected) <= Decimal('0.00000001')
                               for value, expected in actual)
        if aggregates_match:
            break
        time.sleep(1)
    assert aggregates_match, 'Key/member/user/team aggregates differ from request cost'
    print('P1_ACCOUNTING '+json.dumps({
        'alias': alias, 'upstream': PRICES[alias]['upstream'], 'requests': len(requests),
        'tokens': [item['usage'] for item in requests],
        'expected_usd': float(expected_total),
        'stored_usd': sum(rows[item['request_id']]['spend'] for item in requests),
        'key_member_user_team_match': True,
    }))
