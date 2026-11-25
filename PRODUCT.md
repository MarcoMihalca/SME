# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users fall into two authenticated roles using the Eaton NZMH4-PX1600-TAZ (PXR25) monitoring platform:

- **Users (`user`)**: University electrical engineering students, laboratory participants, and facility observers who inspect live circuit-breaker telemetry, view essential or detailed power-quality indicators and real-time charts, run Demo simulation mode, export CSV telemetry logs, mute or acknowledge local browser audio alarms, save personal UI preferences, and change their own password.
- **Administrators (`admin`)**: Lab supervisors, faculty instructors, commissioning engineers, and industrial maintenance leads who have all monitoring capabilities plus exclusive authority to configure serial COM port / baud rate, trigger Modbus daisy-chain rescans, acknowledge chain-break hardware halts or resume bus polling, synchronize device RTC clocks, manually flush the TimescaleDB write buffer, manage user accounts/roles/lockouts, and review authentication and control audit logs.

## Product Purpose

Provide real-time multi-device electrical telemetry, IEC/EN 50160 and Romanian ANRE power-quality diagnostics, overcurrent (`Ir`) threshold supervision, RS-485 daisy-chain topology break detection, automated CSV and TimescaleDB persistence, and role-governed authentication and user management for chained Eaton `NZMH4-PX1600-TAZ` (PXR25) circuit breakers and `NZM4-XBSM-TAZ-N` modules.

## Positioning

Unlike generic Modbus polling scripts or cloud-dependent SCADA portals, SME combines:

- **Physical RS-485 daisy-chain awareness**: Sequentially probes Modbus Slave IDs (`1..247`) and immediately surfaces downstream device drops and break points, allowing administrators to halt the RS-485 bus for safe hardware intervention.
- **Built-in Romanian ANRE and EN 50160 intelligence**: Automatically computes 8 power-quality KPIs each polling cycle, including breaker load percentage (`Ir`), phase current and voltage unbalance, neutral conductor loading, frequency deviation, distortion power (`D`), ANRE tariff penalty tier (`cos φ ≥ 0.92`), and required capacitor bank reactive compensation (`Q_comp` toward `0.95`).
- **Offline-first, zero-CDN architecture**: Runs entirely on a local Python `ThreadingHTTPServer` with native HTML5 Canvas rendering and custom inline SVG iconography, functioning reliably in air-gapped labs and switchboard rooms.
- **Shared role-governed access**: Uses a unified SQLite authentication store (`Login/users.db`) across both the web interface and the standalone desktop user-management utility (`Login/main.py`).

## Operating Context

- **Physical environment**: Primarily operated in brightly lit university electrical measurement laboratories and industrial switchboard rooms, with optional dark-mode support for dimly lit control desks.
- **Runtime environment**: Local or intranet HTTP server (`127.0.0.1:8080`) launched via `main.py`, communicating over USB–RS485 (Modbus RTU) and optionally persisting batches to Docker PostgreSQL 16 + TimescaleDB (`SME`) and `pxr25_log.csv`.
- **Language**: All user-facing labels, statuses, diagnostic alerts, and errors are in Romanian.

## Capabilities and Constraints

- Self-contained HTML/CSS/JavaScript/Canvas served directly by Python's stdlib `ThreadingHTTPServer` (`src/eaton_pxr/web/server.py`) with zero external network or CDN dependencies (strict `Content-Security-Policy` `'self'`).
- Cookie-based sessions (`sme_session`, `HttpOnly`, `SameSite=Lax`) backed by PBKDF2-HMAC-SHA256 (`310,000` iterations), CSRF token enforcement (`X-CSRF-Token`) on state-changing routes, account lockout after consecutive failures, per-IP login rate limiting, and audit logging (`auth_audit_log`).
- Strict RBAC matrix:
  - `user`: `telemetry:read`, `csv:export`, `ui:prefs`, `demo:run`
  - `admin`: all `user` permissions plus `hardware:control`, `db:flush`, `users:manage`, `audit:read`
- Standalone Tkinter utility (`Login/main.py`) and web server share `Login/users.db`.
- Existing unit-test contracts in `tests/test_bug_fixes.py` must continue to pass (`id="device-select"`, `id="btn-mode-simple"`, `id="btn-mode-advanced"`, `id="overcurrent-toast"`, `/api/sync-time`, and absence of `id="view-averages"`).

## Brand Commitments

- **Identity**: `Eaton NZMH4-PX1600-TAZ (PXR25) — SME`
- **Language**: Romanian engineering terminology throughout.
- **Reliability**: Offline-first operation without external fonts, scripts, or icon CDNs; unambiguous visual separation between live hardware telemetry and simulated Demo mode.

## Evidence on Hand

- Real Modbus RTU register map (`src/eaton_pxr/registers.py`) and decoder (`src/eaton_pxr/decoder.py`) for Eaton PXR25 fixed-point and float blocks, protection Group 1 (`0x0BB8..0x0BCF`), RTC (`0x0B68..0x0B6F`), and trip/event history (`0x2000..0x2021`).
- Verified power-quality calculation engine (`src/eaton_pxr/analytics.py`) and batch TimescaleDB writer (`src/eaton_pxr/database.py`, `docker/init_timescaledb.sql`).
- Interactive Demo telemetry stream in the web dashboard when no physical Modbus hardware is attached.
- Automated `unittest` regression suite (`tests/`).
- No commercial customer claims, external SLA metrics, or live hardware serial captures should be fabricated when hardware is disconnected.

## Product Principles

1. **Operational truth first**: Circuit-breaker state, overcurrent margin relative to `Ir`, and RS-485 chain breaks must read unambiguously within seconds.
2. **Safe separation of observation and actuation**: Standard users can inspect, simulate, and export without risking bus halts, clock writes, or configuration drift.
3. **Zero external dependencies**: Every chart, icon, font fallback, and interaction operates offline on local machines.
4. **Progressive technical depth**: `Mod Simplu` surfaces immediate operational telemetry; `Mod Avansat` reveals all 20 measurements, 8 power-quality KPIs, protection settings, event logs, and administrative tools.
