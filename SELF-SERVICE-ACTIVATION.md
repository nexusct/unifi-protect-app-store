# Nexus Vision Self-Service Enrollment and Activation

**Status:** Architecture decision proposal

## Decision

Build two bounded components:

1. A hosted **Nexus Control Plane** for customer identity, organizations, sites, billing state, selected function stacks, enrollment codes, device records, and signed entitlements.
2. A local **Activation Service** inside the Nexus Vision appliance for device identity, entitlement verification, camera/function mapping, validation, atomic configuration changes, restart, readiness checking, and rollback.

The appliance initiates every Internet connection over outbound HTTPS. The control plane never opens an inbound tunnel, receives UniFi credentials, or receives continuous video. All 100 active function implementations remain inside the versioned container image, and all 271 source/archive contracts remain available for migration and audit; activation changes configuration only. Do not download executable Python plug-ins from the control plane.

This is a subscription and lifecycle boundary, not unbreakable DRM. Because customers control their own host and the current repository contains the implementation, a determined operator can patch enforcement. Signed entitlements still provide the right operational, support, billing, and audit mechanism without fragile hardware locking.

## Current product gap

The repository already has most local seams, but they are not connected into a self-service lifecycle:

- The public signup API creates a lead in appliance-local SQLite. It does not create an account, organization, paid subscription, device, or entitlement.
- The marketplace selection tray only downloads YAML.
- The setup wizard is local and protected by `VISION_ADMIN_TOKEN`, but it currently submits an empty `detectors_by_camera` mapping.
- The runtime loads all installed detector and marketplace classes, then instantiates whatever IDs appear in local camera YAML.
- There is no customer identity, billing authority, device enrollment, signed license, entitlement gate, desired-state sync, or activation rollback.

Therefore the hosted signup experience must move outside the customer appliance, while UniFi discovery, credentials, video, camera names, zones, and detector settings stay local.

## Customer journey

1. The customer browses the hosted marketplace and builds a stack before signing in.
2. The portal preserves that draft stack, creates an organization and site after managed OIDC or passwordless authentication, and sends Starter or Professional purchases through hosted checkout. Enterprise remains an approval flow.
3. An idempotent billing webhook changes subscription state. The browser redirect is never treated as payment authority.
4. The portal creates a single-use enrollment code scoped to one organization, site, and draft stack. Store only its hash; expire it after ten minutes; consume it once.
5. The customer installs the signed Linux AMD64 image through Unraid Community Apps or Docker Compose, maps `/config`, `/data`, `/models`, and `/evidence`, sets a strong local admin token, and opens `/setup/` on the trusted LAN.
6. The local administrator enters the enrollment code. The appliance generates a device key pair locally, then exchanges the code and public key with the control plane over outbound TLS.
7. The control plane returns a device identity plus a short-lived signed entitlement. The private device key never leaves `/config`.
8. The local wizard discovers UniFi Protect cameras using local credentials. Nothing in this step is sent to the control plane.
9. The wizard imports the purchased function stack, maps functions to local cameras, captures required zones and settings, and runs a preflight plan.
10. The customer reviews the exact diff and applies it. The appliance writes a new configuration revision atomically, restarts, waits for readiness, and rolls back if startup or detector initialization fails.
11. The appliance periodically renews the signed entitlement and sends only minimal operational metadata: device version, catalog hash, entitlement revision, enabled function IDs, aggregate readiness, and capacity facts. It sends no video, snapshots, UniFi credentials, RTSP URLs, or human-readable camera names by default.

Cloud stack changes should be staged as pending. Enabling a new analytic requires local approval by default because it can change privacy scope, GPU load, zones, and alert behavior. A future administrator-controlled policy may auto-apply safe disables or pre-approved changes.

## Trust boundaries

- **Hosted portal:** user identity, organization membership, checkout, subscription management, site records, and draft function stacks.
- **Control-plane API:** enrollment, device authentication, desired stack, signed entitlement issuance, heartbeat, and audit.
- **Billing provider:** card handling and subscription events. Nexus stores provider identifiers, not card data.
- **Local appliance:** device private key, UniFi credentials, TLS trust material, camera inventory, RTSP URLs, zones, model caches, evidence, and active configuration.
- **UniFi console/NVR:** local camera and Access source; reachable only from the customer network.
- **Signing boundary:** entitlement private key held in KMS/HSM or a dedicated signing service. Portal code must not hold the signing root.

Base44 may host portal UX and ordinary account/site records, but device authentication and entitlement signing should remain a small dedicated service with auditable keys and strict schemas.

## Device identity and enrollment

Do not use MAC address, disk serial, or a mutable hardware fingerprint as the primary identity. They are brittle, privacy-sensitive, and create support failures during legitimate migrations.

On first enrollment, generate an Ed25519 key pair locally. Store the private key owner-only under `/config/device/`; submit only the public key and non-secret capability facts. Exchange the one-time code for a device ID and a certificate or proof-of-possession credential bound to that public key. All later control-plane calls must authenticate the device and reject replayed requests. Re-enrollment and host migration require an authorized portal action and produce an audit event.

## Signed entitlement contract

Use a compact JWS with EdDSA and an explicit versioned schema. The protected header carries a key ID. The payload should contain at least:

```json
{
  "schema": "nexus.entitlement/v1",
  "license_id": "lic_…",
  "organization_id": "org_…",
  "site_id": "site_…",
  "device_id": "dev_…",
  "plan": "professional",
  "status": "active",
  "limits": {
    "sites": 1,
    "streams": 24,
    "distinct_functions": 12
  },
  "function_ids": ["queue-length", "truck-turn-time"],
  "catalog_sha256": "…",
  "revision": 42,
  "issued_at": "2026-08-16T00:00:00Z",
  "not_before": "2026-08-16T00:00:00Z",
  "expires_at": "2026-09-15T00:00:00Z",
  "grace_until": "2026-09-22T00:00:00Z"
}
```

Resolve plan rules into an explicit list of granted function IDs when issuing the entitlement. This prevents a future catalog tier change from silently changing an existing grant. Bind every document to one site and device, pin the catalog hash, increase the revision monotonically, and retain a rotating public verification-key set in the signed appliance image.

Treat entitlement and desired configuration as separate concepts:

- The entitlement states what the site may run.
- The desired stack states which granted IDs the customer wants.
- The local mapping states which cameras, zones, thresholds, schedules, and alert routes use those IDs.

Only the local mapping contains site-sensitive camera data.

## Packaging rules

Use the pricing already published by the site:

| Plan | Site limit | Stream limit | Function limit | Function eligibility |
|---|---:|---:|---:|---|
| Starter | 1 | 8 | 5 distinct IDs | Starter-tier functions |
| Professional | 1 per subscription | 24 | 12 distinct IDs | Any catalog tier, subject to capacity |
| Enterprise | Contract value | Contract value | Contract value | Explicit grants |

A function counts once per site even when it is mapped to multiple cameras. Streams and distinct function IDs are separate limits. The existing vocabulary mismatch must be normalized: billing uses `professional`, while marketplace manifests use the capability tier `pro`.

## Local activation boundary

Add one deep `ActivationService` instead of scattering plan checks across routes and UI code. Its public operations should be small:

```text
enroll(one_time_code) -> DeviceIdentity + Entitlement
status() -> redacted activation state
plan(requested_mapping) -> ActivationPlan
apply(plan_id) -> ActivationResult
refresh() -> Entitlement
```

`plan()` must fail closed unless all of these hold:

1. The entitlement signature, key ID, device binding, time window, catalog hash, and monotonic revision are valid.
2. Every requested function is both explicitly granted and present in the installed registry.
3. Distinct-function, stream, and site limits are satisfied.
4. The host is Linux AMD64; required GPU functions have a compatible NVIDIA runtime and enough measured capacity for the proposed evaluation workload.
5. Every function's required config schema, camera geometry, and site timezone are present and type-valid.
6. Every camera ID came from the most recent verified local Protect discovery.
7. No unknown IDs, extra keys, path references, or executable values enter generated configuration.

The plan response is a redacted diff and a short-lived opaque plan ID, not a client-controlled YAML blob. `apply()` revalidates the plan, writes a versioned staging file, atomically swaps configuration, restarts, waits for fresh frames and detector initialization, and either marks the revision good or restores the prior revision. Preserve at least the last five local revisions and an append-only activation audit log.

Runtime enforcement must not rely on the browser. At startup, verify the cached entitlement and reduce the configured detector IDs to an effective authorized configuration before `build_camera_detectors()` instantiates anything. Unauthorized IDs, forged grants, unsupported hardware, and expired documents must never instantiate paid functions.

Suggested local modules:

```text
src/activation/domain.py          immutable contracts and state transitions
src/activation/device_identity.py key generation, storage, and request proof
src/activation/entitlement.py     JWS verification and lease rules
src/activation/control_plane.py   bounded outbound client
src/activation/planner.py         entitlement + catalog + hardware + config validation
src/activation/store.py           owner-only identity, entitlement, revisions, audit
src/activation/api.py             admin-token-protected local endpoints
```

Keep `marketplace.runtime.build_camera_detectors()` pure. Feed it only the planner's effective configuration.

## Offline and failure behavior

- Renew a 30-day signed lease daily. A temporary control-plane outage should not interrupt on-site analytics.
- Before `expires_at`, use the cached last-known-good entitlement normally.
- Between `expires_at` and `grace_until`, continue the last-known-good mapping, block additions and swaps, and show a prominent local and portal warning.
- After grace, never accept a new activation or restart paid functions without a valid entitlement. The exact policy for stopping an already-running process must be a documented commercial and safety decision; do not silently change it in code.
- If a new entitlement is invalid, older, for another device, or references an unknown catalog hash, reject it and retain the still-valid prior document.
- Persist the greatest accepted server timestamp and revision to detect simple local clock rollback. A fully customer-controlled host cannot provide perfect anti-tamper guarantees.
- If a requested ID is granted but missing from the installed image, report `update_required`; do not download code dynamically or crash the runtime.
- If readiness fails after apply, roll back automatically and keep the failed revision plus a redacted reason.

Enterprise offline sites can later use the same verifier with a portal-downloaded signed `.nexus-license` bundle. That is a second delivery path, not a second licensing model.

## Control-plane records and APIs

Minimum durable records:

- organizations, users, memberships, and roles
- subscriptions and idempotent billing webhook events
- sites and desired function stacks
- devices, public keys, certificate status, and last-seen facts
- hashed enrollment codes with expiry and consumption state
- signed entitlement revisions and their reason
- activation outcomes and security audit events

Minimum device API surface:

```text
POST /v1/device-enrollments/exchange
GET  /v1/device/desired-state
GET  /v1/device/entitlement
POST /v1/device/heartbeat
POST /v1/device/activation-results
```

Enrollment exchange is authorized only by a short-lived single-use code plus proof of the new private key. Every later endpoint requires the device credential. Bound request size, use strict schemas, reject unknown fields, rate-limit by account, IP, code, and device, and make enrollment and billing handlers idempotent.

Portal operations create checkout sessions, manage sites and stacks, issue enrollment codes, revoke or migrate devices, display redacted health, and show the audit trail. They never expose entitlement signing keys or local operational credentials.

## Security and privacy requirements

- Keep port 8090 LAN-only or behind an authenticated customer reverse proxy. Self-service must not require public inbound appliance access.
- Require the existing local admin token for every activation endpoint, including enrollment-code submission.
- Store device private keys, cached entitlements, revisions, and audit files owner-only. Never return private material through status APIs.
- Never log enrollment codes, bearer credentials, private keys, JWS bodies, UniFi passwords, RTSP URLs, connection strings, or checkout secrets.
- Use managed checkout so Nexus never handles card numbers.
- Sign entitlements in KMS/HSM or a dedicated isolated signer; support overlapping verification keys during rotation.
- Verify image provenance separately with signed container images and pinned release digests. Entitlement signatures do not establish image integrity.
- Send no continuous video to the control plane. Make snapshot/evidence forwarding a separate explicit alert-destination choice.
- Avoid hardware serials as identity. Capability facts are advisory input to planning, not authentication secrets.
- Maintain role separation: organization owners manage billing and device enrollment; site administrators map local cameras and apply activation; viewers can inspect status only.
- Treat remote enables as privacy-significant changes and require local confirmation by default.

## Rejected approaches

- **Cloud-to-appliance tunnel or open inbound API:** increases attack surface and conflicts with the local-first boundary.
- **Downloadable executable function plug-ins:** creates a remote-code-execution and supply-chain channel. Ship new function code only in signed images.
- **One API key pasted into every function:** causes secret sprawl and provides no site, device, revision, or audit model.
- **MAC-address or disk-serial licensing:** brittle, spoofable, privacy-sensitive, and hostile to legitimate hardware replacement.
- **Browser-only checks:** trivial to bypass and do not protect runtime startup.
- **Treating checkout redirect as payment success:** vulnerable to replay and false activation; billing webhooks must be authoritative.
- **Sending UniFi credentials or full camera inventory to the cloud:** unnecessary and contrary to the product's privacy promise.

## Delivery sequence

### Phase 1 — local signed-entitlement vertical slice

Implement the entitlement contract, verifier, effective-configuration gate, activation planner, revision store, readiness rollback, redacted local APIs, and tests. Use test signing keys and manually supplied signed fixtures. This proves the hard local boundary before choosing a cloud stack.

### Phase 2 — enrollment control plane

Implement organization/site/device records, one-time enrollment codes, device credentials, desired stacks, signed lease renewal, heartbeat, and an administrative entitlement issuer. No billing is required yet. This supports controlled pilots.

### Phase 3 — customer identity and billing

Add managed OIDC or passwordless login, hosted checkout, customer billing portal, idempotent webhooks, subscription state transitions, and plan-to-grant issuance. Starter and Professional can become self-service; Enterprise remains approved.

### Phase 4 — integrated setup UX

Change the hosted marketplace action from YAML-only generation to `Continue to checkout`, while retaining YAML download for development. Add enrollment, entitled stack, camera mapping, preflight diff, apply, rollback status, and swap flows to `/setup/`.

### Phase 5 — fleet and offline enterprise

Add multi-site fleet views, controlled device migration, signed offline license bundles, staged remote changes, key rotation drills, and documented disaster recovery.

## Required tests

### Entitlement

- valid signature, unknown key, altered payload, wrong device/site, not-yet-valid, expired, grace, revision rollback, catalog mismatch, and clock rollback
- Starter five-function and eight-stream limits; sixth distinct ID rejected
- one function on multiple cameras counts once; cameras still count toward the stream limit
- Professional twelve-function limit and tier eligibility
- unavailable function returns `update_required`

### Enrollment and billing

- enrollment code expires, is stored hashed, is single-use, and rejects replay
- a code for one site cannot enroll another site
- device proof is required and certificate rotation preserves identity
- checkout redirect cannot activate a subscription
- duplicate and out-of-order billing webhooks are idempotent
- canceled, past-due, resumed, migrated, and revoked states issue the intended revision

### Local activation

- forged or unauthorized function IDs never instantiate
- GPU-required functions reject an unsupported host
- stale Protect camera IDs, missing zones, invalid settings, and unknown fields fail before write
- plan IDs expire and cannot be replayed after configuration changes
- writes are atomic; secrets remain owner-only
- failed restart or readiness restores the prior known-good revision
- status and error responses redact credentials, codes, keys, RTSP URLs, and connection strings

### End to end

1. Build a five-function Starter stack, create an account, complete checkout, enroll a fresh appliance, discover eight cameras, map functions, apply, and prove readiness.
2. Attempt a sixth function and a ninth stream; both must fail with useful non-secret errors.
3. Change to Professional, receive a higher entitlement revision, activate twelve functions, and verify the same local device identity.
4. Disconnect the control plane, restart during the valid lease, and verify last-known-good operation.
5. Apply a bad detector setting, force readiness failure, and prove automatic rollback.

## Concrete integration seams in this repository

- Replace the appliance-local lead-only interpretation in `src/subscriptions/` with a hosted control-plane client or keep it only as a development/demo adapter.
- Add the runtime entitlement gate between `main.load_detectors()` and `Pipeline` construction. Loading installed code is allowed; instantiating unauthorized IDs is not.
- Let `SetupService` obtain allowed detector IDs from the current verified entitlement, not the full installed registry.
- Extend `/api/setup/save` into a plan/apply flow rather than accepting a final mapping and immediately replacing the active file.
- Replace the setup page's current `detectors_by_camera: {}` submission with an entitled function-to-camera mapper driven by each manifest's config schema and camera-zone contract.
- Change the hosted marketplace's primary stack action from a raw YAML download to an authenticated draft-stack/checkout handoff. Keep YAML export as an advanced local-development path.
- Add activation status to readiness without exposing license contents or device credentials.
- Sign and pin release images independently from entitlement signing.

## Decisions required before production implementation

1. Billing provider and tax handling. Hosted Stripe Checkout and Customer Portal are the default recommendation.
2. Managed identity provider. Passwordless email plus Microsoft/Google OIDC is the default recommendation; add SAML for Enterprise later.
3. Exact past-due and post-grace runtime policy. It must be explicit, customer-visible, and consistent with contracts.
4. Whether Professional truly permits any catalog tier, as the current pricing page states.
5. Whether the container and GHCR package remain public. Public source means entitlement enforcement is operational rather than strong DRM.
6. Whether remote stack changes always require local approval. Local confirmation is the default recommendation.
7. Whether Base44 hosts only portal workflows or also the control-plane records. Entitlement signing should remain isolated either way.

## First implementable slice

Start with Phase 1 and one vertical acceptance test:

> Given a locally generated device identity and a signed Starter entitlement granting five known function IDs, the appliance plans a valid mapping, rejects a sixth ID, writes one versioned configuration, restarts, proves readiness, and rolls back when the new revision fails.

That slice establishes the difficult security and reliability boundary. Account, checkout, and enrollment can then issue the same entitlement format without redesigning the appliance.
