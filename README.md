# UniFi Protect Function Marketplace (Nexus Vision)

An open function marketplace for UniFi Protect NVRs. Connect through a scoped,
local Protect account, pick the GPU-accelerated functions your business
needs, and process continuous video on your own premises. Configured alerts can
send metadata or snapshots; no new cameras or per-camera AI hardware required.

**100 functions across 9 business categories**, plus 10 safety-oriented core
detectors. Built and maintained by [Nexus Communications Technology](https://nexusct.com),
Schaumburg, IL.

## What's here

| Path | What it is |
|---|---|
| `storefront/` | The marketplace UI — 100 active module cards with image artwork, filters, add-to-stack controls, and subscription YAML generation. Serve from the repository root so shared assets resolve. |
| `assets/icons/` | 100 repository-owned SVG module images, a deterministic image fallback, and an icon manifest. |
| `scripts/build_marketplace_catalog.py` | Validates literal manifests and regenerates `catalog.json` plus the static `catalog.js` data layer. |
| `scripts/generate_marketplace_icons.py` | Regenerates the complete icon set from the validated marketplace catalog. |
| `landing/` | The subscription landing page — pricing tiers, problem/solution, signup form. Served at `/` by the container. |
| `src/subscriptions/` | Subscription platform — SQLite store, signup/status/admin endpoints, and optional Base44 sales-pipeline forwarding. |
| `src/marketplace/` | The function library + plug-in contract + loader. Each function is one self-describing module with a `MANIFEST` (id, name, tier, category, config schema). |
| `src/detectors/` | 10 safety-oriented core detectors (fall, bed-exit, weapon, smoke…). Site calibration and human review remain required. |
| `src/` engine | RTSP stream manager, UniFi Protect + Access API clients, alert engine with dedup/severity routing, FastAPI status/search server. |
| `Dockerfile`, `docker-compose.yml` | GPU (`--profile gpu`) and CPU (`--profile cpu`) deployments. |

## Marketplace function catalog

**Retail & QSR** — Queue Length Monitor · Shelf Stockout Alert · Zone Dwell
Analytics · Unacknowledged Customer Alert · Footfall & Occupancy Counter ·
Drive-Thru Service Timer · Table Turn Tracker

**Manufacturing & Warehouse** — Shared-Lane Vehicle Motion Alert · Safety Zone Breach ·
Machine-Zone Motion-Energy Summary · Dock Door Utilization · Staging Object Count ·
Conveyor Stalled-Object Review · Truck Yard Dwell Estimate

**Property & Liability** — Possible Fall Review · Fire Exit Blocked ·
Low-Luminance Lighting Watch · Camera View Change Alert · White-Coverage Walkway Watch ·
Door-Zone Baseline Change

**Automotive & Parking** — Lot Occupancy · EV Charger Blocked ·
Vehicle-Stall Change Review · Curbside Pickup Arrival

**Compliance** — Sink-Stop Sequence Check · Uniform Color-Signature Check ·
Pest Watch (after-hours)

**People & Safety** — Persistent Object Review · Crowd Density Alert ·
Raised-Arm Motion Review · Small-Person Restricted-Zone Alert ·
Wrong-Way Movement

**Intelligence** — Repeat Appearance Pattern (appearance-similarity clustering, not identity matching) · Vendor Arrival
Verification · Service Response Time

**Security & Access** — After-Hours Activity · After-Hours Supply-Zone Activity · Site Theft Watch · Per-Tenant After-Hours Watch

## 30 more: vertical expansion pack (v2)

**Healthcare & Clinics** — Waiting Room Overflow · Clinical-Attire Color Check ·
Pharmacy Window Queue · MRI Approach Presence Alert · Specimen Drop-Zone Dwell Log

**Education & Fitness** — Hall Pass Monitor · Lone Small-Figure Playground Alert ·
Bus Loop Safety · Studio Attendance Estimate · Equipment Usage Analytics

**Logistics & Fleet** — Trailer Yard Dwell · Gate Cycle Time ·
Trailer Rear-State Change · Driver-in-Cab Activity Alert · Service Bay Queue

**Hospitality** — Pool-Area Person Count · Pool Stillness Review ·
Housekeeping Pace Tracker · Banquet Setup Verification

**Office & CRE** — Meeting Room Reality · Desk Utilization Map ·
Lobby Visitor Flow · Per-Tenant After-Hours Watch

**Agriculture** — Pen Motion Watch · After-Hours Supply-Zone Activity · Canopy Hue-Shift Watch

**Banking** — ATM Vestibule Watch · Teller Line Pace

**Construction** — Site Theft Watch · Crane Exclusion-Zone Presence Alert

## 10 more: Access ↔ Protect cross-system pack (v3)

These modules correlate UniFi Access door events with what the correlated
Protect camera observed. They read the shared access-event buffer through
`src/marketplace/access.py`, which normalizes the Access side (event kind,
identity, timestamp, credential method) into one vocabulary. Without Access
credentials the event buffer stays empty and every module idles — no alerts
and no inference. None of them identify people or use face recognition, and
none of them send an unlock command; door control stays on the authenticated
`/unlock` route.

| Module | Access input | Protect input |
|---|---|---|
| Verified Door Incident Timeline | any door event | person counts in the review window |
| Credential-to-Crossing Correlation | explicit credential grants | directional doorway crossings |
| Forced/Held-Open Video Verification | door-state alarms | people, vehicles, objects, dwell |
| Denied-Access Escalation | repeated denied credentials | person count, approach dwell |
| Access Incident Search Index | door, kind, method, timestamp | observed counts, bounded local index |
| Access Event Evidence Package | original event id + metadata | observed counts, review history |
| After-Hours Entry Verification | grants outside configured hours | count, direction, vehicle, proximity |
| Occupancy Reconciliation | credentialed passages | directional line counts |
| Visitor Entry Review Context | doorbell / entry request | person, carried item, vehicle |
| Door Operation Verification | unlock command | doorway crossing, door-zone change |

**100 marketplace functions total**: the 80 highest-scoring existing functions plus 20 independently implemented vendor-pattern plugins. Retired implementations remain available only through the explicit source-archive loader for migration and audit.

## Turnkey Unraid deployment

The supplied container and templates target **Linux AMD64** (standard x86-64
Unraid servers). Other processor architectures require separate platform builds
and are not supported by this image.

Choose one template:

- `unraid/nexus-vision-ai-cpu.xml` — onboarding, image health, Protect-event
  analytics, reporting, and small evaluation workloads.
- `unraid/nexus-vision-ai-gpu.xml` — continuous detector, pose, tracking, and
  embedding workloads. Install the Unraid NVIDIA Driver plugin first and use a
  host driver compatible with CUDA 12.1.

Both templates pull `ghcr.io/nexusct/unifi-protect-app-store:latest`, use bridge
networking, run without privileged mode, and map these persistent directories:

| Unraid host path | Container path | Contents |
|---|---|---|
| `/mnt/user/appdata/nexus-vision-ai/config` | `/config` | Site YAML, owner-only runtime credentials, trusted controller certificates, public entitlement verification keys, and appliance-bound license state |
| `/mnt/user/appdata/nexus-vision-ai/data` | `/data` | SQLite state, durable alert outbox, analytics indexes |
| `/mnt/user/appdata/nexus-vision-ai/models` | `/models` | Torch, Ultralytics, OpenCLIP, OCR, and custom-weight caches |
| `/mnt/user/appdata/nexus-vision-ai/evidence` | `/evidence` | Permitted snapshots, clips, and exports |

The committed entitlement trust-store template is intentionally empty and therefore
deny-all. Before activating paid functions on a customer appliance, Nexus must
provision the current **public verification keys** at
`/config/trusted-entitlement-keys.json`; Compose and both Unraid templates set
`VISION_ENTITLEMENT_TRUST_STORE` to that persistent path and keep appliance
identity, entitlement, and rollback state under `/config/licensing`.
Never place private signing keys in the image, container environment, customer
mount, or Railway variables. If the trust store is missing, malformed, or does
not recognize the entitlement key ID, paid analytics and physical control remain
disabled.

The public Railway deployment is a deliberately unlicensed storefront and lead
management plane. It serves the landing page, guide, setup documentation, catalog,
and signup API without UniFi credentials, analytics streams, or door-control
authority. Customer analytics run only on the separately deployed local appliance.

At install time, enter a long random `VISION_ADMIN_TOKEN`; keep the optional
door-control token different. Start the container, open `/setup/`, and then:

1. Enter the administrator token, site name, and IANA timezone.
2. Enter the local UniFi console/NVR hostname and a dedicated Protect account.
3. Use system TLS trust, explicitly review and pin the controller certificate,
   or mount a private CA under `/config/certs`. TLS and authentication failures
   fail closed.
4. Discover cameras, select only RTSP/S-enabled feeds, save, and restart.
5. Verify `/ready`; saving configuration alone is not a readiness pass.

The container requires LAN access to the console/NVR over HTTPS `443` and to
enabled Protect RTSP/S feeds on `7441`. Initial model acquisition can require
outbound HTTPS unless all selected weights are already present in `/models`.
Do not expose port 8090 directly to the Internet.

## Quick start

```bash
# .env is optional; create it only for alert destinations or to override values.
cp .env.example .env
docker compose --profile gpu up -d   # NVIDIA runtime required
docker compose --profile cpu up -d   # onboarding/event analytics/evaluation
# Local Compose binds 8090 to loopback: http://127.0.0.1:8090/setup/
```

Set `site.timezone` in `config/sites.yaml` to the facility's IANA timezone
(for example, `America/Chicago`). Scheduled windows and daily summaries use
that timezone and follow daylight-saving transitions.

The container serves three surfaces on port 8090:

| Route | What |
|---|---|
| `/` | Subscription landing page (pricing, signup) |
| `/setup/` | Authenticated first-run Protect connection and feed discovery |
| `/guide/` | 8-step implementation guide (hardware, zones, tuning, writing functions) |
| `/storefront/` | Function marketplace catalog (filter + sort by category, name, or plan tier) |
| `/api/subscriptions` | Public signup API (POST); status/list/update operations require the admin token |
| `/health`, `/streams`, `/detectors`, `/search` | Runtime + NL video search |

Signups land in the container's SQLite store and can forward to your Base44
sales pipeline when `BASE44_ALERT_URL` +
`BASE44_INTERNAL_TOKEN` are set.
Subscription status, list, and status-update routes are disabled until a strong
`VISION_ADMIN_TOKEN` is configured. Send it only in the `x-admin-token` header;
it is separate from the Base44 forwarding token.

Storefront preview:

```bash
python3 -m http.server 8080
# → http://localhost:8080/storefront/
```

## UniFi Protect setup

1. Protect console → enable RTSP on each camera (per-camera `rtsps://` alias).
2. Create a read-only Protect local user; put console host + creds in `.env`.
   `unifi_protect.py` discovers cameras and maps RTSP URLs from the bootstrap API —
   omit `rtsp:` in sites.yaml and it resolves automatically.
   TLS verification is enabled by default. For a private controller CA, set
   `UNIFI_PROTECT_VERIFY_SSL` or `UNIFI_ACCESS_VERIFY_SSL` to the absolute CA-bundle path;
   disable verification only in an isolated lab.
3. UniFi Access (optional): a local admin token in `.env` supports door-event
   correlation. Remote unlock additionally requires a non-placeholder
   `VISION_CONTROL_TOKEN` bearer token. Docker Compose publishes the API on
   localhost by default; put any wider exposure behind authenticated network controls.

## Alert destinations

- **Base44 (Nexus NOC):** POSTs to a function that writes NocAlert /
  FieldMessage records (`BASE44_ALERT_URL` + `BASE44_INTERNAL_TOKEN`).
- **Generic JSON webhook or integration relay:** `EXTRA_WEBHOOK_URL`.
- Dedup + severity routing per function in `sites.yaml → alerts:`.

## Hardware sizing

- **Compact x86 RTX appliance** at the edge: benchmark for the selected stream mix.
- **x86 RTX/L4 server** in the MDF: benchmark for the selected stream mix.
- `VISION_FRAME_INTERVAL` (default 1.0s) is the GPU-load dial.

The supplied image targets `linux/amd64`. ARM targets require a separate,
platform-specific PyTorch build and are not supported by this image.

Benchmark model, resolution, decoder load, function mix, and alert volume before production sizing.

## Compliance stance

- **Illinois BIPA posture:** the current design does not use face recognition or
  biometric identity matching. It may process pose and appearance-similarity
  signals; deployment owners remain responsible for privacy counsel, legal review,
  retention policy, and site notice requirements.
- **Local by default:** continuous video is processed on the on-site GPU
  appliance. Configured alerts may send metadata or snapshots to approved
  destinations; continuous video is not forwarded to Nexus.

## Writing your own function

```python
# src/marketplace/functions/my_function.py
from marketplace.contract import MarketplaceFunction, boxes_of

MANIFEST = {
    "id": "my-function",
    "name": "My Function",
    "tagline": "What it does in one honest sentence.",
    "category": "People & Safety",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {"zone": "polygon — watch area"},
}

class Function(MarketplaceFunction):
    def process(self, camera, frame, ts, ctx):
        for (cls, cx, cy, *_r, tid) in boxes_of(frame, classes=[0]):
            ctx.alerts.fire(site=ctx.site, camera=camera,
                            detector=MANIFEST["id"], title="Person seen",
                            detail="...", frame=frame)
```

Drop the file in `src/marketplace/functions/`, then regenerate the checked-in
catalog and artwork before rebuilding:

```bash
python3 scripts/build_marketplace_catalog.py
python3 scripts/generate_marketplace_icons.py
```

The Docker build runs both steps again, validates the manifests, and refuses
duplicate or malformed module IDs.
