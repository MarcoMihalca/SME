---
name: Eaton PXR25 SME Switchgear SCADA
description: Industrial German-Swiss switchgear specification sheet and operational SCADA telemetry system for Eaton NZMH4-PX1600-TAZ circuit breakers.
colors:
  switchgear-cobalt: "#005FB8"
  switchgear-cobalt-deep: "#004C97"
  switchgear-cobalt-solid-dark: "#0B66C3"
  cobalt-tint: "#EBF4FF"
  switchgear-navy: "#0F294A"
  navy-divider: "#1E3A5F"
  navy-night: "#081324"
  porcelain-canvas: "#F7F8FA"
  porcelain-sheet: "#FFFFFF"
  porcelain-subtle: "#F1F5F9"
  ink-slate: "#0F172A"
  ink-secondary: "#334155"
  ink-muted: "#475569"
  steel-hairline: "#CBD5E1"
  hairline-subtle: "#E2E8F0"
  dark-canvas: "#0C131D"
  dark-sheet: "#131C2B"
  dark-border: "#263449"
  iec-l1-blue: "#005FB8"
  iec-l2-amber: "#B45309"
  iec-l3-teal: "#0F766E"
  iec-neutral-violet: "#6D28D9"
  iec-ground-slate: "#475569"
  fault-crimson: "#C81E1E"
  fault-crimson-deep: "#991B1B"
typography:
  display:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, BlinkMacSystemFont, \"Roboto\", sans-serif"
    fontSize: "1.62rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, BlinkMacSystemFont, \"Roboto\", sans-serif"
    fontSize: "1.2rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  title:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, BlinkMacSystemFont, \"Roboto\", sans-serif"
    fontSize: "0.94rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "0em"
  body:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, BlinkMacSystemFont, \"Roboto\", sans-serif"
    fontSize: "0.85rem"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "0em"
  label:
    fontFamily: "\"Cascadia Mono\", ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "0.78rem"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "0em"
    fontFeature: "tnum"
rounded:
  xs: "2px"
  sm: "3px"
  default: "4px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "14px"
  xl: "20px"
  rail-width: "248px"
components:
  button-primary:
    backgroundColor: "{colors.switchgear-cobalt}"
    textColor: "{colors.porcelain-sheet}"
    rounded: "{rounded.default}"
    padding: "6px 11px"
  button-primary-hover:
    backgroundColor: "{colors.switchgear-cobalt-deep}"
    textColor: "{colors.porcelain-sheet}"
    rounded: "{rounded.default}"
    padding: "6px 11px"
  button-secondary:
    backgroundColor: "{colors.porcelain-sheet}"
    textColor: "{colors.ink-secondary}"
    rounded: "{rounded.default}"
    padding: "6px 11px"
  button-ok:
    backgroundColor: "{colors.iec-l3-teal}"
    textColor: "{colors.porcelain-sheet}"
    rounded: "{rounded.default}"
    padding: "6px 11px"
  button-danger:
    backgroundColor: "{colors.fault-crimson}"
    textColor: "{colors.porcelain-sheet}"
    rounded: "{rounded.default}"
    padding: "6px 11px"
  input-field:
    backgroundColor: "{colors.porcelain-sheet}"
    textColor: "{colors.ink-slate}"
    rounded: "{rounded.default}"
    padding: "6px 10px"
  sheet-card:
    backgroundColor: "{colors.porcelain-sheet}"
    textColor: "{colors.ink-slate}"
    rounded: "{rounded.default}"
    padding: "14px 16px"
  ind-pill-info:
    backgroundColor: "{colors.cobalt-tint}"
    textColor: "{colors.switchgear-cobalt}"
    rounded: "{rounded.default}"
    padding: "2px 7px"
  nav-rail-item-active:
    backgroundColor: "{colors.switchgear-cobalt}"
    textColor: "{colors.porcelain-sheet}"
    rounded: "{rounded.default}"
    padding: "10px 12px"
---

# Design System: Eaton PXR25 SME Switchgear SCADA

## Overview

**Creative North Star: "The Industrial Switchgear Binder"**

This design system transforms a German-Swiss electrical engineering switchgear catalog (Eaton / Moeller specification binder style) into an air-gapped operational SCADA interface for university electrical engineering labs and industrial switchboard rooms. Light-first porcelain worksheets maximize daylight readability under overhead fluorescent lighting, while an authoritative Switchgear Navy navigation shell frames system status, role authority, and RS-485 bus controls cleanly without visual noise.

Across both the authentication gate (`/login`) and multi-device telemetry desk (`/`), information density is governed by crisp `1px` steel hairlines, flat porcelain figure-ground separation, IEC three-phase signal discipline, and right-aligned tabular numerals (`tabular-nums`). The system deliberately rejects dark-slate glowing neon aesthetics, nested SaaS sub-cards, decorative thick accent stripes, and external CDN dependencies so every telemetry frame renders instantaneously offline.

**Key Characteristics:**
- Light-default Porcelain Lab Canvas (`#F7F8FA`) paired with pure white data sheets (`#FFFFFF`) and a committed Switchgear Navy left rail (`#0F294A`), plus a calibrated per-user dark-room polarity (`#0C131D` / `#131C2B`).
- Zero-CDN system typography using `"Segoe UI"` for Romanian prose and `"Cascadia Mono"` (`tabular-nums`) strictly for electrical readings, Modbus register addresses, timestamps, and numeric badges.
- Flat structural sheets divided internally by `1px` steel borders (`#CBD5E1`) and hairlines (`#E2E8F0`) with a disciplined `4px` technical corner radius.
- Calibrated IEC three-phase waveform palette (`#005FB8`, `#B45309`, `#0F766E`, `#6D28D9`, `#475569`) paired with separate high-contrast solid control inks (`>= 4.5:1` with white labels) across both Light and Dark themes.
- Custom High-DPI HTML5 Canvas plots and RS-485 topology / `Ir` overcurrent load ruler components with zero third-party chart or icon packages.

## Colors

The palette pairs high-luminance daylight porcelain grounds with Switchgear Navy structural anchors, Cobalt action accents, and non-overlapping IEC electrical phase and alarm semantics.

### Primary
- **Switchgear Cobalt** (`#005FB8`): Primary interactive accent for active navigation items, active view toggles (`Mod Simplu` / `Mod Avansat`), primary CTAs, active RS-485 chain nodes, and focus outlines (`:focus-visible`). In dark mode, borders, links, and focus outlines shift to luminous Cobalt (`#3898EC`), while solid white-text button surfaces use dedicated `#0B66C3` (`#0953A0` hover) to maintain `>= 4.5:1` contrast.
- **Cobalt Tint** (`#EBF4FF`): Soft tint for text selections, `.ind-pill.info` role badges (notably `admin`), and hover states (`rgba(56, 152, 236, 0.14)` in dark mode).

### Secondary
- **Switchgear Navy** (`#0F294A`): Structural brand shell for the left navigation rail (`248px`), `/login` specification binder column, and bottom toast notifications (`#081324` in dark mode). Paired with `--rail-border` (`#1E3A5F` / `#1E324F`), `--rail-text` (`#E2E8F0`), and `--rail-muted` (`#93C5FD`).
- **IEC Three-Phase & Ground Inks**: Strictly dedicated to live waveforms, legend dots, and phase ledger bars — Phase L1 (`#005FB8` light / `#38BDF8` dark), Phase L2 (`#B45309` light / `#F59E0B` dark), Phase L3 (`#0F766E` light / `#34D399` dark), Neutral `I_N` (`#6D28D9` light / `#C084FC` dark), and Earth Fault `I_G` (`#475569` light / `#CBD5E1` dark) so `I_G` never collides visually with the red dashed `Prag Ir` limit line.
- **Semantic Alarm & Status Ramps**: Normal / Verified in Teal (`#0F766E` dot/border, `#065F46` ink on `#ECFDF5` with `#99F6E4` border), Attention in Amber (`#B45309` / `#92400E` on `#FFFBEB` with `#FDE68A`), and Overcurrent / Critical Fault in Crimson (`#C81E1E` / `#991B1B` on `#FEF2F2` with `#FECACA`). Solid white-text status buttons (`btn-ok`, `btn-danger`) use deep ink fills (`#0F766E`, `#C81E1E`) in both themes.

### Neutral
- **Porcelain Canvas** (`#F7F8FA`) & **Porcelain Sheet** (`#FFFFFF`): Main workspace background and flat data containers (`#0C131D` / `#131C2B` in dark mode).
- **Porcelain Subtle** (`#F1F5F9`): Banded sheet headers (`.sheet-head`), table column headers (`th`), legend chips, mode switch wells, and disabled input backgrounds (`#1A2538` in dark mode).
- **Ink Slate / Secondary / Muted** (`#0F172A`, `#334155`, `#475569`): Primary readings, control labels, and secondary metadata (`#F1F5F9`, `#CBD5E1`, `#94A3B8` in dark mode).
- **Steel Hairline & Subtle Divider** (`#CBD5E1`, `#E2E8F0`): Primary `1px` sheet frames and internal hairline dividers (`#263449`, `#1E293B` in dark mode).

### Named Rules
**The Polarity Contrast Split Rule.** Never paint a bright dark-mode foreground pen (`#3898EC`, `#34D399`, `#F87171`) behind `#FFFFFF` button labels. Solid controls in dark theme bind to dedicated deep surface fills (`--btn-accent-bg: #0B66C3`, `--btn-ok-bg: #0F766E`, `--btn-danger-bg: #C81E1E`) to guarantee `>= 4.5:1` legibility.

**The Semantic Non-Collision Rule.** Keep `I_G` earth-fault traces on neutral steel slate (`#475569` / `#CBD5E1`) and admin role pills in Cobalt `.info`, reserving Crimson (`--danger`) exclusively for `Prag Ir` overcurrent thresholds and fault alarms and Teal (`--ok`) for active/normal operational health.

## Typography

**Display & Body Font:** `"Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, "Roboto", sans-serif`
**Label / Telemetry Mono Font:** `"Cascadia Mono", ui-monospace, SFMono-Regular, Consolas, monospace`

**Character:** Crisp technical neutrality engineered for zero-CDN Windows and cross-platform offline rendering, pairing clear Romanian operational UI typography with aligned `tabular-nums` instrumentation readouts.

### Hierarchy
- **Display** (`700`, `1.62rem`, `1.2`, `-0.02em`): Switchgear specification heading (`Eaton NZMH4-PX1600-TAZ`) on `/login`.
- **Headline** (`700`, `1.2rem`–`1.38rem`, `1.25`, `-0.015em`): Topbar operational view title (`.topbar h1`) and authentication sheet heading (`.auth-sheet h2`).
- **Title** (`700`, `0.94rem`–`1.32rem`, `1.2`–`1.3`): Sheet headers (`.sheet-head h2`), `Ir` hero readouts (`.ir-stat-val`), and Canvas chart titles.
- **Body** (`400`–`600`, `0.85rem`–`0.95rem`, `1.45`–`1.5`): Form inputs, ledger labels, navigation links, and system descriptions (dashboard HTML root `15px`; login HTML root `16px`).
- **Label** (`600`–`700`, `0.72rem`–`0.8rem`, `1.35`): Monospace `tabular-nums` values, table headers, rail tags, `Ir` ruler ticks, and compact status pills.

### Named Rules
**The Monospace Discipline Rule.** Apply `.mono` (`font-family: var(--font-mono); font-variant-numeric: tabular-nums;`) exclusively to electrical quantities, Modbus register addresses, ISO/local timestamps, usernames/IDs, and numeric counters — never to surrounding Romanian prose labels.

## Layout

The workstation uses a directional sidebar-and-sheet layout engineered for high-density monitoring without viewport clutter:

- **Persistent Navigation Rail (Desktop):** Fixed `248px` Switchgear Navy rail sticky at `height: 100vh`, collapsing below `960px` into a slide-over drawer (`transform: translateX(-100%)` over a dimmed backdrop).
- **Sticky Command Topbar (`56px` min-height):** Single-row desktop header (`flex-wrap: nowrap` above `1180px`, `padding: 6px 16px`, `gap: 10px`) holding the view heading, connection status badge, active slave selector (`#device-select`), `Mod Simplu` / `Mod Avansat` segmented switch, Demo Live toggle, sound controls, and `Export CSV`. On non-telemetry routes (`admin`, `account`), `.topbar-right` hides so the header remains uncluttered; below `960px`, `.topbar` shifts to `position: static`.
- **Main Content Flow:** Padded `16px 20px 28px` up to `max-width: 1520px` with consistent `14px` vertical stacking (`#panel-telemetry`, `#panel-admin`, `#panel-account`, `.grid-2`) across all sheets so cards never collide at `0px`.
- **Responsive Breakpoints:** `1180px` (allow `.topbar` wrap), `1120px` (stack `.hero-strip` 1-col; collapse `.indicators-grid` 4-col to 2-col), `960px` (slide-over `.rail`, stack `.charts-grid` / `.simple-columns` / `.grid-2`, static `.topbar`), `860px` (`/login` 2-col -> 1-col stack), `600px` (compact `14px` gutters, 1-col KPIs, compact `.ir-tick-label` omission on `Ir` ruler).

## Elevation & Depth

Surfaces are **flat by default**. Structural hierarchy comes from `1px solid var(--border)` contrast (`#CBD5E1` on `#FFFFFF` over `#F7F8FA`) and `.sheet-head` subtle gray headers (`#F1F5F9`) rather than heavy drop shadows or concentric gray nested cards.

### Shadow Vocabulary
- **Sheet Resting (`--shadow-sm`)**: `0 2px 6px rgba(0, 0, 0, 0.06)` in Light (`0 2px 8px rgba(0, 0, 0, 0.3)` in Dark) — subtle grounding on `.sheet`, `.hw-bar`, `.auth-sheet`, and `.chain-node.active`.
- **Overlay Floating (`--shadow-md`)**: `0 12px 32px rgba(0, 0, 0, 0.14)` in Light (`0 16px 40px rgba(0, 0, 0, 0.55)` in Dark) — reserved exclusively for fixed overcurrent alert toasts, status toasts, and blocking RS-485 fault modals.

### Named Rules
**The Flat Sheet-No-Nesting Rule.** Partition content inside `.sheet` exclusively with `1px solid var(--border)` / `var(--border-subtle)` internal grid lines (`.simple-columns`, `.charts-grid`, `.indicators-grid`, `.ledger-rows`), removing redundant outer-edge hairlines (`border-right: none`, `border-bottom: none` on trailing grid rows/columns) instead of nesting bordered cards inside cards.

## Shapes

Every interactive primitive and container adopts an engineered rectangular technical corner language:
- **Standard Corner (`--radius: 4px`)**: Applied uniformly to `.sheet`, `.hw-bar`, `.btn`, `input`, `select`, `.rail-nav-btn`, `.chain-node`, `.badge`, `.ind-pill`, and `.alert-banner`.
- **Compact Sub-Control (`3px` / `2px`)**: `3px` for `.mode-btn` inside the `4px` `.mode-switch` well; `2px` for horizontal instrumentation meters (`.ir-ruler`, `.ledger-bar-track`).
- **Circular Indicators (`50%`)**: Applied strictly to `7px`–`8px` status dots (`.status-dot`, `.legend-dot`).

## Components

### Buttons
Minimal crisp rectangles (`4px` radius, `600` weight, `150ms ease` transitions, `white-space: nowrap`) with explicit hover darkening and `:focus-visible` `2px solid var(--accent)` ring (`2px` offset).
- **Shape:** Technical crisp rectangle (`4px`)
- **Primary (`.btn-primary` / `.btn-submit`):** Light `--btn-accent-bg` (`#005FB8`), hover `--btn-accent-hover` (`#004C97`); Dark `--btn-accent-bg` (`#0B66C3`), hover `--btn-accent-hover` (`#0953A0`); `#FFFFFF` text; `6px 11px` padding (`4px 8px` `.topbar .btn-sm`, `44px` height on `/login` `.btn-submit`).
- **Secondary (`.btn`):** `--surface` background, `--border` stroke, `--ink-secondary` text; shifts to `--surface-subtle` and `--ink-muted` border on hover.
- **Semantic Status (`.btn-ok`, `.btn-danger`, `.btn-warn`):** `.btn-ok` uses `#0F766E` (`#065F46` / `#115E59` hover) with `#FFFFFF` text; `.btn-danger` uses `#C81E1E` (`#991B1B` / `#B91C1C` hover) with `#FFFFFF` text; `.btn-warn` uses `--warn-bg`, `--warn-border`, and `--warn-ink`.

### Chips & Pills
- **Style:** `4px` radius, `2px 7px` padding, `1px` semantic border matching soft tinted ground (`.badge`, `.ind-pill`, `.perm-chip`, `.role-chip`).
- **States:** `.ok` (Teal), `.warn` (Amber), `.danger` (Crimson), `.info` (Cobalt `--accent-soft` / `--accent` for `admin` roles), and neutral steel for idle states and `user` roles.

### Sheets & Containers
- **Corner Style:** `4px`
- **Background:** `--surface` (`#FFFFFF` / `#131C2B`), optional `.sheet-head` header band in `--surface-subtle` (`#F1F5F9` / `#1A2538`)
- **Shadow Strategy:** Rests on `--shadow-sm` with `1px solid var(--border)` outer frame
- **Border:** `1px solid var(--border)` outer; `1px solid var(--border-subtle)` internal cell rules
- **Internal Padding:** `10px 16px` header bands; `13px 15px` KPI cells; `14px 16px` charts and hero columns; `9px 16px` ledger rows

### Inputs & Selects
- **Style:** `1px solid var(--border)` stroke on `--surface` ground, `4px` radius, `6px 10px` padding (`42px` height on `/login`), `font-size: 0.85rem` (`0.95rem` login), `caret-color: var(--accent)`.
- **Focus:** Shifts border cleanly to `--accent` (`#005FB8` light / `#3898EC` dark) with global `:focus-visible` outline (`2px solid var(--accent)`, `2px` offset).
- **Disabled:** `opacity: 0.55`–`0.6`, `cursor: not-allowed`, `--surface-subtle` fill (used cleanly to indicate RBAC read-only observation mode for `user` accounts).

### Navigation Rail & Sticky Topbar
- Fixed `248px` `--rail-bg` (`#0F294A` / `#081324`) rail holding brand lockup, custom `1.75px` inline SVG icons, navigation buttons (`10px 12px` padding, `#005FB8` active state), active slave count `.rail-nav-tag`, RBAC user/role badge, Zi/Noapte theme toggle, and logout button. Collapses on `<= 960px` viewports to an off-canvas drawer triggered by `.mobile-menu-btn`.

### Signature Components
- **RS-485 Topology Rail & `Ir` Load Ruler (`.hero-strip`):** Two-column hero sheet uniting clickable Modbus slave chain buttons (`#1 • 460 A → #2 • 418 A`) alongside the `Ir` overcurrent readout (`Imax`, `Ir`, `%`) and calibrated horizontal meter track featuring an orange warning tick at `left: 80%` synchronized directly above `.ir-tick-80` (`80% Atenție`, collapsing to `80%` below `600px`).
- **Adaptive High-DPI Canvas Telemetry Charts (`drawSingleChart`):** Zero-dependency `devicePixelRatio`-scaled time-series plots reading active light/dark CSS tokens live via `getComputedStyle`, measuring widest Y-axis label dynamically (`padL`), clamping non-negative series at `0.0` via `clampZero`, aligning adjacent chart canvases via `margin-top: auto`, and drawing dashed Crimson `Prag Ir` threshold lines when measured load reaches `>= 65%` of `Ir`.

## Do's and Don'ts

### Do:
- **Do** keep `4px` crisp technical corners (`--radius`) on all sheets, buttons, inputs, badges, and rail navigation items across light and dark modes.
- **Do** enforce `14px` flex/grid gaps between top-level `.sheet` and `.hw-bar` blocks while using `1px` internal hairlines inside sheets (removing trailing bottom/right grid borders).
- **Do** pair bright dark-mode accents (`#3898EC`, `#34D399`, `#F87171`) exclusively with borders, chart lines, and dark-surface text; use dedicated `--btn-accent-bg` (`#0B66C3`), `--btn-ok-bg` (`#0F766E`), and `--btn-danger-bg` (`#C81E1E`) behind `#FFFFFF` button labels.
- **Do** restrict `.mono` and `font-variant-numeric: tabular-nums` strictly to numeric measurements, addresses, IDs, counters, and timestamps.
- **Do** render all icons as inline `stroke-width="1.75"` SVGs and keep HTML templates 100% self-contained with zero external URLs or CDN imports (`Content-Security-Policy: default-src 'self'`).

### Don't:
- **Don't** add glowing neon gradients, blurred glassmorphism panels, heavy `box-shadow` depth cards, or nested bordered cards inside `.sheet` containers.
- **Don't** use thick colored left/right border stripes (`3px`–`4px`) on alerts, banners, or KPI cells; communicate state through `1px` semantic borders, subtle tinted backgrounds, and crisp SVG/pill marks.
- **Don't** use raw Unicode emoji or symbol glyphs (`↻`, `⚠`, `⚡`) for UI buttons or alert indicators, and don't add decorative uppercase kickers above section titles.
- **Don't** share Crimson (`--danger`) between `Prag Ir` limit thresholds and `I_G` earth-fault telemetry curves or allow negative Y-axis margin padding on inherently non-negative electrical series.
