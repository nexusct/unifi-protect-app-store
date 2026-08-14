# UniFi Protect App Store (Nexus Vision Marketplace)

An open function marketplace for UniFi Protect NVRs. Plug an API key into
your existing cameras, pick the GPU-accelerated functions your business
needs, and run everything on your own premises — no cloud video, no new
cameras, no per-camera AI hardware.

**120 functions across 9 business categories**, plus 10 core life-safety
detectors. Built and maintained by [Nexus Communications Technology](https://nexusct.com),
Schaumburg, IL.

## What's here

| Path | What it is |
|---|---|
| `storefront/` | The marketplace UI — a self-contained static page (browse, filter, add-to-stack, generates a subscription YAML). Serve the folder or drop it on GitHub Pages. |
| `landing/` | The subscription landing page — pricing tiers, problem/solution, signup form. Served at `/` by the container. |
| `src/subscriptions/` | Subscription platform — SQLite store, signup/status/admin endpoints, forwards signups into the Base44 sales pipeline as scored hot leads. |
| `src/marketplace/` | The function library + plug-in contract + loader. Each function is one self-describing module with a `MANIFEST` (id, name, tier, category, config schema). |
| `src/detectors/` | 10 core life-safety detectors (fall, bed-exit, weapon, smoke…). |
| `src/` engine | RTSP stream manager, UniFi Protect + Access API clients, alert engine with dedup/severity routing, FastAPI status/search server. |
| `Dockerfile`, `docker-compose.yml` | GPU (`--profile gpu`) and CPU (`--profile cpu`) deployments. |

## The 37 marketplace functions

**Retail & QSR** — Queue Length Monitor · Shelf Stockout Alert · Zone Dwell
Analytics · Unacknowledged Customer Alert · Footfall & Occupancy Counter ·
Drive-Thru Service Timer · Table Turn Tracker

**Manufacturing & Warehouse** — Forklift Speed Governor · Safety Zone Breach ·
Machine Idle Watch (visual OEE) · Dock Door Utilization · Pallet Count ·
Conveyor Jam Detector · Truck Turn Time

**Property & Liability** — Slip & Fall Liability Guard · Fire Exit Blocked ·
Lighting Outage Watch · Camera Tamper Detection · Snow & Ice Watch ·
Door Propped Open

**Automotive & Parking** — Lot Occupancy · EV Charger Blocked ·
Vehicle Damage Scan · Curbside Pickup Arrival

**Compliance** — Hand Hygiene Compliance · Uniform Compliance Check ·
Pest Watch (after-hours)

**People & Safety** — Loitering Watch · Abandoned Object Detection ·
Crowd Density Alert · Aggression Early-Warning · Child Safety Zone ·
Wrong-Way Movement

**Intelligence** — Repeat Visitor Pattern (BIPA-safe) · Vendor Arrival
Verification · Service Response Time

**Security & Access** — After-Hours Activity · Supply Theft Watch · Site Theft Watch · Per-Tenant After-Hours Watch

## 30 more: vertical expansion pack (v2)

**Healthcare & Clinics** — Waiting Room Overflow · Clinical Zone Access Check ·
Pharmacy Window Queue · MRI Zone IV Safety · Specimen Drop Verification

**Education & Fitness** — Hall Pass Monitor · Playground Alone Alert ·
Bus Loop Safety · Class Attendance Counter · Equipment Usage Analytics

**Logistics & Fleet** — Trailer Yard Dwell · Gate Cycle Time ·
Trailer Seal Check · Driver-in-Cab Dock Interlock · Service Bay Queue

**Hospitality** — Pool Bather Load · Pool Distress Watch ·
Housekeeping Pace Tracker · Banquet Setup Verification

**Office & CRE** — Meeting Room Reality · Desk Utilization Map ·
Lobby Visitor Flow · Per-Tenant After-Hours Watch

**Agriculture** — Livestock Down Alert · Supply Theft Watch · Canopy Visual Health

**Banking** — ATM Vestibule Watch · Teller Line Pace

**Construction** — Site Theft Watch · Crane Exclusion Zone

**120 marketplace functions total** (verified: 120/120 register with zero errors).

## Quick start

```bash
cp config/sites.example.yaml config/sites.yaml   # your cameras + zones
cp .env.example .env                             # UniFi + alert creds
docker compose --profile gpu up -d               # NVIDIA runtime required
docker compose --profile cpu up -d               # dev laptop (1-2 streams)
```

The container serves three surfaces on port 8090:

| Route | What |
|---|---|
| `/` | Subscription landing page (pricing, signup) |
| `/guide/` | 8-step implementation guide (hardware, zones, tuning, writing functions) |
| `/storefront/` | Function marketplace catalog (filter + sort by vertical / name / service level) |
| `/api/subscriptions` | Signup API (POST), status (GET /{id}), admin (token-gated) |
| `/health`, `/streams`, `/detectors`, `/search` | Runtime + NL video search |

Signups land in the container's SQLite store AND forward to your Base44
sales pipeline as scored hot leads when `BASE44_ALERT_URL` +
`BASE44_INTERNAL_TOKEN` are set.

Storefront preview:

```bash
python3 -m http.server 8080 --directory storefront
# → http://localhost:8080
```

## UniFi Protect setup

1. Protect console → enable RTSP on each camera (per-camera `rtsps://` alias).
2. Create a read-only Protect local user; put console host + creds in `.env`.
   `unifi_protect.py` discovers cameras and maps RTSP URLs from the bootstrap API —
   omit `rtsp:` in sites.yaml and it resolves automatically.
3. UniFi Access (optional): local admin token in `.env` unlocks door-event
   correlation (tailgating, vendor verification) and remote unlock.

## Environment Variables

All configuration is via environment variables in `.env` (copy from `.env.example`).

### UniFi Protect (Required)

| Variable | Description | Example |
|---|---|---|
| `UNIFI_PROTECT_HOST` | IP or hostname of UniFi Protect console | `192.168.1.10` |
| `UNIFI_PROTECT_PORT` | HTTPS port (default 443) | `443` |
| `UNIFI_PROTECT_USERNAME` | Local user (read-only recommended) | `vision-readonly` |
| `UNIFI_PROTECT_PASSWORD` | Password for the Protect user | `secure-password` |
| `UNIFI_PROTECT_VERIFY_SSL` | Verify SSL certificates (`true`/`false`) | `true` (recommended) |

**Security**: Create a dedicated **read-only local user** in UniFi Protect. Do not use admin credentials. Enable SSL verification (`true`) in production — see [SECURITY.md](SECURITY.md) for details on self-signed certificates.

### UniFi Access (Optional)

| Variable | Description | Example |
|---|---|---|
| `UNIFI_ACCESS_HOST` | IP or hostname of UniFi Access controller | `192.168.1.10` |
| `UNIFI_ACCESS_TOKEN` | Local API token (generate in Access console) | `your-access-token` |
| `UNIFI_ACCESS_VERIFY_SSL` | Verify SSL certificates (`true`/`false`) | `true` (recommended) |

Required only for door event correlation (tailgating detection, vendor verification) and remote unlock features.

### Alert Destinations (Optional)

| Variable | Description | Example |
|---|---|---|
| `BASE44_ALERT_URL` | Nexus Base44 alert ingestion endpoint | `https://nexusct.com/api/functions/nexusVisionIngest` |
| `BASE44_INTERNAL_TOKEN` | Internal auth token for Base44 | `your-internal-token` |
| `EXTRA_WEBHOOK_URL` | Additional webhook (Slack, Teams, custom) | `https://hooks.slack.com/services/...` |

Alerts are logged locally by default. Configure these to forward alerts to external systems. Leave blank to disable.

### Runtime Configuration

| Variable | Description | Default |
|---|---|---|
| `VISION_DEVICE` | Compute backend: `cuda` or `cpu` | `cuda` |
| `VISION_FRAME_INTERVAL` | Seconds between frame analysis (GPU load dial) | `1.0` |
| `VISION_DATA` | Data directory for snapshots, clips, DB (container path) | `/app/data` |
| `VISION_ADMIN_TOKEN` | Bearer token for admin API endpoints | `change-me` |
| `VISION_CONFIG` | Path to sites.yaml config file (container path) | `/app/config/sites.yaml` |

**Security**: Treat `VISION_ADMIN_TOKEN` as a password. The system enforces minimum 16-character tokens and rejects the default "change-me" value. Generate a strong random token:
```bash
openssl rand -hex 32
```

Mount `VISION_DATA` to a host volume in docker-compose.yml for persistence (default: `./data`).

### Rate Limiting

Built-in rate limits protect public and admin endpoints from abuse:

| Endpoint | Rate Limit | Purpose |
|---|---|---|
| `POST /api/subscriptions` (signup) | 5/minute per IP | Prevent spam signups |
| `GET /api/subscriptions/{id}` (status) | 30/minute per IP | Prevent enumeration |
| `GET /api/subscriptions` (admin list) | 10/minute per IP | Prevent brute-force |
| `PATCH /api/subscriptions/{id}` (admin) | 20/minute per IP | Prevent brute-force |
| `POST /unlock/{door_id}` | 5/minute per IP | Prevent unauthorized unlocks |
| `GET /search` (video search) | 30/minute per IP | Prevent resource exhaustion |

Rate limits are IP-based. Configure `X-Forwarded-For` handling in your reverse proxy if deploying behind NAT.

## Alert destinations

- **Base44 (Nexus NOC):** POSTs to a function that writes NocAlert /
  FieldMessage records (`BASE44_ALERT_URL` + `BASE44_INTERNAL_TOKEN`).
- **Any webhook:** `EXTRA_WEBHOOK_URL` (Slack/Teams/whatever).
- Dedup + severity routing per function in `sites.yaml → alerts:`.

## Hardware sizing

- **Jetson Orin** at the edge: 4–10 streams.
- **RTX/L4 server** in the MDF: 15–40 streams.
- `VISION_FRAME_INTERVAL` (default 1.0s) is the GPU-load dial.

## Compliance stance

- **Illinois BIPA:** no face recognition, no biometric identification.
  Skeletons, objects, plates, and counts only.
- **On-prem everything:** video never leaves the building; the GPU
  appliance (Jetson or RTX-class) sits next to the NVR.

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

Drop the file in `src/marketplace/functions/`, rebuild, and it's in the
catalog. The loader validates the manifest and refuses broken modules.
