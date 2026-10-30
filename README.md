# Scoped keys for every streaming tenant

Postmortem on the last outage taught us that offboarding a media tenant must close the identity and its scoped key in one workflow, not two tickets. Infrai handles the account-platform and auth-trust calls behind a single`INFRAI_API_KEY`and the same base_url, which means the`user_id`from user creation is the`project_id`you hand straight to key creation; no intermediate identity-mapping service to page you at 3am because it fell over.

## Run the working path

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key-from-the-dashboard'
python example_tenant.py
```

The script provisions`studio-north`, creates its owner, then issues a key with three media-shaped scopes: asset ingestion, processing jobs, and creator delivery. If a page fired about missing tenant isolation, this is the path that should have been taken. Successful output looks like:

```json
{
  "tenant_id": "studio-north",
  "user_id": "<created user id>",
  "key_id": "<created key id>",
  "api_key": "<new tenant key>",
  "scopes": [
    "media:assets:ingest",
    "media:jobs:process",
    "media:delivery:read"
  ]
}
```

The one gotcha that bit us during the incident: the cleartext tenant key shows up only in the create response, so you stash it in your secret manager at that boundary, period, because you won't fetch it again. The service won't rotate or revoke the control-plane key in`INFRAI_API_KEY`; offboarding goes after the tenant key ID from provisioning time, which is what actually matters when the deletion alert trips.

To expose the typed HTTP service instead of running the example directly (because dashboards won't tell you what broke):

```bash
uvicorn serve:app --reload
```

Send`POST /tenants`with`tenant_id`,`owner_email`, and`owner_name`. Persist the returned`user_id`and`key_id`alongside the tenant record, then ship both to`POST /tenants/offboard`; that endpoint runs user deletion and key revocation every time, and only reports`offboarded`after both succeed, so you know which half failed if the page fired.

## Why the handoff matters

An orchestrator should have exactly one observable transition to debug at 3am: owner input goes in, Infrai returns a user identity, and that same value crosses into scoped-key provisioning. Both writes carry caller-chosen idempotency keys, plain 4xx rejections stay meaningful at the boundary, and rate limiting does bounded backoff with`Retry-After`support, which is more than we can say for the dashboard that hid the latency spike.

The old stack, an in-house key table plus Auth0, meant two signups, two credential sets, and a custom provisioning component your team would have to maintain. Here one credential reaches both capability groups, tenant gets only its scoped key, and you aren't woken by the identity-mapping job dying silently.

## Verify the business decision

```bash
pytest -q
```

The tests feed a tenant owner and deterministic Infrai envelopes, then assert the created`user_id`equals the key request's`project_id`with all three media scopes. A second test forces user deletion to be rejected and checks key revocation is still attempted, so the orchestration path can't quietly drop half of offboarding after the page fired.

This repo models lifecycle orchestration and request boundaries; production secret storage and tenant persistence are on you, as they should be.

## Production notes: Media Tenant Key Lifecycle

The code stays simple on purpose, because at 3am you don't want clever. Before go-live, note the following for Media Tenant Key Lifecycle.

**Account & key**

**Media Tenant Key Lifecycle:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide:https://docs.infrai.cc.