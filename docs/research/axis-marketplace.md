# Axis ACAP and application ecosystem: independently implementable plugin patterns

**Research snapshot:** 2026-08-17
**Scope:** Current Axis Communications first-party analytics, ACAP, and Axis Technology Integration Partner offerings that reveal commercially validated problem patterns relevant to Nexus Vision.
**Constraint:** Research only. This report proposes independent problem-level implementations; it does not recommend copying partner code, models, names, user interfaces, protocols, or claims.

## Executive summary

Axis positions ACAP as an open application platform for deploying and integrating edge applications across cameras, speakers, access-control products, and radar, with edge/server/cloud hybrid designs intended to reduce bandwidth, storage, and server requirements.[1] Axis also directs customers from its analytics portfolio to a Technology Partner Finder for compatible software, hardware, and services.[2][4]

The strongest transferable lesson is not “put every model on the camera.” It is to package a narrow detector with the operational workflow that creates value: schedules and zones, persistent state, event correlation, evidence clips, dashboards or exports, and a buyer-specific alert. The 15 patterns below are already sold as named solutions in the Axis ecosystem. Several have unusually strong commercialization signals: more than 4,000 deployed counting cameras, retail deployments in 24 countries, and a field-proven campus speed program.[5][6][8] Other disclosed signals include more than 30,000 traffic-analytics channels and security-health monitoring on well over 100,000 cameras.[9][24]

For Nexus Vision, the best near-term opportunities are **camera-estate health**, **external-event evidence packages**, **multi-class flow KPIs**, **parking-stall state**, **PPE workflow packaging**, and **perimeter alarm verification**. They fit the existing camera inventory, RTSP, tracking, zone/line, Protect event, clip-export, and alert primitives with limited new model work. Environmental sensing, manufacturing SOP analysis, and visual quality inspection are commercially credible but require calibration or domain-specific weights.

## How to read “commercially proven”

The Axis Partner Finder is an official Axis-hosted directory, but Axis explicitly says solution descriptions are supplied by the partners and are neither provided nor endorsed by Axis.[4] Accordingly, this report uses three proof levels:

- **Deployed proof:** the Axis-hosted partner page discloses quantified deployments, countries, channels, or a named field deployment.
- **Established-market proof:** the page gives operating history, certification, or broad market adoption but no deployment count.
- **Current commercial listing:** a named, currently marketed solution is present in the Axis Technology Integration Partner directory, but the page does not disclose quantitative adoption. This proves commercial availability, not efficacy.

All performance, scale, and benefit statements below are attributed to those Axis-hosted, partner-supplied pages. They should be validated in customer discovery before entering a Nexus roadmap.

## Ecosystem map: ACAP versus built-in Axis analytics

### ACAP is the platform, not a single analytic

ACAP is Axis's open platform for developing, deploying, and integrating applications on supported edge devices. Axis describes both fully edge-based and hybrid applications that combine camera, local-server, and cloud execution.[1][2] A solution can therefore be part of the Axis application ecosystem without being an ACAP package, and an ACAP application can still depend on a first-party Axis analytic or an external service.

### First-party/built-in Axis capabilities

Axis's current first-party analytics portfolio includes AXIS Object Analytics, AXIS Audio Analytics, AXIS Image Health Analytics, and AXIS License Plate Verifier.[2] AXIS Object Analytics is preinstalled at no extra cost on compatible cameras and detects, classifies, tracks, and counts humans and vehicles at the edge.[2] Its current scenarios are object-in-area, directional line crossing, time-in-area/dwell, crossline counting, occupancy-in-area, tailgating detection, and hard-hat detection, with hard-hat detection marked beta in the current page.[3]

These capabilities should not be presented as third-party marketplace discoveries. They are the baseline against which a Nexus plugin must add workflow or vertical value. For example:

- “Person loitering in a polygon” is baseline object/time-in-area logic, not a differentiated product.
- “Directional people count” becomes a commercial plugin when it adds schedules, multiple count groups, historical KPIs, exports, and a retail or municipal workflow.
- “Plate read” becomes a commercial plugin when it adds retention controls, vehicle attributes, gate/yard reconciliation, evidence, and an auditable action.
- “Camera obstruction” becomes a commercial service when combined with estate inventory, uptime, storage/recording checks, compliance reports, and maintenance routing.

### Third-party and partner solutions

A page is marked **ACAP confirmed** below only when the Axis-hosted partner page explicitly says the application runs on-camera via ACAP. **Embedded/edge** means the page says on-device processing but does not explicitly use the ACAP label. **Ecosystem integration** means the solution uses Axis streams, events, or products but is described as server, cloud, or otherwise not confirmed as an ACAP package.

## Priority matrix

| # | Pattern | Axis deployment form | Nexus fit | Build disposition |
|---|---|---|---|---|
| 1 | Multi-class directional flow KPIs | ACAP confirmed | High | Generalize existing counters |
| 2 | Privacy-safe in-store shopper funnel | Edge ecosystem integration | High | Extend dwell/zone tracking |
| 3 | Parking-stall occupancy, dwell, and enforcement | ACAP optional/hybrid | High | Extend lot occupancy |
| 4 | Speed-event evidence package | ACAP confirmed, depends on radar/LPV | Medium | Add event/evidence workflow; do not claim certified speed measurement |
| 5 | Automatic road-incident detection | ACAP confirmed or server | High | Compose tracking, direction, dwell, queues, clips |
| 6 | LPR/OCR transport identity event | ACAP confirmed | Medium | Extend existing ALPR with generic OCR/event contract |
| 7 | PPE rule matrix and escalation | ACAP confirmed | High | Productize existing PPE detector |
| 8 | Visible smoke/flame/thermal anomaly escalation | Embedded/ACAP ecosystem | High for visible smoke/flame | Productize existing detector; certification boundary required |
| 9 | Perimeter alarm verification | ACAP confirmed or server | High | Compose zone/dwell/track/event evidence |
| 10 | Camera-based water level and flow monitoring | Embedded edge | Medium-low | New calibrated environmental model |
| 11 | Weather and environmental scene hazards | ACAP confirmed | Medium | Extend snow/ice and visual scene-quality primitives |
| 12 | Manual-production cycle and SOP analytics | Edge ecosystem integration | Medium | New sequence/timing layer over tracking |
| 13 | Visual assembly and defect checks | Ecosystem integration | Medium-low | Requires product-specific weights/templates |
| 14 | External-event pre/post evidence | Ecosystem integration | Very high | Compose events, clip export, metadata, alerts |
| 15 | Camera-estate health and compliance | Ecosystem integration | Very high | Compose inventory, snapshots, stream/storage checks, alerts |

## 15 commercially validated plugin patterns

### 1. Multi-class directional flow KPIs

- **Exact commercial capability:** TrafficCounter runs as an ACAP application, uses Axis Object Analytics to classify people, vehicles, and bicycles crossing configured lines, separates counts into scheduled groups and destinations, sends real-time data to retail or city platforms, and provides live/historical web reporting.[5]
- **Buyer / vertical:** Retail operations, shopping centers, municipalities, transit agencies, and traffic planners.
- **Commercial value:** One camera becomes a low-infrastructure flow sensor for staffing, footfall trends, mode-share analysis, and capacity planning. The strongest disclosed proof signal is more than 4,000 cameras deployed across Europe and more than 18 years in Axis-based analytics.[5]
- **Source URL:** [Axis partner page — People and vehicle counting](https://www.axis.com/partner-finder/think-and-make-di-andriano-rocco-giuseppe).[5]
- **Non-infringing Nexus concept:** **Flow Ledger** — use Nexus `boxes_of`, scoped track IDs, `crossed_line`, schedules, and per-camera aggregation to emit directional counts by generic object class. Add CSV/webhook summaries and retention-safe KPIs. Do not copy TrafficCounter's name, reporting protocol compatibility layer, UI, or configuration model.
- **Repository overlap:** `footfall_counter.py`, `lobby_visitor_flow.py`, and other vertical counters already prove the primitives. The opportunity is a single reusable multi-class counting engine rather than more one-off counters.

### 2. Privacy-safe in-store shopper funnel

- **Exact commercial capability:** Standard AI's VISION processes existing Axis video at the edge into privacy-safe spatial data, uses configurable store zones to measure shopper awareness, engagement, and conversion, and exposes dashboards for layout, staffing, and media-performance decisions without facial recognition.[6]
- **Buyer / vertical:** Grocers, convenience stores, specialty retail, CPG brands, and retail-media operators.
- **Commercial value:** Connects physical behavior to merchandising and media decisions without replacing the camera estate. The Axis-hosted page states deployments across 24 countries.[6]
- **Source URL:** [Axis partner page — In-store retail intelligence](https://www.axis.com/partner-finder/standard-ai).[6]
- **Non-infringing Nexus concept:** **Zone Funnel Analytics** — anonymously record track transitions such as entrance → display → product zone → checkout, plus dwell and abandonment rates. Store only ephemeral track IDs and aggregate counts; never perform face recognition or cross-visit identity. Use original zone semantics and dashboard design.
- **Repository overlap:** `dwell_analytics.py`, `footfall_counter.py`, `shelf_stockout.py`, and zone tracking provide the base. The net-new asset is a configurable funnel/state-machine and periodic KPI digest.

### 3. Parking-stall occupancy, dwell, and enforcement

- **Exact commercial capability:** Parquery markets real-time parking occupancy, duration, guidance, ANPR, and enforcement, deployable in cloud, on-premise, edge, or ACAP forms. Its page describes metadata-only transmission, dashboarding, signage/enforcement integrations, and third-party payment/navigation integration.[7]
- **Buyer / vertical:** Municipal parking, airports, campuses, hospitals, commercial real estate, and private operators.
- **Commercial value:** Improves utilization, reduces search traffic and patrol labor, supports guidance and compliance, and creates the data foundation for pricing decisions.[7]
- **Source URL:** [Axis partner page — AI smart parking intelligence](https://www.axis.com/partner-finder/parquery).[7]
- **Non-infringing Nexus concept:** **Stall State & Dwell** — configure one polygon per stall or row; use vehicle detections and state hysteresis to produce occupied/free transitions, dwell duration, overstays, and evidence snapshots. Keep ANPR optional and separate. Export a generic occupancy feed rather than copying Parquery APIs or dashboards.
- **Repository overlap:** `lot_occupancy.py`, `overnight_parking.py`, `handicap_stall_monitor.py`, and `ev_charger_blocked.py` cover slices of the workflow. Consolidating them around a shared stall-state service would produce a stronger product.

### 4. Speed-event evidence package

- **Exact commercial capability:** CamCentral's SpeedScan ACAP application joins radar speed/direction with AXIS License Plate Verifier events, stores plate, speed, direction, and timestamp on-camera, and exports CSV/JSON. Its page describes a field-proven university campus deployment.[8]
- **Buyer / vertical:** Campuses, municipalities, industrial sites, private roads, and transport authorities.
- **Commercial value:** Turns a speed event into reviewable, exportable evidence without a separate server, including off-grid deployments.[8]
- **Source URL:** [Axis partner page — Vehicle speed enforcement](https://www.axis.com/partner-finder/camcentral-systems-inc).[8]
- **Non-infringing Nexus concept:** **Speed Event Evidence** — consume an authorized radar/speed event from a generic event adapter, correlate the nearest tracked vehicle and optional plate candidate, export a pre/post clip, and alert with timestamp/direction/sensor value. Do not reverse-engineer SpeedScan's fusion or claim evidentiary/certified speed measurement from video alone.
- **Repository overlap:** Protect events, `clip_export`, `event_clip`, ALPR, alert metadata, and tracked vehicles already cover most of the workflow; the missing piece is a calibrated/authorized speed source and correlation contract.

### 5. Automatic road-incident detection

- **Exact commercial capability:** Sprinx runs traffic analytics directly on Axis cameras via ACAP to classify road users and detect anomalous situations on roads, highways, tunnels, bridges, and urban networks. Citilog separately markets edge/server automatic incident detection with VMS/SCADA integration.[9][10]
- **Buyer / vertical:** Departments of transportation, tunnel/highway operators, ports, campuses, and large industrial road networks.
- **Commercial value:** Earlier detection of stopped vehicles, wrong-way movement, congestion, and unsafe conditions reduces operator scanning and speeds incident response. Sprinx reports more than 30,000 deployed analytics channels over 15 years.[9]
- **Source URL:** [Axis partner page — Sprinx traffic management](https://www.axis.com/partner-finder/sprinx) and [Axis partner page — Citilog traffic safety](https://www.axis.com/partner-finder/citilog).[9][10]
- **Non-infringing Nexus concept:** **Road Incident Sentinel** — combine tracked trajectory, direction, speed proxy, stationary dwell, lane zones, and queue-length changes; create event clips for stopped vehicle, wrong-way, sudden queue growth, or pedestrian-in-road. Use original thresholds and event schemas, and label speed as an estimate unless calibrated.
- **Repository overlap:** `wrong_way.py`, `abandoned_object.py`, `yard_dwell.py`, `queue_length.py`, and clip alerts are reusable building blocks.

### 6. LPR/OCR transport identity event

- **Exact commercial capability:** Vaxtor runs LPR/OCR as ACAP analytics for plates, container codes, USDOT numbers, and other transport identifiers, with timestamps/GPS and VMS/back-office output. Adaptive Recognition adds plate plus vehicle make, model, category, and color in supported Axis camera environments.[11][12]
- **Buyer / vertical:** Logistics yards, ports, parking, tolling, gated property, fleet operations, and lawfully authorized security teams.
- **Commercial value:** Replaces manual gate transcription, improves asset/vehicle reconciliation, and links identity metadata to a precise event and image.[11][12]
- **Source URL:** [Axis partner page — Vaxtor LPR/OCR](https://www.axis.com/partner-finder/vaxtor-technologies) and [Axis partner page — Adaptive Recognition](https://www.axis.com/partner-finder/adaptive-recognition).[11][12]
- **Non-infringing Nexus concept:** **Transport ID Event** — build a pluggable crop → OCR → normalize → confidence → event pipeline for customer-authorized identifier types. Add allow/deny matching, short retention, encryption, and auditable access. Use independently trained/licensed models and generic output fields; do not copy recognition engines, country packs, or proprietary formats.
- **Repository overlap:** `src/detectors/alpr.py` already implements plate-region/OCR candidate handling. The extension is a generic identifier adapter, retention policy, event evidence, and optional vehicle-attribute model.

### 7. PPE rule matrix and escalation

- **Exact commercial capability:** peoly's ACAP module analyzes live video on ARTPEC 8/9 cameras for required helmets, vests, reflective garments, earmuffs, goggles, gloves, and related PPE, then raises ONVIF/ACAP events for non-compliance.[13]
- **Buyer / vertical:** Manufacturing, warehousing, construction, utilities, mining, and logistics.
- **Commercial value:** Converts periodic manual checks into immediate, zone-specific intervention and produces reviewable safety evidence. The partner page cites more than nine years of custom video/audio analytics experience.[13]
- **Source URL:** [Axis partner page — AI PPE detection on camera](https://www.axis.com/partner-finder/peoly).[13]
- **Non-infringing Nexus concept:** **PPE Rule Matrix** — package the existing PPE detector with rules by zone, shift, and required item set; add persistence across frames, supervisor escalation, snapshots/clips, and compliance digests. Do not use peoly's app name, models, thresholds, or UI.
- **Repository overlap:** `src/detectors/ppe.py`, `uniform_check.py`, `lab_coat_zone.py`, and alert dedup already cover much of the technical path. This is primarily a productization and evidence-quality opportunity.

### 8. Visible smoke/flame and thermal-anomaly escalation

- **Exact commercial capability:** Araani markets embedded Axis analytics for smoke, flame, hot spots, and thermometric temperature anomalies, producing real-time events for VMS, alarm, and safety workflows. The page states that Araani was founded in 2014 and progressed from a certified video-based fire detector to thermometric fire and temperature-anomaly products.[14] IntelexVision also markets on-camera ACAP fire/smoke detection with server-side verification.[15]
- **Buyer / vertical:** Recycling and waste, warehouses, industrial plants, battery/energy sites, tunnels, and other high-risk areas.
- **Commercial value:** Visual detection can identify visible precursors in large/open environments and route evidence for faster verification, potentially limiting loss and downtime.[14][15]
- **Source URL:** [Axis partner page — Araani fire detection](https://www.axis.com/partner-finder/araani) and [Axis partner page — IntelexVision](https://www.axis.com/partner-finder/intelexvision).[14][15]
- **Non-infringing Nexus concept:** **Visible Fire Early Warning** — strengthen the existing smoke/flame detector with multi-frame persistence, growth/motion signatures, zone sensitivity, optional thermal-event ingestion, staged severity, and pre/post clips. Market it only as supplemental visual review unless independently tested and certified; never represent it as a replacement for code-required fire detection or alarms.
- **Repository overlap:** `src/detectors/smoke_flame.py` is already present. The opportunity is commissioning, calibrated confidence, escalation, and evidence packaging rather than a new generic detector.

### 9. Perimeter alarm verification

- **Exact commercial capability:** VAELSYS offers visual/thermal perimeter analytics as an ACAP app on compatible ARTPEC-8 devices or as a server deployment, with central configuration, alarm verification, and VMS/alarm integration.[18]
- **Buyer / vertical:** Critical infrastructure, solar farms, utilities, logistics yards, industrial campuses, and remote property.
- **Commercial value:** Reduces nuisance alarms and operator workload while preserving rapid response to genuine boundary events. VAELSYS states that it has specialized in computer vision and perimeter protection since 2004.[18]
- **Source URL:** [Axis partner page — AI-powered perimeter security](https://www.axis.com/partner-finder/vaelsys).[18]
- **Non-infringing Nexus concept:** **Perimeter Alarm Verifier** — correlate a Protect motion/smart event with tracked object class, boundary crossing direction, zone dwell, schedule, and a pre/post clip before escalation. Optionally require confirmation across adjacent cameras. Use original scoring and generic integrations.
- **Repository overlap:** `after_hours_activity.py`, `loitering_watch.py`, `wrong_way.py`, `site_theft_watch.py`, `safety_zone_breach.py`, and the alert engine supply nearly all workflow primitives.

### 10. Camera-based water level and flow monitoring

- **Exact commercial capability:** TENEVIA's embedded CamLevel and CamFlow applications run on Axis cameras, estimate water level and surface velocity, calculate river discharge, and produce measurements plus augmented images for remote verification.[19]
- **Buyer / vertical:** Municipal flood teams, water authorities, dam/canal operators, environmental agencies, and critical infrastructure.
- **Commercial value:** A camera becomes a non-contact hydrometric sensor with visual verification, useful at sites where installing or maintaining in-water instrumentation is difficult. TENEVIA reports ten years in image-based hydrometry.[19]
- **Source URL:** [Axis partner page — Water monitoring video analytics](https://www.axis.com/partner-finder/tenevia).[19]
- **Non-infringing Nexus concept:** **Gauge & Flow Monitor** — independently implement fixed-camera gauge/shoreline ROIs, calibration points, segmentation-derived level, optical-flow trend, threshold alerts, and annotated evidence. Present discharge as an estimate only after site calibration and validation; do not copy CamLevel/CamFlow algorithms or names.
- **Repository overlap:** RTSP, snapshots, trend state, and alerts exist, but calibrated geometry, environmental segmentation, and validation are net-new.

### 11. Weather and environmental scene hazards

- **Exact commercial capability:** WaterView markets ACAP applications that detect flooding, snow accumulation, poor visibility, and smoke plumes on the edge, outputting standard system events and MQTT/VMS integrations.[20]
- **Buyer / vertical:** Roads, rail, airports, municipalities, utilities, campuses, and outdoor critical infrastructure.
- **Commercial value:** Reuses existing cameras as distributed environmental sensors and routes local hazard events without continuous cloud video transfer.[20]
- **Source URL:** [Axis partner page — Weather and environmental monitoring](https://www.axis.com/partner-finder/waterview).[20]
- **Non-infringing Nexus concept:** **Scene Weather Hazard** — combine baseline image contrast/visibility, snow/ice region growth, standing-water segmentation, and trend thresholds; emit a distinct environmental event with snapshot/clip evidence. Keep wildfire/fire-life-safety claims separate and require human verification.
- **Repository overlap:** `snow_ice_watch.py`, `greenhouse_climate_visual.py`, `thermal_shimmer.py`, and camera/image utilities offer a starting point. A shared baseline-and-drift engine would reduce duplicated heuristics.

### 12. Manual-production cycle and SOP analytics

- **Exact commercial capability:** PowerArena ingests Axis assembly-line video to analyze worker motions, cycle times, process adherence, bottlenecks, idle time, line balancing, and error-proofing signals in real time.[21]
- **Buyer / vertical:** Electronics manufacturing services, automotive/industrial assembly, contract manufacturing, and continuous-improvement teams.
- **Commercial value:** Converts manual production into measurable cycle/SOP data without adding a sensor to every workstation. The partner page says the platform is trusted by top EMS enterprises.[21]
- **Source URL:** [Axis partner page — AI-powered manufacturing visibility](https://www.axis.com/partner-finder/powerarena).[21]
- **Non-infringing Nexus concept:** **Cycle Step Timer** — define an original sequence of workstation zones/events, use anonymous pose/object tracks to timestamp step entry/exit, flag skipped or overlong steps, and publish shift summaries. Avoid worker identity, productivity scoring at the individual level, and any copying of PowerArena's line-balancing logic or interface.
- **Repository overlap:** Pose tracking, zone dwell, route verification, `machine_idle.py`, and digests are available. The net-new work is a configurable sequence/state model and privacy-safe aggregation.

### 13. Visual assembly and defect checks

- **Exact commercial capability:** Loopr AI uses Axis streams as visual sensors to automate PPE/safety checks, correct-part assembly verification, and defect detection across production lines, plants, warehouses, and supply chains.[22]
- **Buyer / vertical:** Manufacturing quality, packaging, warehousing, and supplier-quality teams.
- **Commercial value:** Earlier detection can reduce scrap, rework, downtime, warranty exposure, and unsafe conditions, according to the partner's Axis-hosted description.[22]
- **Source URL:** [Axis partner page — Visual quality and safety](https://www.axis.com/partner-finder/loopr-ai).[22]
- **Non-infringing Nexus concept:** **Assembly Presence Check** — for a tightly scoped SKU/station, independently train or license a model to verify required components, orientation, label, seal, or final-state template; alert with evidence and a review workflow. Do not attempt a generic “detect any defect” claim.
- **Repository overlap:** `seal_check.py`, `banquet_setup_verify.py`, `detail_qc_walk.py`, and custom-weight fallbacks show the pattern. Production readiness requires controlled lighting, station-specific data, explicit fail-safe behavior, and model versioning.

### 14. External-event pre/post evidence

- **Exact commercial capability:** TAKEBISHI's DxpRecSync receives PLC event signals and captures Axis video before and after the event so users can remotely reconstruct production errors without modifying existing PLC programs.[23]
- **Buyer / vertical:** Manufacturing maintenance, controls engineering, machine builders, and process troubleshooting teams.
- **Commercial value:** Replaces “what happened?” guesswork with a synchronized visual record, reducing root-cause time and repeat downtime.[23]
- **Source URL:** [Axis partner page — PLC event video recording](https://www.axis.com/partner-finder/takebishi-corporation).[23]
- **Non-infringing Nexus concept:** **External Event Evidence** — accept a generic, authenticated webhook/MQTT/Protect/Access event with timestamp and asset ID; map it to cameras; export a configurable pre/post clip; attach event metadata; and deliver an evidence package. PLC-specific adapters can be separate connectors. Do not copy DxpRecSync's PLC communications or interface.
- **Repository overlap:** This is a direct composition of Protect events, camera inventory, `clip_export`, `event_clip`, alert delivery, and existing evidence-package patterns. It is one of the lowest-risk opportunities.

### 15. Camera-estate health and compliance

- **Exact commercial capability:** Ai-RGUS analyzes Axis camera/AXIS Camera Station performance, uptime, image availability, clarity/correctness, recordings, storage media, and timestamps, then provides unified alerts and compliance reports.[24]
- **Buyer / vertical:** Integrators/MSPs, schools, healthcare, enterprise security, regulated sites, and large multi-site estates.
- **Commercial value:** Converts reactive truck rolls into planned maintenance and recurring managed service while proving that cameras and recordings are usable. The partner page says the product began with Duke University's 2,000+ camera system and is now deployed on well over 100,000 cameras worldwide.[24]
- **Source URL:** [Axis partner page — Verifying security system health](https://www.axis.com/partner-finder/ai-rgus).[24]
- **Non-infringing Nexus concept:** **Vision Estate Health** — inventory cameras; test stream availability/latency; score blur, occlusion, over/underexposure, and scene drift from scheduled snapshots; detect clock skew; verify recent events/clips; and route maintenance alerts plus compliance digests. Use original metrics and reports.
- **Repository overlap:** `camera_tamper.py`, Protect `camera_inventory`, `stream_quality`, `scene_quality`, snapshot governance, clip/event profiles, and alert readiness make this the strongest immediate fit.

## Recommended implementation sequence

### Wave 1 — workflow products on existing primitives

1. **Vision Estate Health** — broad buyer base, strongest disclosed commercial scale, and direct inventory/snapshot/alert fit.
2. **External Event Evidence** — mostly orchestration over events and clip export; useful beyond manufacturing.
3. **Flow Ledger** — replace fragmented vertical counters with one reusable engine and vertical presets.
4. **Stall State & Dwell** — consolidate existing parking functions around a shared state model.
5. **PPE Rule Matrix** and **Visible Fire Early Warning** — package existing detectors with explicit commissioning, evidence, and claim boundaries.
6. **Perimeter Alarm Verifier** — high-value composition of mature tracking, zones, schedules, events, and clips.

### Wave 2 — moderate model or calibration work

7. **Road Incident Sentinel** — compose existing primitives, then add lane calibration and queue/spillback logic.
8. **Transport ID Event** — extend existing ALPR under strict retention and authorization controls.
9. **Speed Event Evidence** — proceed only with an authorized speed source; keep the Nexus role focused on correlation and evidence.
10. **Zone Funnel Analytics** — add a generic track-sequence/funnel engine and retail KPI layer.

### Wave 3 — domain-specific pilots

11. **Gauge & Flow Monitor**, **Scene Weather Hazard**, **Cycle Step Timer**, and **Assembly Presence Check** require site-specific calibration, datasets, or tightly bounded process definitions. Pilot with one buyer and one fixed scene before marketplace packaging.

## Independent-implementation guardrails

- Treat partner pages as evidence of customer demand, not implementation specifications.
- Use original product names, manifests, configuration schemas, UI, event schemas, and dashboards.
- Train or properly license models and datasets independently; do not extract partner models, binaries, APIs, or output formats.
- Preserve Nexus's no-face-recognition rule. Use anonymous tracks and aggregate journeys for retail/manufacturing analytics.
- Apply purpose limitation, short retention, encryption, access logging, and customer authorization to plate/OCR data.
- Separate supplemental visual alerts from certified life-safety, enforcement, hydrometric, or compliance claims. Independent testing and applicable certification are required before making such claims.
- Prefer workflow differentiation—event correlation, evidence quality, maintenance routing, reporting, and vertical presets—over cloning a vendor's detector.

## Sources

[1] https://www.axis.com/products/acap — AXIS Camera Application Platform (ACAP)
[2] https://www.axis.com/products/video-analytics — Video analytics | Axis Communications
[3] https://www.axis.com/products/axis-object-analytics/scenarios — AXIS Object Analytics scenarios
[4] https://www.axis.com/partner-finder — Axis Technology partner finder
[5] https://www.axis.com/partner-finder/think-and-make-di-andriano-rocco-giuseppe — People and vehicle counting by Think and Make
[6] https://www.axis.com/partner-finder/standard-ai — In-store retail intelligence by Standard AI
[7] https://www.axis.com/partner-finder/parquery — AI smart parking intelligence by Parquery
[8] https://www.axis.com/partner-finder/camcentral-systems-inc — Vehicle speed enforcement by CamCentral Systems
[9] https://www.axis.com/partner-finder/sprinx — AI traffic management by Sprinx
[10] https://www.axis.com/partner-finder/citilog — Transportation and traffic safety by Citilog
[11] https://www.axis.com/partner-finder/vaxtor-technologies — LPR and advanced OCR analytics by Vaxtor
[12] https://www.axis.com/partner-finder/adaptive-recognition — ANPR and vehicle recognition by Adaptive Recognition
[13] https://www.axis.com/partner-finder/peoly — AI PPE detection on camera by peoly
[14] https://www.axis.com/partner-finder/araani — Video and thermographic fire detection by Araani
[15] https://www.axis.com/partner-finder/intelexvision — AI-powered video intelligence by IntelexVision
[18] https://www.axis.com/partner-finder/vaelsys — AI-powered perimeter security by VAELSYS
[19] https://www.axis.com/partner-finder/tenevia — Water monitoring video analytics by TENEVIA
[20] https://www.axis.com/partner-finder/waterview — Weather and environmental monitoring by WaterView
[21] https://www.axis.com/partner-finder/powerarena — AI-powered manufacturing visibility by PowerArena
[22] https://www.axis.com/partner-finder/loopr-ai — Visual quality and safety by Loopr AI
[23] https://www.axis.com/partner-finder/takebishi-corporation — PLC event video recording by TAKEBISHI
[24] https://www.axis.com/partner-finder/ai-rgus — Verifying security system health by Ai-RGUS
