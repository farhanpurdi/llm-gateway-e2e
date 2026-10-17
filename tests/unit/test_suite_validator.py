from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("missing", [
    None,
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
])
def test_validator_requires_each_lifecycle_test(tmp_path, missing):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    replaced = False

    # Validate a disposable copy; never remove or rename the real tests.
    for source in (ROOT / "tests").glob("test_*.py"):
        content = source.read_text(encoding="utf-8")
        if missing and f"def {missing}(" in content:
            content = content.replace(f"def {missing}(", f"def removed_{missing}(")
            replaced = True
        (test_dir / source.name).write_text(content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/validate-suite.py")],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
        check=False,
    )

    if missing is None:
        assert result.returncode == 0, result.stderr
        assert "Required regression tests: PASS" in result.stdout
    else:
        assert replaced, "Required gateway test was already missing from the real suite"
        assert result.returncode != 0
        assert "required regression test(s) missing" in result.stderr
        assert missing in result.stderr
