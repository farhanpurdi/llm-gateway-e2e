from __future__ import annotations

from typing import Any

import requests


class RedactedKey(str):
    """Keep HTTP behavior while hiding credentials in pytest/container reprs."""
    def __repr__(self):
        return '<redacted credential>'


class GatewayTransportError(RuntimeError):
    """Transport diagnostics must never echo credential-bearing URLs or bodies."""


class LiteLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = RedactedKey(api_key)
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": RedactedKey(f"Bearer {self.api_key}"),
            "Content-Type": "application/json",
        }

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        try:
            return requests.get(
                f"{self.base_url}{path}",
                headers=self.headers,
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise GatewayTransportError(
                f"Gateway GET transport failed: {type(error).__name__}; details suppressed"
            ) from None

    def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        try:
            return requests.post(
                f"{self.base_url}{path}",
                headers=self.headers,
                json=json,
                stream=stream,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise GatewayTransportError(
                f"Gateway POST transport failed: {type(error).__name__}; details suppressed"
            ) from None

    def expect_json(
        self,
        response: requests.Response,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        if response.status_code != expected_status:
            raise AssertionError(
                f"Expected HTTP {expected_status}, "
                f"got {response.status_code}; response body suppressed"
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
                "does not contain team_id."
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

    def team_info(self, team_id: str) -> dict[str, Any]:
        return self.expect_json(self.get('/team/info', params={'team_id': team_id}))

    def member_info(self, team_id: str, user_id: str) -> dict[str, Any]:
        matches = [row for row in self.team_info(team_id)['team_memberships']
                   if row.get('user_id') == user_id]
        if len(matches) != 1:
            raise AssertionError('Expected exactly one matching team membership')
        return matches[0]

    def key_info(self, virtual_key: str) -> dict[str, Any]:
        return self.expect_json(self.get('/key/info', params={'key': virtual_key}))['info']

    def model_prices(self) -> dict[str, dict[str, Any]]:
        """Return only public pricing fields; /model/info can contain credentials."""
        data = self.expect_json(self.get('/model/info'))
        result = {}
        for entry in data['data']:
            name = entry.get('model_name')
            if name not in {'company-fast', 'company-coding'}:
                continue
            info = entry.get('model_info') or {}
            result[name] = {
                'upstream': entry.get('litellm_params', {}).get('model'),
                **{field: info.get(field) for field in (
                    'input_cost_per_token', 'output_cost_per_token',
                    'cache_read_input_token_cost')},
            }
        return result

    def list_user_keys_page(
        self,
        *,
        user_id: str,
        page: int = 1,
        size: int = 100,
    ) -> dict[str, Any]:
        if not user_id or not user_id.strip():
            raise ValueError("user_id must not be empty")

        if page < 1:
            raise ValueError("page must be >= 1")

        if not 1 <= size <= 100:
            raise ValueError("size must be between 1 and 100")

        response = self.get(
            "/key/list",
            params={
                "user_id": user_id,
                "page": page,
                "size": size,
                "return_full_object": "true",
                "include_team_keys": "false",
                "include_created_by_keys": "false",
            },
        )

        if response.status_code != 200:
            raise AssertionError(
                "Cannot list user keys: "
                f"HTTP {response.status_code}"
            )

        return response.json()

    def list_user_keys(
        self,
        *,
        user_id: str,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        results = []
        seen_tokens = set()

        page = 1
        expected_total = None
        expected_pages = None

        while True:
            data = self.list_user_keys_page(
                user_id=user_id,
                page=page,
                size=page_size,
            )

            total_count = data["total_count"]
            total_pages = data["total_pages"]

            if data["current_page"] != page:
                raise AssertionError("Unexpected key-list page")

            if expected_total is None:
                expected_total = total_count
                expected_pages = total_pages
            elif (
                total_count != expected_total
                or total_pages != expected_pages
            ):
                raise AssertionError(
                    "Key count changed during pagination; "
                    "retry discovery before offboarding"
                )

            for item in data["keys"]:
                if item.get("user_id") != user_id:
                    raise AssertionError(
                        "Key discovery returned another user's key"
                    )

                token = item.get("token")

                if not isinstance(token, str) or not token:
                    raise AssertionError(
                        "Key discovery returned no token identifier"
                    )

                if token in seen_tokens:
                    raise AssertionError(
                        "Duplicate key encountered during pagination"
                    )

                seen_tokens.add(token)
                results.append(item)

            if page >= total_pages:
                break

            if not data["keys"]:
                raise AssertionError(
                    "Empty page before the end of key discovery"
                )

            page += 1

        if len(results) != expected_total:
            raise AssertionError(
                "Incomplete key discovery: "
                f"expected={expected_total}, "
                f"received={len(results)}"
            )

        return results

    def offboard_user_keys(
        self,
        *,
        user_id: str,
        page_size: int = 100,
    ) -> dict[str, Any]:
        keys = self.list_user_keys(
            user_id=user_id,
            page_size=page_size,
        )

        blocked_count = 0
        errors = []

        for index, item in enumerate(keys, start=1):
            label = f"key #{index}"

            try:
                response = self.post(
                    "/key/block",
                    json={
                        "key": item["token"],
                    },
                )

                if response.status_code != 200:
                    errors.append(
                        f"{label}: HTTP {response.status_code}"
                    )
                    continue

                data = response.json()

                if (
                    data.get("token") != item["token"]
                    or data.get("user_id") != user_id
                ):
                    errors.append(
                        f"{label}: unexpected key identity in response"
                    )
                    continue

                if data.get("blocked") is not True:
                    errors.append(
                        f"{label}: blocked status was not confirmed"
                    )
                    continue

                blocked_count += 1

            except Exception as exc:
                errors.append(
                    f"{label}: {type(exc).__name__}"
                )

        if errors:
            raise AssertionError(
                "Offboarding incomplete: "
                f"confirmed={blocked_count}/{len(keys)}. "
                + "; ".join(errors)
            )

        return {
            "user_id": user_id,
            "discovered_count": len(keys),
            "blocked_count": blocked_count,
        }

    def list_user_spend_logs_page(
        self,
        *,
        user_id: str,
        start_date: str,
        end_date: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        if not user_id or not user_id.strip():
            raise ValueError("user_id must not be empty")

        if page < 1:
            raise ValueError("page must be >= 1")

        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")

        response = self.get(
            "/spend/logs/v2",
            params={
                "user_id": user_id,
                "start_date": start_date,
                "end_date": end_date,
                "page": page,
                "page_size": page_size,
            },
        )

        if response.status_code != 200:
            raise AssertionError(
                "Cannot read user spend history: "
                f"HTTP {response.status_code}"
            )

        return response.json()
