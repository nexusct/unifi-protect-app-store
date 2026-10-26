# Nexus Vision 105-function portfolio audit

**Decision date:** 2026-08-29
**Publication arithmetic:** 100 − 25 + 30 = **105 active functions**
**Compatibility inventory:** 271 + 30 = **301 source/archive contracts**

The machine-readable decision record is [`super-skill-portfolio.json`](super-skill-portfolio.json). Retired contracts remain loadable through `load_all(include_archived=True)`; retirement changes publication only.

## Decision criteria

Retire duplicated presets, raw platform plumbing, low-actionability diagnostics, technically weak proxies, and claim-risky labels. Add composite, stateful, evidence-first workflows that use anonymous tracks, zones, schedules, Protect events, and optional Access context.

## Exactly 25 retirements

| # | ID | Rationale |
|---:|---|---|
| 1 | `mandated-camera-check` | Duplicates camera-tamper and estate-level scene-health checks; its first-frame baseline is too narrow for a standalone product. |
| 2 | `protect-camera-discovery-failure-log` | Low-level discovery telemetry is consolidated into vision-estate-health. |
| 3 | `protect-event-poll-health` | Low-level poll telemetry is consolidated into vision-estate-health. |
| 4 | `rtsp-decode-error-rate` | A raw stream metric better presented as one fleet maintenance priority. |
| 5 | `rtsp-frame-gap-watch` | Overlaps connectivity, freeze, and quality analysis and is consolidated into vision-estate-health. |
| 6 | `rtsp-rolling-quality-digest` | A bundle of low-level stream metrics superseded by an explainable fleet-health workflow. |
| 7 | `snapshot-last-good-frame` | An incident-support implementation detail rather than a distinct buyer outcome. |
| 8 | `protect-camera-unnamed-records` | Configuration hygiene with little standalone commercial value. |
| 9 | `protect-event-camera-reference-audit` | Reference hygiene belongs in estate readiness, not a separate SKU. |
| 10 | `clip-export-daily-manifest` | A reporting derivative of existing checksum, integrity, and index capabilities. |
| 11 | `clip-export-queue` | Internal export job state rather than a customer outcome. |
| 12 | `motion-event-clip-export` | Duplicates retained generic and smart-event pre/post-roll export functions. |
| 13 | `floor-water-change-review` | Blue-excess and reflection heuristics are too lighting- and material-sensitive to support a water-oriented SKU. |
| 14 | `unusual-motion-baseline` | Global frame-difference energy is noise-prone and is superseded by zone- and schedule-conditioned baselining. |
| 15 | `hallway-overnight` | A vertical preset of retained after-hours person detection. |
| 16 | `forecourt-loiter` | A vertical preset of retained loitering analytics. |
| 17 | `laundromat-overnight` | A narrow preset of retained after-hours and loitering functions. |
| 18 | `magnet-crane-exclusion` | Near-duplicate of crane-exclusion without observing crane or magnet state. |
| 19 | `splash-pad-capacity` | A narrow duplicate of retained crowd and occupancy counting. |
| 20 | `machine-monopoly` | Generic zone dwell without evidence of machine use or availability. |
| 21 | `child-safety-zone` | Bounding-box height is an unreliable age proxy and creates avoidable claim risk. |
| 22 | `aggression-posture` | Raised-arm motion cannot reliably establish aggression or intent. |
| 23 | `vehicle-attribute-log` | Arbitrary domain-label logging lacks a bounded operational workflow. |
| 24 | `assembly-stage-order-review` | A camera-global sequence is superseded by a per-track configurable cycle-step workflow. |
| 25 | `curbside-arrival` | Arrival-only detection is superseded by an end-to-end handoff timer. |

## Exactly 30 super skills

| # | ID | Category | Tier | Workflow |
|---:|---|---|---|---|
| 1 | `secured-exit-approach-review` — Secured Exit Approach Review | Healthcare & Senior Living | pro | `secured_exit` |
| 2 | `room-exit-sequence-review` — Room Exit Sequence Review | Healthcare & Senior Living | enterprise | `room_exit_sequence` |
| 3 | `mobility-aid-egress-obstruction` — Mobility-Aid Egress Obstruction Review | Healthcare & Senior Living | pro | `mobility_obstruction` |
| 4 | `controlled-room-two-person-review` — Controlled-Room Person-Count Review | Healthcare & Senior Living | enterprise | `controlled_room_count` |
| 5 | `care-area-occupancy-imbalance` — Care-Area Occupancy Imbalance | Healthcare & Senior Living | pro | `occupancy_imbalance` |
| 6 | `waiting-room-flow-ledger` — Waiting-Room Flow Ledger | Healthcare & Senior Living | pro | `waiting_flow` |
| 7 | `vision-estate-health` — Vision Estate Health | Security & Access | enterprise | `estate_health` |
| 8 | `perimeter-event-verifier` — Perimeter Event Verifier | Security & Access | pro | `perimeter_verify` |
| 9 | `multi-zone-intrusion-progression` — Multi-Zone Intrusion Progression Review | Security & Access | enterprise | `intrusion_progression` |
| 10 | `package-room-chain-review` — Package-Room Chain Review | Security & Access | enterprise | `package_chain` |
| 11 | `after-hours-multi-camera-corroboration` — After-Hours Multi-Camera Corroboration | Security & Access | enterprise | `multi_camera_corroboration` |
| 12 | `door-alarm-observed-response-timer` — Door Alarm Observed Response Timer | Security & Access | enterprise | `door_response` |
| 13 | `anonymous-zone-funnel` — Anonymous Zone Funnel | Retail & QSR | pro | `zone_funnel` |
| 14 | `queue-service-rate-digest` — Queue Service Rate Digest | Retail & QSR | pro | `queue_service` |
| 15 | `curbside-handoff-timer` — Curbside Handoff Timer | Retail & QSR | pro | `curbside_handoff` |
| 16 | `drive-thru-lane-balance` — Drive-Thru Lane Balance | Retail & QSR | enterprise | `lane_balance` |
| 17 | `table-reset-delay-review` — Table Reset Delay Review | Retail & QSR | pro | `table_reset` |
| 18 | `high-traffic-service-trigger` — High-Traffic Service Trigger | Retail & QSR | pro | `traffic_trigger` |
| 19 | `dock-stage-turnaround` — Dock Stage Turnaround | Manufacturing & Warehouse | pro | `dock_turnaround` |
| 20 | `dock-apron-conflict-review` — Dock Apron Conflict Review | Manufacturing & Warehouse | enterprise | `trajectory_conflict` |
| 21 | `forklift-route-deviation-review` — Forklift Route Deviation Review | Manufacturing & Warehouse | enterprise | `domain_route` |
| 22 | `aisle-blockage-duration-review` — Aisle Blockage Duration Review | Manufacturing & Warehouse | pro | `persistent_obstruction` |
| 23 | `cycle-step-timer` — Cycle Step Timer | Manufacturing & Warehouse | enterprise | `domain_sequence` |
| 24 | `yard-queue-bottleneck-digest` — Yard Queue Bottleneck Digest | Manufacturing & Warehouse | pro | `yard_queue` |
| 25 | `multi-class-flow-ledger` — Multi-Class Flow Ledger | Intelligence | pro | `multi_class_flow` |
| 26 | `anonymous-space-utilization-percentiles` — Anonymous Space Utilization Percentiles | Intelligence | pro | `space_utilization` |
| 27 | `route-completion-ledger` — Route Completion Ledger | Intelligence | pro | `route_completion` |
| 28 | `zone-activity-schedule-baseline` — Zone Activity Schedule Baseline | Intelligence | pro | `schedule_baseline` |
| 29 | `shift-change-flow-review` — Shift Change Flow Review | Intelligence | pro | `shift_flow` |
| 30 | `exception-evidence-casebook` — Exception Evidence Casebook | Intelligence | enterprise | `evidence_casebook` |

## Safety and implementation boundary

- No face recognition, biometric identity, emotion inference, or cross-visit identity.
- Outputs describe observed evidence for human review; they are not legal, clinical, life-safety, or intent determinations.
- Domain-model workflows fail silently when required weights are missing or unreadable.
- Resident-room workflows remain compatible with skeleton privacy mode and snapshot suppression.
- No super skill controls a door, vehicle, production machine, or life-safety system.

## First-party commercial evidence

- **axis-object:** [AXIS Object Analytics scenarios](https://www.axis.com/products/axis-object-analytics/scenarios)
- **axis-retail:** [Axis retail optimization](https://www.axis.com/insights/topics/retail-optimization)
- **axis-entry:** [AXIS Camera Station Secure Entry](https://www.axis.com/en-us/products/axis-camera-station-secure-entry)
- **hanwha-retail:** [Hanwha Vision Retail & Business AI Pack](https://www.hanwhavision.com/global/news-events/article/1588310)
- **hanwha-factory:** [Hanwha Vision factory and safety analytics](https://www.hanwhavision.com/global/news-events/article/1574355)
- **avigilon:** [Avigilon video analytics](https://www.avigilon.com/analytics)
- **genetec:** [Genetec Security Center](https://www.genetec.com/products/unified-security/security-center)
- **genetec-crowd:** [Genetec crowd estimation](https://www.genetec.com/blog/products/crowd-estimation-keeping-count-with-video-analytics)
- **verkada-occupancy:** [Verkada Occupancy Trends dashboard](https://www.verkada.com/blog/new-occupancy-trends-dashboard/)
- **iqsight-traffic:** [IQSIGHT IVA Pro Traffic](https://www.iqsight.com/en/products/video-analytics/iva-pro-traffic/mvc-iva-tra)
- **iqsight-buildings:** [IQSIGHT IVA Pro Buildings](https://www.iqsight.com/en/products/video-analytics/iva-pro-buildings/mvc-iva-bld)

Competitor material validates buyer problem patterns only. Nexus implementations are independent and use no vendor code, models, or output formats.
