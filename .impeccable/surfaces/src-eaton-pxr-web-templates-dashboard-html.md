---
version: 1
slug: "src-eaton-pxr-web-templates-dashboard-html"
primary_target: "src/eaton_pxr/web/templates/dashboard.html"
related_targets: ["src/eaton_pxr/web/templates/login.html"]
---

# Surface Brief — SME Eaton PXR25 Web Login & Dashboard

- **Scope:** `src/eaton_pxr/web/templates/login.html` & `src/eaton_pxr/web/templates/dashboard.html`
- **Visitor Mode:** `operate` (code-led)
- **Audience & Job:** Faculty, electrical engineering students (`user`), and commissioning/maintenance administrators (`admin`) monitoring chained Eaton `NZMH4-PX1600-TAZ` (PXR25) circuit breakers over USB–RS485 in brightly lit university labs or switchboard rooms, with optional dark theme for low-light control desks.
- **Primary Tasks:** Authenticate cleanly at `/login` into role-governed session; monitor breaker state, RS-485 daisy-chain topology, `Ir` overcurrent load margin, live Canvas charts, and 8 ANRE/EN 50160 power-quality KPIs; operate Demo mode, CSV export, sound alerts, and (for `admin`) COM port / chain scan / RTC sync / DB flush / user administration & audit log.
- **Constraints:** Zero external CDNs or web fonts (`Content-Security-Policy: default-src 'self'`), Romanian UI copy, shared SQLite auth (`Login/users.db`), CSRF (`X-CSRF-Token`) on all mutating calls, existing `tests/test_bug_fixes.py` contracts preserved (`id="device-select"`, `id="btn-mode-simple"`, `id="btn-mode-advanced"`, `id="overcurrent-toast"`, `/api/sync-time`, no `id="view-averages"`).

## Direction contract

- **THESIS:** Transform a German-Swiss industrial switchgear technical catalog (Eaton / Moeller spec binder) into a high-trust operational SCADA desk — refusing generic dark-slate neon dashboards and nested gray SaaS cards in favor of flat porcelain daylight sheets, a committed deep engineering navy rail, and 1px hairline structural rigor.
- **OWN-WORLD:** Deep Switchgear Navy shell (`#0F294A`), Porcelain Lab Canvas (`#F7F8FA`) with pure white data sheets (`#FFFFFF`) and crisp 1px steel hairlines (`#CBD5E1`), Switchgear Cobalt primary accent (`#005FB8`), calibrated IEC three-phase signal inks (L1 `#005FB8`, L2 `#B45309`, L3 `#0F766E`), and semantic fault inks (Attention `#B45309`, Critical `#C81E1E`, Normal `#0F766E`), paired with an authentic low-light dark-room polarity (`#0C131D` ground, `#131C2B` surface, `#09182D` rail) toggled per user. Single workhorse sans (`"Segoe UI", system-ui, -apple-system, sans-serif`, fixed rem scale) plus tabular monospace (`"Cascadia Mono", Consolas, ui-monospace, monospace`) strictly for electrical readings, register addresses, and timestamps. Zero emojis, zero kickers above headings, zero colored left/right stripes above 1px, zero nested cards.
- **STORY:** At `/login`, the visitor immediately encounters a trustworthy engineering access gate clarifying read-only monitoring vs. administrative bus authority; after authenticating, they land on a calm, immediately scannable workspace where breaker state, RS-485 daisy-chain continuity, `Ir` overcurrent margin, and real-time phase charts read within two seconds.
- **FIRST VIEWPORT:** Fixed `248px` Switchgear Navy navigation rail on the left (brand header, views: Telemetrie, Utilizatori & Audit for `admin`, Cont & Parolă, active user/role badge, Zi/Noapte theme toggle, logout); main workspace opens with a slim `56px` command header (device dropdown `id="device-select"`, `Mod Simplu` / `Mod Avansat` switch, Demo Live toggle, sound mute/test, CSV export), compact hardware/RTC/DB control bar (gated to `admin` for mutations), the signature **RS-485 Daisy-Chain Topology Rail & `Ir` Load Ruler** strip (`#1 → #2 → ...` clickable live nodes beside the horizontal `Ir` load bar with 80% and 100% ticks), and below it live High-DPI Canvas charts paired with right-aligned tabular phase measurements.
- **FORM:** Candidate #3 (Catalog Switchgear Eaton / Moeller), `seed:38a174dd4631ac95`. Raised by declined challengers: flat figure-ground separation without nested card clutter (`aww2-zoo-gardens-guide-map`), strict `Mod Simplu` / `Mod Avansat` A/B sheet parity with right-aligned tabular numerals (`vernacular-ephemera-cassette-j-card`), and 1px hairline structural rigor with unmistakable state marks (`rw-centre-rail-reference-setting`).
- **FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
