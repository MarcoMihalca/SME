"""
Interfața în linie de comandă (CLI) și formatarea rapoartelor în consolă.
Dacă aplicația este pornită simplu (`python main.py`), deschide direct Dashboard-ul Web
unde utilizatorul poate vedea și selecta portul USB (COM) din interfața grafică.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from .connection import (
    detect_preferred_usb_port,
    normalize_com_port,
    print_serial_ports,
)
from .csv_exporter import CsvExporter
from .models import PxrSnapshot, SerialConnectionConfig
from .reader import acquire_pxr_snapshot


def print_console_snapshot(
    snapshot: PxrSnapshot,
    show_settings_and_events: bool = True,
    csv_status: Optional[str] = None,
) -> None:
    """Afișează în consolă raportul structurat cu toate datele din `PxrSnapshot`."""
    print("\n" + "=" * 78)
    print(f" RAPORT EATON NZMH4-PX1600-TAZ + NZM4-XBSM-TAZ-N ({snapshot.connection_desc})")
    print(f" Timestamp: {snapshot.timestamp}")
    if csv_status:
        print(f" Fișier CSV: {csv_status}")
    print("=" * 78)

    print("\n--- 1. STARE DISJUNCTOR ȘI UNITATE PXR25 ---")
    for k, v in snapshot.status_info.items():
        print(f"  {k:<32}: {v}")

    print("\n--- 2. VALORI MĂSURATE ÎN TIMP REAL ---")
    print(f"  {'Parametru':<38} | {'Valoare':>14} | {'Unitate':<6}")
    print("  " + "-" * 66)
    for m in snapshot.measurements:
        val_str = f"{m.value:14.2f}" if m.value is not None else "  Indisponibil"
        print(f"  {m.name:<38} | {val_str} | {m.unit:<6}")

    if show_settings_and_events and snapshot.protection_settings:
        print("\n--- 3. SETĂRI DE PROTECȚIE ACTIVE & CONFIGURAȚIE PXR25 ---")
        print(f"  {'Parametru':<38} | {'Registru':<17} | {'Valoare'}")
        print("  " + "-" * 72)
        for s in snapshot.protection_settings:
            print(f"  {s.name:<38} | {s.register:<17} | {s.formatted}")

    if show_settings_and_events and snapshot.event_history:
        print("\n--- 4. ISTORIC DECLANȘĂRI ȘI EVENIMENTE ---")
        for ev in snapshot.event_history:
            print(
                f"  [{ev.event_type} #{ev.event_id}] {ev.timestamp} -> {ev.cause} "
                f"({ev.currents})"
            )

    print("=" * 78 + "\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Monitorizare USB–RS485 (Modbus RTU) pentru Eaton NZMH4-PX1600-TAZ + NZM4-XBSM-TAZ-N. "
            "Rulat fără argumente, pornește automat Dashboard-ul Web cu selector de port COM."
        )
    )
    parser.add_argument(
        "--port",
        default="",
        help="Portul COM inițial (ex: COM5). Poate fi schimbat direct din Dashboard-ul Web.",
    )
    parser.add_argument(
        "--slave-id",
        type=int,
        default=1,
        help="Adresa Modbus Slave a unității PXR25 (implicit = 1)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=19200,
        choices=[9600, 19200, 38400, 57600],
        help="Viteza RS-485 (implicit PXR25 = 19200)",
    )
    parser.add_argument(
        "--parity",
        default="E",
        choices=["N", "E", "O"],
        help="Paritate RS-485: E=Even (implicit), O=Odd, N=None",
    )
    parser.add_argument(
        "--stopbits",
        type=int,
        default=1,
        choices=[1, 2],
        help="Stop bits RS-485 (implicit = 1)",
    )
    parser.add_argument(
        "--format",
        choices=["fixed", "float"],
        default="fixed",
        help="Formatul registrelor PXR25: 'fixed' (0x1800) sau 'float' (0x1200)",
    )
    parser.add_argument(
        "--no-word-swap",
        action="store_true",
        help="Dezactivează inversarea cuvintelor (Low/High word) pe 32 biți",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Rulează în consolă în loc să deschidă Dashboard-ul Web",
    )
    parser.add_argument(
        "--watch",
        type=float,
        default=0.0,
        help="Interval în secunde pentru actualizare continuă în consolă (ex: --watch 2)",
    )
    parser.add_argument(
        "--csv",
        default="pxr25_log.csv",
        help="Fișierul CSV în care se salvează automat citirile (implicit: pxr25_log.csv)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8080,
        help="Portul HTTP pentru Dashboard-ul Web (implicit: 8080)",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="Listează porturile USB / COM disponibile în consolă și iese",
    )
    return parser


def run_cli(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.list_ports:
        print_serial_ports()
        return 0

    initial_port = (
        normalize_com_port(args.port) if args.port else detect_preferred_usb_port("COM5")
    )
    config = SerialConnectionConfig(
        port=initial_port,
        baudrate=args.baudrate,
        parity=args.parity,
        stopbits=args.stopbits,
        slave_id=args.slave_id,
        use_float=(args.format == "float"),
        word_swap=(not args.no_word_swap),
    )

    csv_exporter = CsvExporter(args.csv)

    # Implicit deschidem direct Dashboard-ul Web (unde utilizatorul își poate alege portul COM)
    if not args.console:
        from .web.server import run_dashboard_server

        run_dashboard_server(
            config=config,
            csv_exporter=csv_exporter,
            host="127.0.0.1",
            port=args.web_port,
            interval_sec=args.watch if args.watch > 0 else 2.0,
        )
        return 0

    # Mod consolă (--console)
    try:
        first_iter = True
        while True:
            snapshot = acquire_pxr_snapshot(
                config=config,
                include_settings_and_events=first_iter,
            )
            rows = csv_exporter.append_snapshot(snapshot)
            csv_msg = f"{csv_exporter.csv_path} ({rows} înregistrări)"

            print_console_snapshot(
                snapshot=snapshot,
                show_settings_and_events=first_iter,
                csv_status=csv_msg,
            )
            first_iter = False

            if args.watch <= 0:
                break
            time.sleep(args.watch)
    except KeyboardInterrupt:
        print("\nMonitorizare oprită de utilizator.")
    except Exception as exc:
        print(f"\n[EROARE] {exc}", file=sys.stderr)
        return 1

    return 0
