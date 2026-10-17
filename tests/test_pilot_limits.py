import json
import os
import time
from datetime import datetime, timezone, timedelta

import pytest


def complete(key, *, padding=0):
    return key['client'].post('/v1/chat/completions', json={
        'model': 'company-fast', 'messages': [{'role': 'user',
            'content': 'Reply with exactly: ok.\n' + 'context ' * padding}],
        'max_tokens': 16, 'reasoning_effort': 'none',
    })


def allowed(response):
    assert response.status_code == 200, f'Expected inference HTTP200, got {response.status_code}'
    return response.json()


def denied_budget(response, scope):
    assert response.status_code == 422, f'Expected exhausted {scope} HTTP422, got {response.status_code}'
    message = str(response.json().get('error', {}).get('message', '')).lower()
    assert 'budget' in message and scope in message, 'Wrong budget rejection scope'


def denied_rate(response):
    assert response.status_code == 429, f'Expected gateway HTTP429, got {response.status_code}'
    message = str(response.json().get('error', {}).get('message', '')).lower()
    assert 'team' in message and ('rate limit' in message or 'tpm' in message), 'Not a gateway team limit'


def wait_until(check, *, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise AssertionError('Asynchronous budget/spend condition was not observed before timeout')


@pytest.mark.policy
def test_pilot_policy_is_persisted(admin_client, pilot_identity_factory, pilot_policy):
    ctx = pilot_identity_factory()
    team = admin_client.team_info(ctx['team_id'])['team_info']
    limits = pilot_policy['limits']['team']
    assert team['models'] == pilot_policy['models']
    assert team['max_budget'] == limits['monthly_budget_usd']
    assert team['rpm_limit'] == limits['rpm']
    assert team['tpm_limit'] == limits['tpm']
    assert team['budget_duration'] == '30d'
    reset = datetime.fromisoformat(team['budget_reset_at'].replace('Z', '+00:00'))
    assert timedelta(0) < reset-datetime.now(timezone.utc) <= timedelta(days=31)
    assert (reset.day, reset.hour, reset.minute, reset.second) == (1, 0, 0, 0)
    for uid in ctx['users']:
        budget = admin_client.member_info(ctx['team_id'], uid)['litellm_budget_table']
        assert budget['max_budget'] == pilot_policy['limits']['member']['monthly_budget_usd']
        assert budget['budget_duration'] == '30d'
        reset = datetime.fromisoformat(budget['budget_reset_at'].replace('Z', '+00:00'))
        assert timedelta(0) < reset-datetime.now(timezone.utc) <= timedelta(days=31)
        assert (reset.day, reset.hour, reset.minute, reset.second) == (1, 0, 0, 0)
    for key in ctx['keys']:
        info = admin_client.key_info(key['virtual_key'])
        assert info['max_budget'] is None  # Member budget is not multiplied per key.
    print('P1_POLICY '+json.dumps({'models': team['models'], 'team_usd': team['max_budget'],
          'member_usd': budget['max_budget'], 'rpm': team['rpm_limit'],
          'tpm': team['tpm_limit'], 'team_duration': '30d', 'member_duration': '30d',
          'reset_mode': 'calendar', 'next_reset_utc': team['budget_reset_at']}))


@pytest.mark.live
@pytest.mark.limits
@pytest.mark.parametrize('limit', ['rpm', 'tpm'])
def test_team_rate_limits_are_shared_and_recover(pilot_identity_factory, limit):
    ctx = pilot_identity_factory(team_limits={limit: 2 if limit == 'rpm' else 60})
    keys = ctx['keys']
    padding = 16 if limit == 'tpm' else 0
    allowed(complete(keys[0], padding=padding))
    if limit == 'rpm':
        allowed(complete(keys[2]))  # A different member consumes the same team RPM.
    denied_rate(complete(keys[1], padding=padding))  # Another key cannot bypass the limit.
    # Real recovery on the same team; never reset shared runtime counters.
    time.sleep(65)
    allowed(complete(keys[2], padding=padding))
    print('P1_LIMIT '+json.dumps({'scope': 'team', 'limit': limit,
                                 'shared_keys_members': True, 'recovery': True}))


@pytest.mark.live
@pytest.mark.limits
def test_member_budget_is_shared_across_keys(admin_client, pilot_identity_factory):
    tiny = 0.000001
    ctx = pilot_identity_factory(member_budget=tiny)
    keys = ctx['keys']
    allowed(complete(keys[0]))
    wait_until(lambda: (admin_client.member_info(ctx['team_id'], keys[0]['user_id']).get('spend') or 0) >= tiny)
    denied_budget(complete(keys[0]), 'team')
    denied_budget(complete(keys[1]), 'team')
    allowed(complete(keys[2]))  # Another member has an independent budget.
    print('P1_LIMIT '+json.dumps({'scope': 'member', 'both_keys_denied': True,
                                 'other_member_allowed': True}))


@pytest.mark.live
@pytest.mark.limits
def test_team_budget_blocks_all_members(admin_client, pilot_identity_factory):
    tiny = 0.000001
    ctx = pilot_identity_factory(team_limits={'monthly_budget_usd': tiny}, member_budget=None)
    allowed(complete(ctx['keys'][0]))
    wait_until(lambda: (admin_client.team_info(ctx['team_id'])['team_info'].get('spend') or 0) >= tiny)
    for key in (ctx['keys'][1], ctx['keys'][2]):
        denied_budget(complete(key), 'team')
    print('P1_LIMIT '+json.dumps({'scope': 'team_budget', 'all_members_denied': True}))


@pytest.mark.live
@pytest.mark.limits
def test_key_budget_does_not_block_other_keys(admin_client, pilot_identity_factory):
    tiny = 0.000001
    ctx = pilot_identity_factory(first_key_budget=tiny)
    allowed(complete(ctx['keys'][0]))
    wait_until(lambda: (admin_client.key_info(ctx['keys'][0]['virtual_key']).get('spend') or 0) >= tiny)
    denied_budget(complete(ctx['keys'][0]), 'budget')
    allowed(complete(ctx['keys'][1]))
    print('P1_LIMIT '+json.dumps({'scope': 'key', 'other_key_allowed': True}))


@pytest.mark.live
@pytest.mark.limits
def test_member_budget_window_resets_without_losing_total_spend(admin_client, pilot_identity_factory):
    ctx = pilot_identity_factory(member_budget=0.000001, member_duration='5s')
    key = ctx['keys'][0]
    before = admin_client.member_info(ctx['team_id'], key['user_id'])['litellm_budget_table']['budget_reset_at']
    allowed(complete(key))
    def reset_observed():
        member = admin_client.member_info(ctx['team_id'], key['user_id'])
        budget = member['litellm_budget_table']
        if budget['budget_reset_at'] > before and (member.get('spend') or 0) == 0 and (member.get('total_spend') or 0) > 0:
            return member
        return None
    # Pinned proxy checks due budgets every 597-605s; 5s is the budget window,
    # not the scheduler interval. Keep runtime settings unchanged.
    member = wait_until(reset_observed, timeout=int(os.getenv('E2E_BUDGET_RESET_TIMEOUT', '660')))
    assert member['litellm_budget_table']['max_budget'] == 0.000001
    allowed(complete(ctx['keys'][1]))
    print('P1_LIMIT '+json.dumps({'scope': 'member_reset', 'test_duration': '5s',
                                 'cycle_spend_reset': True, 'total_spend_retained': True}))
