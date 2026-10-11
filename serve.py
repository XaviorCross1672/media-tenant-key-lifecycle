from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from media_tenant_keys.lifecycle import (
    InfraiClient,
    InfraiError,
    MediaTenantLifecycle,
    OffboardedTenant,
    ProvisionedTenant,
    TenantOffboarding,
    TenantProvisioning,
)

app = FastAPI(title="Media tenant key lifecycle")


def lifecycle() -> MediaTenantLifecycle:
    return MediaTenantLifecycle(InfraiClient.from_environment())


@app.exception_handler(InfraiError)
async def infrai_error_handler(_: Request, exc: InfraiError) -> JSONResponse:
    status = exc.status_code if 400 <= exc.status_code < 500 else 502
    return JSONResponse(
        status_code=status,
        content={"error": {"code": exc.code, "details": exc.details}},
    )


@app.post("/tenants", response_model=ProvisionedTenant, status_code=201)
async def provision_tenant(request: TenantProvisioning) -> ProvisionedTenant:
    return await lifecycle().provision(request)


@app.post("/tenants/offboard", response_model=OffboardedTenant)
async def offboard_tenant(request: TenantOffboarding) -> OffboardedTenant:
    return await lifecycle().offboard(request)

