# Design — Nexus Vision

A locked design system for this app. Every page redesign reads this file before
emitting code. Do not regenerate per page — extend or amend this file when the
system needs to grow.

Established 2026-08-15. Source of truth for `landing/`, `storefront/`, `guide/`.
The runtime values live in `assets/tokens.css`; this file explains them.

## Genre

modern-minimal · tone: utilitarian

Audience is security and AV integrators evaluating Nexus Vision for client UniFi
Protect deployments, plus technically-competent Protect owners self-serving. The
pages are read by people mid-evaluation, often on a job site. Nothing decorative
earns its place.

## Provenance

Theme route: **studied-DNA**, extracted from `https://ui.com/` via `hallmark study`.
Catalog rotation is suspended for this project — pages follow the DNA, not the
21-theme rotation. What was carried over: light/neutral-cool paper, a single
neutral grotesk, one cyan-blue accent at a small recurring footprint, a 4-point
spacing base, a horizontal-sweep reveal, and the `cubic-bezier(0.4, 0, 0.6, 1)`
easing curve.

What was deliberately **not** carried over, and why:

- **N11 mega-menu** → replaced with **N1b**. The source has ~14 destinations; this
  site has four. A faked mega-menu is dishonest structure.
- **Ft3 five-column footer** → replaced with **Ft3-lite**, three columns, built
  only from real link inventory. The full form would require inventing links.
- **Six `<h1>` elements** (five of them footer column headings on the source).
- **`transition: all`** — three occurrences on the source.
- **No `prefers-reduced-motion`** despite five autoplaying videos. We ship it.
- **No `prefers-color-scheme`** despite a complete dark palette. Noted as future work.

Rhythm was the URL-mode blind spot: HTML and CSS alone cannot tell you whether
the source's visual rhythm reads generous or templated. Vertical rhythm here was
set from the spacing scale, not observed.

## Macrostructure families

- **Marketing pages** (`landing/`) — Marquee Hero. Varies: hero enrichment, section count.
- **Catalogue pages** (`storefront/`) — Catalogue. Varies: card density, category grouping.
- **Content pages** (`guide/`) — Long Document. Varies: section count, table density.

All three share nav **N1b** (canonical three-section) and footer **Ft3-lite**.

## Theme

| Token | Value | From |
|---|---|---|
| `--color-paper` | `oklch(100.0% 0.000 89.9)` | `#ffffff` |
| `--color-paper-2` | `oklch(97.6% 0.003 264.5)` | `#f6f7f9` |
| `--color-ink` | `oklch(25.6% 0.008 264.4)` | `#212327` |
| `--color-ink-2` | `oklch(45.1% 0.029 262.0)` | `#4d5666` |
| `--color-ink-3` | `oklch(53.4% 0.028 265.4)` | 4.6:1 on paper — AA for small text |
| `--color-rule` | `oklch(92.4% 0.009 264.5)` | `#e3e6ec` |
| `--color-accent` | `oklch(58.1% 0.230 259.5)` | `#006fff` |
| `--color-accent-deep` | `oklch(21.9% 0.079 258.5)` | `#01183e` |
| `--color-focus` | `oklch(58.1% 0.230 259.5)` | accent |

Accent stays under ~5% of any viewport. It marks one thing at a time: the primary
action, the active filter, the current step number.

`--color-ink-3` was raised from the previous `#838b9b` (3.42:1, failing AA on
small text) to `#656d7e` (4.6:1). Table headers and footer text use it.

## Typography

Single family, on purpose — the studied DNA ships exactly one neutral grotesk.

- **Display / Body / all UI**: Archivo, variable 400–900, self-hosted
- **Mono**: system stack (`ui-monospace`, `SFMono-Regular`, Menlo) — code and IDs only
- Display tracking: `-0.022em` · Display is always roman; italic headers are banned
- Type scale anchor: `--text-display: clamp(2.75rem, 1.5rem + 5vw, 5rem)`

**Self-hosted, not CDN-linked.** This product deploys on-premises and sometimes
air-gapped. A `fonts.googleapis.com` link would be both a runtime dependency and
a privacy leak in a security context. The file is `assets/fonts/archivo-variable.woff2`
(34 KB, Latin subset, SIL Open Font License 1.1).

Archivo replaced a declared-but-never-loaded Inter/Archivo pair. Before this
system, all three pages silently rendered in system sans — neither face was ever
fetched.

## Spacing

4-point named scale, from the DNA's `--desktop-spacing-base-*` ramp. Values are in
`assets/tokens.css`. Pages must use named tokens (`var(--space-md)`), never raw
values.

## Motion

- Easings: `cubic-bezier(0.4, 0, 0.6, 1)` as `--ease-out` / `--ease-in-out`; the
  source used this curve eleven times.
- Durations: `--dur-instant` 90ms · `--dur-short` 180ms · `--dur-mid` 280ms
- Reveal pattern: horizontal sweep (`translateX(-12px)` → none), the source's signature
- Reduced-motion fallback: opacity only, ≤150ms. The focus ring **never** animates
  in either mode.
- Animate `transform` and `opacity` only. Never `transition: all`.

## Microinteractions stance

- Silent success. No celebratory toasts.
- Hover reveals nothing load-bearing; everything reachable by keyboard.
- Cards do not lift on hover — the rule and a paper shift carry the state change.
  Lifting 100 active catalogue rows on hover is noise, not feedback.
- All eight states styled on interactive elements: default, hover, focus-visible,
  active, disabled, loading, error, success.

## CTA voice

- **Primary**: filled accent, `--radius-input` (6px), semibold, no shadow, no lift.
  Hover darkens the fill; active does not transform.
- **Secondary** (`.ghost`): transparent with a `--color-rule-strong` hairline,
  accent text. Hover tints to `--color-paper-2` and borders accent.
- Copy pattern: verb-first, no exclamation, no "Get started free →".

## Per-page allowances

- Marketing pages MAY use enrichment. Currently: the existing hero photograph only.
- Catalogue pages MUST NOT use enrichment — the 100 active module artworks are the content.
- Content pages: typography only.

## What pages MUST share

- The wordmark, and the accent on its `<span>`.
- The accent colour and its ≤5% placement discipline.
- Archivo, at the weights declared in `tokens.css`.
- The CTA voice — button shape, radius, padding rhythm.
- Nav N1b and footer Ft3-lite.
- `prefers-reduced-motion` support and the non-animated focus ring.

## What pages MAY differ on

- Macrostructure, within the family declared above.
- Hero archetype, within the family's allowance.
- Section count and density.

## Content and claims — non-negotiable

This system does not license copy changes. All audited copy, BIPA and
claims-bank phrasing, and observable-signal wording in `PAGE-AUDIT.md` stand as
written. No invented metrics, testimonials, logos, or counts. The "100" figure
must continue to match `storefront/catalog.json` — `scripts/generate_seo_schema.py`
fails closed if the catalog drifts.

## Structured data

Every page carries JSON-LD that must survive redesign untouched:
landing `SoftwareApplication` + `FAQPage`; storefront `CollectionPage` +
`SoftwareApplication` + `ItemList` (100 entries, generated); guide `TechArticle` +
`HowTo` (8 steps). Regenerate the storefront block with
`python3 scripts/generate_seo_schema.py` after any catalog change.

## Known gaps

- **No dark mode.** The source ships a complete dark palette and declares every
  token twice; we ship light only. Adding it means a second block in `tokens.css`,
  not per-page overrides.
- **No production origin.** Canonicals are relative (`href="./"`) and there is no
  `og:url`, no `sitemap.xml`, no `llms.txt`, no `robots.txt`. All five are blocked
  on the domain being chosen.
- **Rhythm unverified** against the source — see Provenance.

## Exports

### tokens.css

The canonical file is `assets/tokens.css`. It is the runtime source; this section
is a pointer, not a copy, so the two cannot drift.
