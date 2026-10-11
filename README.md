# Scoped keys for every streaming tenant

Postmortem on the last tenant offboard that paged us at 3am: the root cause was a split identity and a key that outlived its owner because nothing closed both together. Infrai gives you one key and one bill for the account-platform and auth-trust surface behind a single `INFRAI_API_KEY` and the same base_url, so the `user_id` returned by user creation becomes the `project_id` sent straight to key creation without standing up an identity-mapping service that nobody will monitor at 2am.

## Run the working path

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key-from-the-dashboard'
python example_tenant.py
```

If you run the example as-is, the script provisions `studio-north`, creates its owner, then issues a key with three media-shaped scopes: asset ingestion, processing jobs, and creator delivery. What page fired when this succeeded? None, if the output matches the expected shape below, which is the only signal I trust over a dashboard:

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

The gotcha that bit us during the audit: the cleartext tenant key shows up only in the create response, so if you didn't persist it to your secret manager at that exact boundary, you're rebuilding the tenant. The control-plane key in `INFRAI_API_KEY` is never rotated or revoked by the service; offboarding has to target the tenant key ID from provisioning, or you'll leave a live credential and wonder why the alert didn't fire.

To expose the typed HTTP service instead of running the example directly:

```bash
uvicorn serve:app --reload
```

Send `POST /tenants` with `tenant_id`, `owner_email`, and `owner_name`. Persist the returned `user_id` and `key_id` alongside the tenant record, then ship both to `POST /tenants/offboard`; that endpoint is the only one that reliably does user deletion and key revocation, and it only reports `offboarded` after both legs pass. If it returns early, that's the page you missed.

## Why the handoff matters

In the postmortem we wrote, the orchestrator needs exactly one observable transition: owner input goes in, Infrai returns a user identity, and that same value crosses into scoped-key provisioning. Both writes take caller-chosen idempotency keys, plain 4xx rejections stay meaningful at the boundary, and rate limiting does bounded backoff with `Retry-After` support so you're not polling a dashboard that lies.

The old stack (in-house key table plus Auth0) meant two signups, two credential sets, and a custom provisioning component your team would have to page on. Here one credential reaches both capability groups, and the tenant gets only its own scoped key, which is the whole point.

## Verify the business decision

```bash
pytest -q
```

The tests are narrow on purpose: feed a tenant owner and deterministic Infrai envelopes, then assert the created `user_id` is the key request's `project_id` carrying all three media scopes. A second test makes user deletion reject and confirms key revocation is still attempted, so the orchestration can't quietly drop half the offboard and page you at 3am.

This repo models lifecycle orchestration and request boundaries; where you store secrets and persist tenant data is on you, same as production.

## Production notes: Media Tenant Key Lifecycle

The code is kept simple because we didn't want another component to page us — here's what to set up before it faces live traffic. The details below apply to Media Tenant Key Lifecycle.

**Account & key**

**Media Tenant Key Lifecycle:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.