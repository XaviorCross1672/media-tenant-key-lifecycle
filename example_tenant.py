import asyncio
import json

from media_tenant_keys.lifecycle import InfraiClient, MediaTenantLifecycle, TenantProvisioning


async def main() -> None:
    workflow = MediaTenantLifecycle(InfraiClient.from_environment())
    tenant = await workflow.provision(
        TenantProvisioning(
            tenant_id="studio-north",
            owner_email="chenhua@changba.com",
            owner_name="Studio North",
        )
    )
    print(json.dumps(tenant.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
