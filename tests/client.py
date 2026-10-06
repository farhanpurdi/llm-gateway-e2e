from __future__ import annotations

from typing import Any

import requests


class LiteLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        return requests.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            params=params,
            timeout=self.timeout,
        )

    def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        return requests.post(
            f"{self.base_url}{path}",
            headers=self.headers,
            json=json,
            stream=stream,
            timeout=self.timeout,
        )

    def expect_json(
        self,
        response: requests.Response,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        if response.status_code != expected_status:
            raise AssertionError(
                f"Expected HTTP {expected_status}, "
                f"got {response.status_code}\n"
                f"Response: {response.text}"
            )

        return response.json()

    def create_team(
        self,
        *,
        team_alias: str,
        models: list[str],
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        max_budget: float | None = None,
        budget_duration: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "team_alias": team_alias,
            "models": models,
        }

        if rpm_limit is not None:
            payload["rpm_limit"] = rpm_limit

        if tpm_limit is not None:
            payload["tpm_limit"] = tpm_limit

        if max_budget is not None:
            payload["max_budget"] = max_budget

        if budget_duration is not None:
            payload["budget_duration"] = budget_duration

        response = self.post(
            "/team/new",
            json=payload,
        )

        data = self.expect_json(
            response,
            expected_status=200,
        )

        team_id = data.get("team_id")

        if not team_id:
            raise AssertionError(
                "LiteLLM /team/new response "
                "does not contain team_id.\n"
                f"Response: {data}"
            )

        if rpm_limit is not None:
            actual_rpm = data.get("rpm_limit")

            if actual_rpm != rpm_limit:
                raise AssertionError(
                    "Team rpm_limit was not persisted. "
                    f"requested={rpm_limit}, "
                    f"actual={actual_rpm}"
                )

        if tpm_limit is not None:
            actual_tpm = data.get("tpm_limit")

            if actual_tpm != tpm_limit:
                raise AssertionError(
                    "Team tpm_limit was not persisted. "
                    f"requested={tpm_limit}, "
                    f"actual={actual_tpm}"
                )

        return data