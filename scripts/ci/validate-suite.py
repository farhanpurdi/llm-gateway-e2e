#!/usr/bin/env python3

from __future__ import annotations

import ast
import sys
from pathlib import Path


TEST_DIR = Path("tests")


REQUIRED_TESTS = {
    "test_litellm_is_alive",
    "test_user_can_see_expected_models",
    "test_invalid_key_is_rejected",
    "test_company_fast_inference",
    "test_company_coding_inference",
    "test_streaming",
    "test_tool_calling",
    "test_team_policy_changes_without_key_rotation",
    "test_spend_is_attributed_to_user",
    "test_blocked_key_is_rejected",
    "test_team_rpm_limit_is_enforced",
    "test_key_budget_is_enforced",
    "test_multiple_user_keys_work_before_offboarding",
    "test_user_offboarding_blocks_all_keys",
    "test_pilot_policy_is_persisted",
    "test_team_rate_limits_are_shared_and_recover",
    "test_member_budget_is_shared_across_keys",
    "test_team_budget_blocks_all_members",
    "test_key_budget_does_not_block_other_keys",
    "test_member_budget_window_resets_without_losing_total_spend",
    "test_opencode_onboarding_uses_developer_key",
    "test_opencode_agent_reads_edits_runs_and_uses_tool_result",
    "test_fault_injection_parameters_are_rejected",
    "test_dependency_outage_preserves_denials_and_recovers",
    "test_virtual_key_rotation_preserves_scope_and_audit",
}


def fail(message: str) -> None:
    print(
        f"ERROR: {message}",
        file=sys.stderr,
    )
    sys.exit(1)


if not TEST_DIR.exists():
    fail("tests directory not found")


test_files = sorted(
    TEST_DIR.rglob("test_*.py")
)


if not test_files:
    fail("no test files found")


print(
    f"Found {len(test_files)} test file(s)"
)


discovered_tests: set[str] = set()


for path in test_files:
    print(f"Inspecting: {path}")

    try:
        source = path.read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            source,
            filename=str(path),
        )

    except SyntaxError as exc:
        fail(
            f"Python syntax error in "
            f"{path}: {exc}"
        )

    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            if node.name.startswith(
                "test_"
            ):
                discovered_tests.add(
                    node.name
                )


missing_tests = (
    REQUIRED_TESTS
    - discovered_tests
)


if missing_tests:
    fail(
        "required regression test(s) "
        "missing: "
        + ", ".join(
            sorted(missing_tests)
        )
    )


print()
print(
    f"Discovered "
    f"{len(discovered_tests)} "
    "test function(s)"
)

print(
    "Required regression tests: PASS"
)
