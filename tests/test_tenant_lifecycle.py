import asyncio

import httpx
import pytest

from media_tenant_keys.lifecycle import (
    InfraiClient,
    MEDIA_SCOPES,
    MediaTenantLifecycle,
    TenantOffboarding,
    TenantProvisioning,
)


async def _check_user_identity_flows_directly_into_scoped_key() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/user/create":
            return httpx.Response(201, json={"ok": True, "data": {"user_id": "usr_media_7"}})
        return httpx.Response(
            201,
            json={"ok": True, "data": {"id": "key_media_7", "key": "issued-once-value"}},
        )

    workflow = MediaTenantLifecycle(
        InfraiClient("test-credential", transport=httpx.MockTransport(handler))
    )
    result = await workflow.provision(
        TenantProvisioning(
            tenant_id="studio-7",
            owner_email="owner@example.com",
            owner_name="Studio Seven",
        )
    )

    key_payload = __import__("json").loads(requests[1].content)
    assert key_payload["project_id"] == "usr_media_7"
    assert key_payload["scopes"] == list(MEDIA_SCOPES)
    assert result.key_id == "key_media_7"


def test_user_identity_flows_directly_into_scoped_key() -> None:
    asyncio.run(_check_user_identity_flows_directly_into_scoped_key())


async def _check_offboarding_attempts_both_account_operations() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.startswith("/v1/auth/user/delete/"):
            raise httpx.ConnectError("simulated client-side interruption", request=request)
        return httpx.Response(200, json={"ok": True, "data": {}})

    workflow = MediaTenantLifecycle(
        InfraiClient("test-credential", transport=httpx.MockTransport(handler))
    )
    with pytest.raises(httpx.ConnectError):
        await workflow.offboard(TenantOffboarding(user_id="usr_8", key_id="key_8"))

    assert sorted(paths) == [
        "/v1/account/keys/revoke/key_8",
        "/v1/auth/user/delete/usr_8",
    ]


def test_offboarding_attempts_both_account_operations() -> None:
    asyncio.run(_check_offboarding_attempts_both_account_operations())
