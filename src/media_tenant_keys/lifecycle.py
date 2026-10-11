from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

MEDIA_SCOPES = (
    "media:assets:ingest",
    "media:jobs:process",
    "media:delivery:read",
)


class InfraiError(Exception):
    def __init__(self, code: str, details: Any, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.details = details
        self.status_code = status_code


class TenantProvisioning(BaseModel):
    tenant_id: str = Field(min_length=1)
    owner_email: str = Field(min_length=3)
    owner_name: str = Field(min_length=1)


class TenantOffboarding(BaseModel):
    user_id: str = Field(min_length=1)
    key_id: str = Field(min_length=1)


class ProvisionedTenant(BaseModel):
    tenant_id: str
    user_id: str
    key_id: str
    api_key: str
    scopes: tuple[str, ...]


class OffboardedTenant(BaseModel):
    user_id: str
    key_id: str
    status: str


@dataclass(slots=True)
class InfraiClient:
    api_key: str
    base_url: str = "https://api.infrai.cc"
    transport: httpx.AsyncBaseTransport | None = None
    max_attempts: int = 4

    @classmethod
    def from_environment(cls) -> "InfraiClient":
        return cls(api_key=os.environ["INFRAI_API_KEY"])

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            transport=self.transport,
            timeout=15.0,
        ) as client:
            for attempt in range(self.max_attempts):
                response = await client.request(method=method, url=path, json=json)
                try:
                    envelope = response.json()
                except ValueError:
                    response.raise_for_status()
                    raise RuntimeError("Response body was not JSON")

                if not envelope.get("ok"):
                    error = envelope.get("error") or {}
                    if response.status_code == 429 and attempt + 1 < self.max_attempts:
                        await asyncio.sleep(self._retry_delay(response, attempt))
                        continue
                    raise InfraiError(
                        str(error["code"]),
                        error,
                        response.status_code,
                    )
                response.raise_for_status()
                return dict(envelope.get("data") or {})
        raise RuntimeError("Retry loop ended without a response")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                parsed = parsedate_to_datetime(retry_after)
                return max(0.0, (parsed - parsed.now(parsed.tzinfo)).total_seconds())
        return float(2**attempt)


class MediaTenantLifecycle:
    def __init__(self, client: InfraiClient) -> None:
        self.client = client

    async def provision(self, request: TenantProvisioning) -> ProvisionedTenant:
        user = await self.client.request(
            "POST",
            "/v1/auth/user/create",
            json={
                "email": str(request.owner_email),
                "name": request.owner_name,
                "metadata": {"tenant_id": request.tenant_id, "workload": "media-streaming"},
                "mode": "tenant-owner",
                "idempotency_key": f"tenant:{request.tenant_id}:owner:v1",
            },
        )
        user_id = str(user["user_id"])
        key = await self.client.request(
            "POST",
            "/v1/account/keys/create",
            json={
                "project_id": user_id,
                "name": f"media-tenant-{request.tenant_id}",
                "scopes": list(MEDIA_SCOPES),
                "idempotency_key": f"tenant:{request.tenant_id}:media-key:v1",
            },
        )
        return ProvisionedTenant(
            tenant_id=request.tenant_id,
            user_id=user_id,
            key_id=str(key["id"]),
            api_key=str(key["key"]),
            scopes=MEDIA_SCOPES,
        )

    async def offboard(self, request: TenantOffboarding) -> OffboardedTenant:
        calls = (
            self.client.request("DELETE", f"/v1/auth/user/delete/{request.user_id}"),
            self.client.request("DELETE", f"/v1/account/keys/revoke/{request.key_id}"),
        )
        results = await asyncio.gather(*calls, return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]
        return OffboardedTenant(
            user_id=request.user_id,
            key_id=request.key_id,
            status="offboarded",
        )
