# Page Audit — nexus-vision-ai (Nexus Vision Marketplace)

Site-optimization-loop tracker. One row per page; ✅ SIGNED OFF only after
SEO/meta + H1 + proofread + claims + links + function test + build pass.

Scope: public pages served by the container (landing, storefront, guide).
Excluded: /api/* (noindex machine endpoints), /health, /streams, /detectors.

| # | Route | File(s) | Status | Issues found | Issues fixed | Notes |
|---|-------|---------|--------|--------------|--------------|-------|
| 1 | / | landing/index.html | ✅ SIGNED OFF | 8: title 70→53c, desc 178→154c, stale "67 functions" ×3, no OG/JSON-LD, BIPA-conclusory FAQ, bundle IDs mismatched to catalog, "one business day" turnaround, bare "SLA" in Enterprise tier | all 8 fixed — OG+SoftwareApplication+FAQPage schema added, counts→120, claims-bank phrasing | build ✅ serve ✅ signup flow ✅ |
| 2 | /storefront/ | storefront/index.html + catalog.js | ✅ SIGNED OFF | 4: stale "67" in meta desc (also over 160c), dead #pricing-note anchor, conclusory "BIPA-safe" stat, no OG/JSON-LD | all fixed — desc 153c, anchor→/#pricing, calibrated privacy copy, CollectionPage schema + OG | build ✅ render ✅ sort ×3 ✅ |
| 3 | /guide/ | guide/index.html | ✅ SIGNED OFF | 1: no OG/JSON-LD (title 47c ✓ desc 149c ✓ H1 ✓ TOC anchors ✓ claims ✓ docker cmds ✓) | fixed — TechArticle schema + OG article tags | build ✅ serve ✅ schema valid ✅ |

**Loop complete: 3/3 pages signed off, 13 issues found, 13 fixed.**
Build: `nexus-vision-ai:test` green. Live-verified on container port 8091.

## Editorial marketplace visual pass — 2026-08-14

Scope: visual hierarchy and interaction styling only; preserve Nexus branding,
claims-safe copy, subscription API behavior, marketplace filtering/sorting, and
YAML generation. Inspiration is limited to familiar store conventions—editorial
feature cards, rounded app artwork, grouped lists, soft-gray surfaces, and compact
Get/Added controls. No third-party marks, proprietary assets, product names, or copied page layouts.

| Route | Status | Visual work | Verification |
|---|---|---|---|
| / | ✅ SIGNED OFF | Rounded editorial hero using Nexus artwork; system typography; layered story, workflow, pricing, signup, and disclosure surfaces; local-connector and biometric copy tightened; optional empty form fields no longer cause API validation failures | Chromium desktop + 390px mobile ✅; one H1 ✅; labeled controls + ARIA live feedback ✅; no console errors ✅; signup POST 200 ✅; horizontal overflow 0 ✅ |
| /storefront/ | ✅ SIGNED OFF | Three-card editorial rail; 120 generated app rows with varied rounded-square artwork; compact metadata; Get/Added state; responsive details sheet; accessible close/Escape behavior; multi-term marketplace search | 120 rows ✅; 3 features ✅; A–Z/category/plan-tier sort ✅; multi-term search ✅; modal + Escape ✅; YAML download ✅; mobile overflow 0 ✅ |
| /guide/ | ✅ SIGNED OFF | Platform support-style grouped reading cards, numbered steps, inset tables, dark code blocks, mobile TOC, and responsive scroll containers | 8 sections + 8 TOC anchors ✅; desktop/mobile screenshots ✅; code/table containment ✅; mobile overflow 0 ✅ |

**Visual pass complete: 3/3 pages signed off.**

Final production evidence:
- Docker image `nexus-vision-ai:test` built successfully.
- Container preview: `http://localhost:8092/` with `/storefront/` and `/guide/` all HTTP 200.
- Marketplace registry: **120 registered, 0 errors**.
- `catalog.json` and `catalog.js`: **120 each, identical IDs, 120 unique IDs**.
- Metadata/schema: title limits, description limits, one H1, and valid JSON-LD retained on all pages.
- Browser QA: zero console/page/request errors across desktop and 390px mobile runs.
- Branding boundary: original Nexus branding with no third-party marks, assets, product names, or copied proprietary artwork.

## Independent release hardening — 2026-08-14

Status: **✅ SIGNED OFF** after independent review identified deployment and
accessibility gaps not covered by the initial browser suite.

- Public assets moved to root `assets/` and referenced relatively; verified under
  FastAPI root mounts, static HTTP subpaths, and direct `file://` rendering.
- Root `index.html` preserves query strings and hashes when redirecting static
  deployments to `landing/`; FastAPI serves `/index.html` directly.
- Function dialog now moves focus inside, traps Tab/Shift+Tab, makes background
  regions inert, closes with Escape, and restores focus to its trigger.
- Marketplace filter chips expose `aria-pressed`; the featured rail is a named
  region; the mobile guide retains linked landing and marketplace navigation.
- WCAG contrast checks: metadata **5.82:1**, Get **5.90:1**, Added **5.27:1**,
  focus indicator **7.38:1** on the page surface.
- Visible copy, metadata, JSON-LD, README, and generated YAML instructions now
  consistently describe local continuous-video processing with optional alert
  metadata/snapshots and scoped local credentials.
- Production regression: signup 200, 120 cards, search/sort, Get/Added, YAML
  download, 8 guide sections/TOC links, zero unnamed controls or duplicate IDs,
  zero browser errors, and zero horizontal overflow at 390px.

## Image artwork and detailed module cards — 2026-08-15

Status: **✅ SIGNED OFF**

- Replaced generated initials/CSS artwork with **120 repository-owned SVG image
  assets**, one for every catalog ID, plus a deterministic image fallback.
- Artwork uses 21 semantic pictogram families, 12 color palettes, and a unique
  visual signature per module; all SVGs are script-free, locally served, and
  generated reproducibly by `scripts/generate_marketplace_icons.py`.
- Replaced compact rows with independent module cards showing image artwork,
  name, operational tagline, module ID, category, plan tier, runtime,
  configurable controls, Get/Added state, and a dedicated details action.
- Category sorting now groups all 120 cards beneath nine labeled category
  sections with concise operational descriptions and per-section counts.
- Details dialog now repeats the module image, exposes a four-part implementation
  profile, and presents human-readable configuration names alongside exact keys.
- Asset verification: **120 cards, 120 `<img>` elements, 120 unique module image
  URLs, 120 HTTP 200 responses, 120/120 catalog-to-file mappings**, valid XML for
  every SVG, and a deliberately broken source recovered through `_fallback.svg`.
- Accessibility: decorative card images use empty alt text beside visible module
  names; explicit dimensions prevent layout shift; card labels meet WCAG AA
  contrast (**4.60:1** and **4.93:1**); focus behavior and named controls retained.
- Responsive/browser verification: two-column desktop cards and 390px single-
  column cards visually reviewed; zero console/page/request errors, zero mobile
  horizontal overflow, static HTTP and direct `file://` image loading pass.
- Production verification: Docker image `nexus-vision-ai:test` green, all public
  routes and workflows green, and marketplace registry **120 registered, 0 errors**.

## Impeccable release audit — 2026-08-15

Status: **⚠️ FINAL INDEPENDENT REVIEW PENDING**

- Four staged-index review rounds found modal isolation, catalog/runtime contract,
  generated-YAML, detector-status, fail-open configuration, snapshot-delivery,
  unauthenticated door control, insecure TLS defaults, enumerable subscriptions,
  partial-delivery retry loss, UTC scheduling, readiness, failed-unlock status,
  multi-badge tailgating, claims, canonical, and accessibility defects. Every finding was reproduced,
  remediated, and assigned regression coverage before this final review.
- Modal isolation preserves prior `inert` state, keeps the selection tray hidden from
  assistive technology while open, traps focus, supports Escape, and restores focus.
  Module names are real headings outside buttons; all public configuration and guide
  tables have captions, scoped headers, table heads, and table bodies.
- The AST catalog builder requires a `MarketplaceFunction` subclass, derives and
  validates each function's actual `camera.zones` geometry contract, and publishes
  `camera_zones` separately from scalar `setting_keys`. **115 geometry-aware modules**
  map to their implementation keys; generation fails closed on unmapped geometry.
- Downloaded YAML uses `cameras[].detectors`, concrete runtime geometry such as
  `camera.zones.oneway_line`, and scalar `detector_settings`. A browser-generated
  config was copied into the exact release container and instantiated `wrong-way`
  with the expected geometry and runtime name: **1 selected / 1 instantiated**.
- Runtime composition loads 120 marketplace classes alongside ten core detectors,
  rejects loader errors, ID collisions, and unknown configured detector IDs, and
  merges shared settings with camera-specific overrides. `/detectors` returned
  `{"cam-1":["wrong-way"]}` from the exact release container.
- Door unlock now fails closed behind a non-placeholder `VISION_CONTROL_TOKEN`
  bearer token, validates door IDs, and returns unavailable when UniFi Access is not
  configured or the upstream request fails. Docker Compose binds port 8090 to
  localhost by default. Protect and Access TLS verification default on and accept
  an explicit private-CA bundle path.
- Subscription IDs use cryptographic randomness rather than timestamps, status
  lookup requires the constant-time-checked admin token, and same-second signups
  are covered by a collision regression.
- A required IANA `site.timezone` drives all 46 marketplace schedule consumers
  with DST-aware local time. `/health` is liveness-only; Docker checks `/ready`,
  which returns 503 until every configured worker is connected. Tailgating
  allowance scales with recent badge events.
- Alert routing now embeds actual JPEG bytes in configured outbound JSON payloads.
  Base44's internal token is sent only to the Base44 endpoint and is excluded from
  generic webhooks. The exact container wrote a real OpenCV JPEG (**631 bytes**), and
  tests verify both destinations receive decodable JPEG content. `privacy_mode:
  skeleton` centrally suppresses both local and outbound snapshots. Only HTTP 2xx
  delivery counts as sent. Dedup state is destination-specific: a successful
  secondary webhook cannot suppress retry to a failed primary NOC destination.
- Public metadata and signup choices use observable-signal wording such as
  possible-fall review and bed-edge movement analysis. Detector cards avoid identity,
  intent, legal-compliance, safety-outcome, unimplemented clip-retention, direct
  messaging-integration, and unsupported performance conclusions. Runtime alert
  messages use the same observable-signal standard.
- Current exact sources passed **38/38 tests** on the host and in Docker, Python compilation,
  storefront/catalog JavaScript syntax, deterministic catalog/icon regeneration,
  whitespace validation, declared-requirements audit, and a full installed-image
  `pip-audit` with **no known vulnerabilities**. The image upgrades the Ubuntu
  packaging baseline to `pip 26.2.1` and `wheel 0.48.0`.
- Generated artifacts are synchronized at **120 catalog IDs, 120 module SVGs, 120
  icon-manifest mappings, and one fallback SVG**. Generated-set SHA-256:
  `1dce5c9f0d446c8c626610bde7d5eefbe51e6595c21e2af12207c89c33713115`.
- The exact candidate Docker image built with IANA timezone data and the audited
  packaging toolchain (manifest-list
  `sha256:b4211adf1487442122eee3ac791a7be656da13ac3aee69f27f4978e8bffe35e2`).
  A CPU-profile container opened a real local video stream and `/ready` returned
  **1/1 streams up**. Live API checks confirmed `{"cam-1":["wrong-way"]}`,
  cryptographically random `SUB-` IDs, 401 for missing/wrong admin tokens, 200
  for the configured admin token, 401 for missing/wrong control tokens, and 503
  rather than false success when Access is unavailable.
- Chromium QA passed at **320, 390, 768, and 1440 px** for static root, project
  subpath, direct `file://`, and production-container modes. Coverage includes all
  120 images, filter/sort/search/empty states, modal semantics and focus isolation,
  geometry-aware YAML download, XSS resistance, image fallback, post-submit visual
  and `aria-pressed` reset, zero browser/network errors, and zero page overflow.

## 2026-08-16 — 130-function storefront layout repair

- **Root cause:** `storefront/index.html` loaded `marketplace.css` without first loading
  `tokens.css` and the local Archivo font. The override stylesheet therefore received
  undefined design tokens and Chromium fell back to browser typography and spacing.
- **Dependency repair:** the storefront now preloads `archivo-variable.woff2`, loads
  `tokens.css`, and only then loads `marketplace.css`. A public-page regression test
  locks that order.
- **Layout repair:** all ten UniFi Access release modules remain present in a keyboard-
  accessible horizontal shelf; the category and plan filters now live in a compact,
  labeled two-tier command bar; mobile module facts use a stable 2 × 2 matrix.
- **Measured improvement:** hero height changed from 1,383 to 948 px at 1440 px and
  from 3,090 to 1,246 px at 390 px. Sticky controls changed from 179/149 px to 95 px
  at 1440/390 px. The representative 390 px card changed from 310 to 271 px.
- **Browser gate:** Chromium passed at 1440, 390, and 320 px with 130 cards, 9
  categories, 10 release cards, Archivo active, no horizontal page overflow,
  scrollable release shelf, no unlabeled form controls, no duplicate IDs, and zero
  request, console, or page errors. Category filtering returned 9 Retail & QSR
  modules; search returned 6 queue modules; A–Z sort, modal focus/Escape, selection,
  and tray clearing all passed.

## 2026-08-16 — 130 custom transparent service illustrations

- **Canonical scene plan:** every catalog ID has one concrete subject/context/signal/
  composition record in `assets/module-art/scene-plan.json`; exact ID equality and
  ordering are locked by tests. SHA-256:
  `8015b708641b9116d4dfc0ae3ef16c44acb83d134fa69224d5ab7a1c55627a04`.
- **Generation contract:** `generate_module_art.py` now derives prompts from that
  text-free scene plan rather than catalog names or taglines. The prompt registry
  explicitly rejects typography, labels, logos, text-bearing panels, colored tiles,
  gradients, borders, and frames.
- **Processing contract:** `process_service_art.py` removes only edge-connected white
  backgrounds, preserves enclosed light details, crops alpha bounds, and centers the
  subject on a lossless optimized 320 × 320 transparent WebP canvas.
- **Exact asset gate:** 130 catalog IDs resolve to 130 WebPs with no missing or extra
  stems, all four corners transparent, every file under 100 KB, 130 unique SHA-256s,
  and no perceptual near-duplicate pairs. Total rich-art weight is **2,053,514 bytes**;
  the largest asset is **54,612 bytes**.
- **Visual/OCR gate:** all 130 assets were reviewed at 96 px and 48 px proxies plus
  full-size inspection of every OCR candidate. Six OCR guesses were geometric false
  positives. One ambiguous H-like shelf ornament in `library-zone-count` was rejected
  and replaced with a cleaner three-zone library scene before final verification.
- **Unboxed integration:** rich WebPs and deterministic SVG fallbacks render with
  transparent backgrounds and `object-fit: contain` in Access shelf, catalog cards,
  and details modal; the previous colored gradient icon tiles and decorative wells
  are removed.
- **Final browser gate:** Chromium fetched and decoded all 130 WebPs as 320 × 320
  image/webp resources, confirmed exact manifest equality and transparent card/modal
  styles, and passed at 1440, 390, and 320 px with zero request, console, page, or
  horizontal-overflow errors. Stable screenshots were visually reviewed after UI
  animation and rail positioning completed.
- **Regression gate:** artwork tests passed **17/17**, full repository tests passed
  **150/150**, and `git diff --check` passed after the final replacement.

## 2026-08-17 — Exact 100-function Railway release

- **Publication authority:** `src/marketplace/active-function-ids.json` selects exactly
  100 active functions: the commercially ranked top 80 retained contracts plus 20
  independently implemented vendor-pattern plugins. The source/archive registry retains
  271 contracts for compatibility; `storefront/catalog.json` and `catalog.js` contain
  100 unique IDs exactly equal to the active manifest. Sorted-ID SHA-256:
  `a830061a1abd7c47017b63bd740111ded4eb86c9c1ef3a25a87b3debcd5c9bda`.
- **Artwork gate:** the active publication set has exactly 100 transparent WebPs totaling
  **1,469,470 bytes**; 171 retired WebPs totaling **2,527,706 bytes** remain under the
  archive path. Active hash-set SHA-256:
  `745f0d0a3f5db9a102bace895d02495b5a50ebd9dee8bcd123fd04737115d55a`.
- **Visual/OCR disposition:** Tesseract 5.5.3 scanned all 100 active WebPs without
  processing errors and produced 35 candidates. Full contact-sheet inspection found
  geometric false positives only: **0 true words, digits, logos, watermarks, UI labels,
  or text-bearing signs**.
- **Container gate:** the exact staged source built for Linux AMD64 and runs as its
  non-root user in CPU mode. Host and in-container probes served complete declared
  response bodies, reported `unlicensed`, denied paid runtime, returned fail-closed
  readiness HTTP 503, and denied physical control HTTP 503. Runtime image manifest
  (excluding the BuildKit provenance attestation):
  `sha256:e0beb8c9f40bdc29129a94bf2551dbc6b95a1fc4a555edfc4418b9394b35d063`.
- **Public artifact equality:** catalog JSON is 88,991 bytes with SHA-256
  `12d74ca20de083b1e1e96aba6ae4e17853e6676c026966bed3be53b3b969fca2`;
  catalog JS is 89,171 bytes with SHA-256
  `3d1a75964b83728e91cbfc25ed7bd67a161101a79c3dccbad4c4fce65d381b5b`.
- **Browser gate:** Chromium passed landing, storefront, and guide at 1440, 390, and
  320 px. Each storefront run rendered 100 cards and decoded 110 image instances with
  zero broken images, request failures, console errors, page errors, or horizontal
  overflow. The original retail landing page remains the public root.
- **Licensing and control gate:** configuration-specific readiness denial, no-I/O public
  health, deny-all missing trust material, runtime refresh-error fail-closed behavior,
  appliance-bound signed grants, separate `access-control` capability, explicit allowlist,
  operator intent/reason, idempotency, and redacted control audit are regression-tested.
  Only public Ed25519 verification keys belong in the persistent trust store; private
  signing keys are prohibited from the image, environment, and customer mounts.
- **Persistence gate:** the subscription database, seeded site config, license lock, and
  public-only trust store remained byte-identical across repeated replacement with the
  rebuilt container on the same `/data` mount. Evidence snapshots are bounded by 30-day
  age, 5,000-file count, and 5 GiB quota defaults.
- **Regression gate:** clean staged-snapshot discovery passed **258/258 tests**;
  deterministic catalog generation/check produced exactly 100 entries; Python compilation,
  entrypoint shell syntax, Compose validation, XML parsing, staged secret screening, and
  whitespace checks passed. `.hallmark/` and `test-results/` remain outside Git and the
  Docker release context.
- **Hosted scope:** Railway is a credential-free CPU storefront/management plane with
  persistent state rooted under `/data`. No UniFi credentials, RTSP streams, private
  entitlement signing keys, appliance physical-control authority, or test fixtures are
  part of the hosted release. Missing production public verification keys intentionally
  keep paid analytics unlicensed and fail-closed.
