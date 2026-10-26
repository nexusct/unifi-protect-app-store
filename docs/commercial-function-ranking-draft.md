# Nexus Vision Commercial Function Ranking — Advisory Draft

**Status:** Advisory draft; not a product commitment, pricing decision, safety certification, or technical acceptance test.
**Inventory snapshot:** 2026-08-17; `storefront/catalog.json` reconciled to 130 literal Python `MANIFEST` declarations plus 121 declarative API manifests.
**Output:** 251 scored function IDs; exact top 80 selected by the frozen weighted score and tie-break rules below.

## Executive outcome

- Scored **251 of 251** unique current IDs; no duplicate or unmatched source/catalog IDs were found.
- Proposed **exactly 80** functions. The inclusion cut line is **rank 80 at 57.5**; rank 81 also scores 57.5 and loses only on the published tie-break sequence.
- Top-80 source mix: vision=51, Protect/API=23, Access/API=6.
- Top-80 uncertainty: Low=55, Medium=11, High=14.
- The ranking intentionally rewards safety, security, evidence, access verification, and operational outcomes over narrow technical diagnostics. Diagnostics can still rank when their estimated customer reach and operational value are broad (for example, camera-offline and stream-connectivity monitoring).

## Evidence basis and limitations

Official competitor material validates a commercial market for intrusion/restricted-area protection, loitering, occupancy, hard-hat/PPE checks, queues, visitor counts, traffic flow, dwell, and wrong-way detection.[1][2] Hanwha also sells factory-safety analytics and an AI analytics box covering person/forklift safety, line and area rules, loitering, direction, intrusion, counting, queue management, and heatmaps.[3][4]

Major VMS vendors also commercialize evidence handling, analytics-triggered workflows, and occupancy management: Genetec describes integrated video/metadata evidence and advanced analytics; Avigilon documents evidence bookmarking, incident reports, and exports; both publish occupancy products or packages.[5][6][7][8] AXIS publishes image-health functions for blocked, redirected, blurred, and underexposed views.[9] The Milestone marketplace also carries partner analytics for intrusion, loitering, left objects, crowding, tailgating, and line crossing.[10]

**Evidence assumptions:** competitor validation is assigned at the capability-family level, not as a claim that a competitor sells an identical implementation or identical SKU. “Direct” means a first-party vendor page or official product document supports the same buyer outcome; “adjacent” means a close workflow, platform primitive, or official marketplace partner. Absence of cited evidence is not proof that no competitor offers a capability. Customer-benefit percentages are planning estimates, not survey results. Business-value scores are analyst estimates, not measured ROI. High-uncertainty rows should be validated with customers and deployment trials before roadmap commitment.

## Reproducible rubric

### 1. Competitor validation (0–100; weight 25%)

Assign the most specific supported band, using official vendor/product documentation before blogs or partner listings:

| Score anchor | Reproducible test |
|---:|---|
| 94 | Same buyer outcome is explicitly sold by two or more major first-party vendors. |
| 92 | Same buyer outcome is explicit in one major first-party product and corroborated by another vendor or major-VMS marketplace. |
| 90 | Direct first-party match from one named major vendor. |
| 82–88 | Close first-party variant using the same commercial workflow or analytic primitive. |
| 70–78 | Adjacent capability, official marketplace partner, or sold platform workflow rather than a like-for-like function. |
| 60–68 | Weak/indirect validation; only a supporting primitive or narrow partner analogue was found. |
| 40–59 | No substantiated comparable SKU in this evidence pass; plausible platform utility only. |
| 0–39 | No credible commercial analogue and no clear sold primitive. |

### 2. Estimated realistic customer benefit (0–100; weight 35%)

This dimension is literally an estimated percentage of realistic Nexus Vision customers who could receive material benefit, not a generic attractiveness score. Use this assumed customer mix: 25% multi-site commercial/property, 20% retail/QSR/hospitality, 20% industrial/logistics/automotive, 15% education/community/recreation, 10% healthcare/senior living, and 10% specialty/high-compliance sites. For each segment, estimate the share with the relevant scene/workflow and a likely action owner, then compute:

`benefit_pct = round(sum(segment_mix_pct × applicable_share_within_segment))`

`applicable_share_within_segment` is 0–1 and requires all three: a plausible camera view, a recurring problem, and a buyer/operator able to act. Broad platform health may reach 60–80%; common security/operations functions often reach 25–60%; vertical functions usually reach 3–20%; ultra-specialty functions can be below 5%. The exact frozen estimate for every ID is in the CSV.

### 3. Business value (0–100; weight 40%)

Calculate the dimension from four 0–100 inputs:

`business_value = round(0.35 × outcome_severity + 0.25 × annual_economic_exposure + 0.20 × response_urgency + 0.20 × buyer_willingness_to_pay)`

Anchor each input consistently: 20=minor convenience, 40=useful reporting, 60=meaningful labor/service improvement, 80=material security/loss/compliance outcome, 100=credible life-safety or major-loss exposure. “Willingness to pay” requires a named budget owner and recurring problem. Narrow diagnostics are capped in practice by lower economic exposure and willingness-to-pay unless they protect the availability of the whole camera fleet.

### Composite and tie-breakers

`weighted_score = round(0.25 × competitor_validation + 0.35 × benefit_pct + 0.40 × business_value, 2)`

Sort by: (1) weighted score descending; (2) business value descending; (3) benefit percentage descending; (4) competitor validation descending; (5) uncertainty Low, then Medium, then High; and (6) exact ID ascending. No category quota or manual promotion is applied after scoring. This explains the exact tie at the rank-80 boundary.

### Uncertainty label

- **Low:** direct competitor evidence plus a common, observable workflow.
- **Medium:** adjacent evidence, customer-mix sensitivity, or meaningful integration assumptions.
- **High:** niche scene, learned visual baseline/heuristic, safety-sensitive claim, or weak evidence-to-implementation transfer.

## Exact proposed top 80

| Rank | Exact ID | Name | Category | Surface | Competitor | Benefit % | Business value | Weighted | Uncertainty |
|---:|---|---|---|---|---:|---:|---:|---:|---|
| 1 | `protect-camera-offline-watch` | Protect Camera Offline Watch | Security & Access | protect | 90 | 78 | 88 | 85.0 | Low |
| 2 | `after-hours-activity` | After-Hours Activity | Security & Access | vision | 94 | 68 | 91 | 83.7 | Low |
| 3 | `rtsp-connectivity-probe` | RTSP Connectivity Probe | Security & Access | protect | 90 | 76 | 84 | 82.7 | Low |
| 4 | `camera-tamper` | Camera View Change Alert | Property & Liability | vision | 90 | 72 | 85 | 81.7 | Low |
| 5 | `loitering-watch` | Loitering Watch | Security & Access | vision | 94 | 62 | 88 | 80.4 | Low |
| 6 | `event-pre-post-roll-clip-export` | Event Pre/Post-Roll Clip Export | Security & Access | protect | 90 | 62 | 88 | 79.4 | Low |
| 7 | `fire-exit-blocked` | Egress-Zone Object Review | Property & Liability | vision | 92 | 52 | 92 | 78.0 | Low |
| 8 | `smart-event-clip-export` | Smart-Detect Event Clip Export | Security & Access | protect | 90 | 58 | 86 | 77.2 | Low |
| 9 | `rtsp-freeze-watch` | RTSP Freeze Watch | Security & Access | protect | 90 | 62 | 82 | 77.0 | Low |
| 10 | `mandated-camera-check` | Camera View Baseline Check | Compliance | vision | 90 | 58 | 82 | 75.6 | High |
| 11 | `tailgating-correlation` | Credential-to-Crossing Correlation | Security & Access | vision | 92 | 42 | 94 | 75.3 | Low |
| 12 | `multi-camera-incident-clip-bundle` | Multi-Camera Clip Bundle | Security & Access | protect | 90 | 48 | 90 | 75.3 | High |
| 13 | `manual-bounded-clip-export` | Manual Bounded Clip Export | Security & Access | protect | 90 | 55 | 83 | 74.95 | Low |
| 14 | `denied-access-escalation` | Denied-Access Escalation | Security & Access | vision | 92 | 45 | 90 | 74.75 | Low |
| 15 | `verified-door-timeline` | Verified Door Incident Timeline | Security & Access | vision | 92 | 45 | 90 | 74.75 | Low |
| 16 | `site-theft-watch` | After-Hours Equipment-Zone Presence | Security & Access | vision | 94 | 43 | 90 | 74.55 | Low |
| 17 | `door-alarm-verification` | Forced/Held-Open Video Verification | Security & Access | vision | 92 | 40 | 93 | 74.2 | Low |
| 18 | `slip-fall` | Possible Fall Review | Property & Liability | vision | 90 | 38 | 94 | 73.4 | Low |
| 19 | `crowd-density` | Crowd Density Alert | People & Safety | vision | 94 | 42 | 88 | 73.4 | Low |
| 20 | `clip-export-integrity-probe` | Clip Export Integrity Probe | Compliance | protect | 90 | 45 | 87 | 73.05 | Low |
| 21 | `rtsp-black-frame-rate` | RTSP Black Frame Rate | Property & Liability | protect | 90 | 55 | 78 | 72.95 | Low |
| 22 | `abandoned-object` | Persistent Object Review | People & Safety | vision | 92 | 46 | 84 | 72.7 | Low |
| 23 | `clip-export-checksum-manifest` | Clip Export Checksum Manifest | Compliance | protect | 90 | 45 | 86 | 72.65 | Low |
| 24 | `hallway-overnight` | Hallway Overnight Presence | Security & Access | vision | 94 | 42 | 85 | 72.2 | Low |
| 25 | `access-incident-index` | Access Incident Search Index | Security & Access | vision | 92 | 42 | 86 | 72.1 | Low |
| 26 | `motion-event-clip-export` | Motion Event Clip Export | Security & Access | protect | 90 | 50 | 80 | 72.0 | Low |
| 27 | `access-after-hours-unlock-report` | After-Hours Unlock Command Report | Security & Access | access | 82 | 46 | 88 | 71.8 | Low |
| 28 | `after-hours-entry-verification` | After-Hours Entry Verification | Security & Access | vision | 92 | 34 | 92 | 71.7 | Low |
| 29 | `access-evidence-package` | Access Event Evidence Package | Security & Access | vision | 92 | 38 | 88 | 71.5 | High |
| 30 | `clip-export-index` | Clip Export Search Index | Intelligence | protect | 90 | 48 | 80 | 71.3 | Low |
| 31 | `access-close-confirmation-gap` | Door Close Event Gap Review | Security & Access | access | 82 | 42 | 89 | 70.8 | High |
| 32 | `rtsp-blur-score` | RTSP Blur Score Monitor | Property & Liability | protect | 90 | 52 | 75 | 70.7 | High |
| 33 | `access-audited-unlock-request` | Audited Door Unlock Request | Security & Access | access | 82 | 40 | 90 | 70.5 | Low |
| 34 | `access-door-alarm-recurrence` | Door Alarm Recurrence Summary | Security & Access | access | 82 | 43 | 87 | 70.35 | Low |
| 35 | `wrong-way` | Wrong-Way Movement | People & Safety | vision | 92 | 34 | 88 | 70.1 | Low |
| 36 | `clip-export-daily-manifest` | Clip Export Daily Manifest | Compliance | protect | 90 | 42 | 82 | 70.0 | Low |
| 37 | `gate-tailgate-storage` | Rapid Gate-Crossing Review | Security & Access | vision | 92 | 45 | 78 | 69.95 | High |
| 38 | `visitor-entry-review` | Visitor Entry Review Context | Security & Access | vision | 92 | 38 | 84 | 69.9 | Low |
| 39 | `footfall-counter` | Footfall & Occupancy Counter | Retail & QSR | vision | 94 | 48 | 74 | 69.9 | Low |
| 40 | `forecourt-loiter` | Forecourt Dwell Watch | Security & Access | vision | 94 | 36 | 84 | 69.7 | Low |
| 41 | `clip-export-queue` | Clip Export Queue | Intelligence | protect | 90 | 48 | 76 | 69.7 | Low |
| 42 | `safety-zone-breach` | Restricted-Zone Person Presence | Manufacturing & Warehouse | vision | 94 | 24 | 94 | 69.5 | Low |
| 43 | `supply-theft-watch` | After-Hours Supply-Zone Activity | Security & Access | vision | 94 | 32 | 87 | 69.5 | Low |
| 44 | `queue-length` | Queue Length Monitor | Retail & QSR | vision | 94 | 40 | 80 | 69.5 | Low |
| 45 | `door-propped` | Door-Zone Baseline Change | Property & Liability | vision | 78 | 45 | 84 | 68.85 | High |
| 46 | `door-operation-verification` | Door Operation Verification | Security & Access | vision | 92 | 32 | 86 | 68.6 | Low |
| 47 | `access-remote-unlock-ledger` | Remote Unlock Event Ledger | Compliance | access | 82 | 40 | 85 | 68.5 | Low |
| 48 | `occupancy-reconciliation` | Occupancy Reconciliation | Security & Access | vision | 92 | 30 | 84 | 67.1 | High |
| 49 | `tenant-after-hours` | Per-Tenant After-Hours Watch | Security & Access | vision | 94 | 28 | 83 | 66.5 | Low |
| 50 | `crane-exclusion` | Crane Exclusion-Zone Presence Alert | People & Safety | vision | 94 | 12 | 95 | 65.7 | Low |
| 51 | `lot-occupancy` | Parking Lot Occupancy | Automotive & Parking | vision | 94 | 38 | 72 | 65.6 | Low |
| 52 | `access-door-alarm-duration-ledger` | Door Alarm Duration Ledger | Compliance | access | 82 | 35 | 80 | 64.75 | Low |
| 53 | `forklift-speed` | Shared-Lane Vehicle Motion Alert | Manufacturing & Warehouse | vision | 90 | 14 | 91 | 63.8 | High |
| 54 | `protect-camera-discovery-failure-log` | Protect Camera Discovery Failure Log | Security & Access | protect | 72 | 60 | 62 | 63.8 | Medium |
| 55 | `protect-event-poll-health` | Protect Event Poll Health | Security & Access | protect | 72 | 58 | 62 | 63.1 | Medium |
| 56 | `overnight-parking` | Overnight Parking Watch | Automotive & Parking | vision | 86 | 34 | 74 | 63.0 | Low |
| 57 | `rtsp-decode-error-rate` | RTSP Decode Error Rate | Security & Access | protect | 72 | 55 | 62 | 62.05 | Medium |
| 58 | `customer-wait-alert` | Service-Zone Dwell Alert | Retail & QSR | vision | 88 | 25 | 78 | 61.95 | High |
| 59 | `lighting-outage` | Low-Luminance Lighting Watch | Property & Liability | vision | 90 | 35 | 68 | 61.95 | High |
| 60 | `snapshot-last-good-frame` | Last Good Frame Snapshot | Security & Access | protect | 78 | 35 | 72 | 60.55 | Medium |
| 61 | `drive-thru-timer` | Drive-Thru Service Timer | Retail & QSR | vision | 88 | 18 | 80 | 60.3 | High |
| 62 | `rtsp-frame-gap-watch` | RTSP Frame Gap Watch | Security & Access | protect | 72 | 50 | 62 | 60.3 | Medium |
| 63 | `rtsp-rolling-quality-digest` | RTSP Rolling Quality Digest | Intelligence | protect | 72 | 50 | 62 | 60.3 | Medium |
| 64 | `pool-capacity` | Pool-Area Person Count | People & Safety | vision | 94 | 10 | 82 | 59.8 | Low |
| 65 | `curbside-arrival` | Curbside Pickup Arrival | Automotive & Parking | vision | 86 | 24 | 74 | 59.5 | Low |
| 66 | `aggression-posture` | Raised-Arm Motion Review | People & Safety | vision | 70 | 25 | 82 | 59.05 | High |
| 67 | `truck-turn-time` | Truck Yard Dwell Estimate | Manufacturing & Warehouse | vision | 88 | 14 | 80 | 58.9 | Low |
| 68 | `dwell-analytics` | Zone Dwell Analytics | Retail & QSR | vision | 88 | 30 | 66 | 58.9 | Low |
| 69 | `conveyor-jam` | Conveyor Stalled-Object Review | Manufacturing & Warehouse | vision | 86 | 10 | 84 | 58.6 | Low |
| 70 | `child-safety-zone` | Small-Person Restricted-Zone Alert | People & Safety | vision | 68 | 10 | 94 | 58.1 | High |
| 71 | `bus-loop-safety` | Bus Loop Safety | People & Safety | vision | 74 | 8 | 92 | 58.1 | Medium |
| 72 | `machine-monopoly` | Machine-Row Dwell Watch | Retail & QSR | vision | 88 | 30 | 64 | 58.1 | Low |
| 73 | `atm-vestibule-watch` | ATM Vestibule Watch | Security & Access | vision | 82 | 18 | 78 | 58.0 | Medium |
| 74 | `waiting-room-overflow` | Waiting Room Overflow | Healthcare & Senior Living | vision | 94 | 9 | 78 | 57.85 | Low |
| 75 | `magnet-crane-exclusion` | Magnet-Crane Exclusion-Zone Alert | People & Safety | vision | 72 | 5 | 95 | 57.75 | Medium |
| 76 | `ev-charger-blocked` | EV Charger Blocked | Automotive & Parking | vision | 92 | 25 | 65 | 57.75 | Low |
| 77 | `splash-pad-capacity` | Splash Pad Capacity | People & Safety | vision | 94 | 4 | 82 | 57.7 | Low |
| 78 | `laundromat-overnight` | Laundromat Overnight Watch | Security & Access | vision | 94 | 8 | 78 | 57.5 | Low |
| 79 | `protect-camera-unnamed-records` | Protect Unnamed Camera Records | Compliance | protect | 72 | 42 | 62 | 57.5 | Medium |
| 80 | `protect-event-camera-reference-audit` | Protect Event Camera Reference Audit | Compliance | protect | 72 | 42 | 62 | 57.5 | Medium |

## Portfolio observations

- The top tier is led by camera availability, after-hours/security monitoring, image tamper/health, evidence export, access-event verification, blocked egress, falls, crowding, and other high-consequence workflows.
- Evidence and access/video-correlation functions score well because they combine a validated VMS buying pattern with clear incident-response and audit value.
- Fine-grained RTSP/API diagnostics generally rank below broad camera-availability and image-health functions. Two tied diagnostics land at ranks 79–80 only because the frozen tie-break order resolves a group at the same composite score.
- Several safety functions retain high business value but rank lower when the relevant customer scene is rare. That is intentional: the rubric separates consequence from addressable reach.
- High-uncertainty top-80 functions should not be marketed as autonomous determinations. They need commissioning, human review, claim controls, and customer validation.

## Coverage and audit trail

| Check | Result |
|---|---:|
| Catalog rows | 251 |
| Unique IDs | 251 |
| Selected top rows | 80 |
| Non-selected rows | 171 |
| Python manifest inventory | 130 |
| Declarative API manifest inventory | 121 |
| Source/catalog union | 251 |

Every row in the CSV includes the exact ID, three dimension scores, weighted score, rank, top-80 flag, uncertainty, capability family, evidence band, and a compact row-level rationale. The CSV is the complete 251-row audit; this Markdown file is the rubric, evidence assumptions, and exact top-80 decision view.

## Sources

[1] https://www.axis.com/products/axis-object-analytics — AXIS Object Analytics
[2] https://www.avigilon.com/analytics — Avigilon Video Analytics
[3] https://www.hanwhavision.com/en/products/software/analytics/A/aia-c01fac — Hanwha Vision Factory & Safety AI Pack
[4] https://www.hanwhavision.com/en/products/peripherals/ai-box/A/aib-800 — Hanwha Vision AIB-800 AI Box
[5] https://www.genetec.com/products/video-management — Genetec Video Management Solutions
[6] https://docs.avigilon.com/bundle/unity-video-client-8-8/page/using/evidence-management.htm — Avigilon Evidence Management
[7] https://www.genetec.com/press-center/press-releases/2020/05/genetec-helps-organizations-monitor-occupancy-levels-and-ensure-compliance-with-physical-distancing-regulations — Genetec Occupancy Management
[8] https://www.avigilon.com/occupancy-management — Avigilon Occupancy Management
[9] https://www.axis.com/dam/public/85/3c/8d/datasheet-axis-m4228-lve-dome-camera-en-US-506759.pdf — AXIS M4228-LVE Datasheet — Image Health Analytics
[10] https://www.milestonesys.com/globalassets/marketplace/uploaded-assets/0013x00002fnu7xqas/v2024.2.5-cvedia-plugin-for-milestone-xprotect-user-manual-lightweight.pdf — CVEDIA-RT AI Analytics Plugin for Milestone XProtect
