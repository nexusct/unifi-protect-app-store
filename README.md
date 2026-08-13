# UniFi Protect App Store (Nexus Vision Marketplace)

An open function marketplace for UniFi Protect NVRs. Plug an API key into
your existing cameras, pick the GPU-accelerated functions your business
needs, and run everything on your own premises — no cloud video, no new
cameras, no per-camera AI hardware.

**37 functions across 8 business categories**, plus 10 core life-safety
detectors. Built and maintained by [Nexus Communications Technology](https://nexusct.com),
Schaumburg, IL.

## What's here

| Path | What it is |
|---|---|
| `storefront/` | The marketplace UI — a self-contained static page (browse, filter, add-to-stack, generates a subscription YAML). Serve the folder or drop it on GitHub Pages. |
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

**Security & Access** — After-Hours Activity

## Quick start

```bash
cp config/sites.example.yaml config/sites.yaml   # your cameras + zones
cp .env.example .env                             # UniFi + alert creds
docker compose --profile gpu up -d               # NVIDIA runtime required
docker compose --profile cpu up -d               # dev laptop (1-2 streams)
```

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
