"""Run via docker exec -i existing-gateway python -; no server or provider I/O."""


def main():
    import asyncio
    import copy
    import json
    import logging
    from pathlib import Path
    from unittest.mock import AsyncMock, patch

    logging.disable(logging.CRITICAL)
    import litellm
    import yaml
    from litellm.proxy._types import ProxyException, UserAPIKeyAuth
    from litellm.proxy.common_request_processing import ProxyBaseLLMRequestProcessing
    from litellm.proxy.proxy_server import openai_exception_handler
    from starlette.requests import Request

    config = yaml.safe_load(Path("/app/config.yaml").read_text())
    retries = config["litellm_settings"]["num_retries"]
    assert retries == 2, "Reviewed retry setting changed"
    aliases = {entry["model_name"] for entry in config["model_list"]}
    assert aliases == {"company-fast", "company-coding"}

    async def run():
        results = []
        for alias in sorted(aliases):
            for kind, kwargs, status in (
                ("rate_limit", {"mock_response": "litellm.RateLimitError"}, 429),
                ("server_error", {"mock_response": "litellm.InternalServerError"}, 500),
                ("timeout", {"mock_response": "unused", "mock_timeout": True, "timeout": 0.01}, 408),
            ):
                caught = None
                try:
                    await litellm.acompletion(
                        model="openai/gpt-5.6-terra" if alias == "company-fast" else "openai/gpt-5.6-sol",
                        api_key="native-probe-no-secret", num_retries=0,
                        messages=[{"role": "user", "content": "Native fault probe."}], **kwargs,
                    )
                except Exception as error:
                    caught = error
                assert caught is not None and caught.status_code == status, "SDK fault was not observed"
                processor = ProxyBaseLLMRequestProcessing(data={"model": alias, "metadata": {}})
                logger = type("FailureLogger", (), {
                    "post_call_failure_hook": AsyncMock(return_value=None),
                    "post_call_response_headers_hook": AsyncMock(return_value={}),
                })()
                translated = None
                try:
                    await processor._handle_llm_api_exception(
                        caught, UserAPIKeyAuth(user_id="native-fixture", team_id="native-fixture"), logger)
                except ProxyException as error:
                    translated = error
                assert translated is not None, "Native proxy did not translate the error"
                request = Request({"type": "http", "method": "POST", "path": "/v1/chat/completions", "headers": []})
                response = await openai_exception_handler(request, translated)
                body = json.loads(response.body)
                assert response.status_code == status and isinstance(body.get("error"), dict)
                assert body["error"].get("type") and body["error"].get("message")
                assert "choices" not in body
                results.append({"alias": alias, "case": kind, "http_status": response.status_code,
                                "error_type": body["error"]["type"], "scope": "native-sdk-and-proxy-handler"})

        models = copy.deepcopy(config["model_list"])
        for entry in models:
            entry["litellm_params"]["api_key"] = "native-probe-no-secret"
        router = litellm.Router(model_list=models, num_retries=retries, retry_after=0)
        for kind, exception_type, failures, expect_success, expected_attempts in (
            ("transient_500", litellm.InternalServerError, 2, True, 3),
            ("persistent_500", litellm.InternalServerError, 9, False, 3),
            ("transient_429", litellm.RateLimitError, 2, True, 3),
            ("persistent_429", litellm.RateLimitError, 9, False, 3),
            ("transient_timeout", litellm.Timeout, 2, True, 3),
            ("persistent_timeout", litellm.Timeout, 9, False, 3),
            ("bad_request", litellm.BadRequestError, 9, False, 1),
        ):
            attempts = 0

            async def upstream(*args, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts <= failures:
                    raise exception_type(message="Controlled native fault", model="company-fast", llm_provider="openai")
                return litellm.ModelResponse(model="company-fast")

            succeeded = False
            metadata = {"model_group": "company-fast"}
            with patch("asyncio.sleep", new=AsyncMock()):
                try:
                    await router.async_function_with_retries(
                        original_function=upstream, model="company-fast", num_retries=retries, metadata=metadata)
                    succeeded = True
                except exception_type:
                    pass
            assert succeeded is expect_success and attempts == expected_attempts, "Native retry contract changed"
            assert metadata["attempted_retries"] == expected_attempts - 1, "Retry metadata differs from actual calls"
            results.append({"case": kind, "attempts": attempts, "succeeded": succeeded,
                            "scope": "native-router-fault-boundary"})
        router.discard()
        print(json.dumps({"status": "PASS", "num_retries": retries, "cases": results,
                          "provider_requests": 0, "gateway_config_changed": False}))

    asyncio.run(run())


if __name__ == "__main__":
    main()
