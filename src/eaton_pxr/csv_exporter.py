"""
Modul dedicat creării și actualizării fișierelor CSV cu valorile citite din lanțul PXR25
(atât pentru fiecare Slave ID individual, cât și rândul de medii AVERAGE).
"""

from __future__ import annotations

import csv
import os
from typing import List, Optional
from .models import MeasuredValue, PxrSnapshot
from .registers import PXR25_PARAMETERS


class CsvExporter:
    """
    Gestionează scrierea citirilor din disjunctoarele NZMH4-PX1600-TAZ într-un fișier CSV.
    Folosește codificarea UTF-8 cu BOM (`utf-8-sig`) pentru deschidere directă în Microsoft Excel.
    """

    def __init__(self, csv_path: str = "pxr25_log.csv") -> None:
        self.csv_path = os.path.abspath(csv_path)
        self.row_count = 0
        self._initialize_file()

    def _initialize_file(self) -> None:
        headers = [
            "Timestamp",
            "Slave_ID",
            "Stare_Principala",
            "Stare_Secundara",
            "Cauza_Stare",
        ] + [f"{p.key} ({p.unit})" if p.unit else p.key for p in PXR25_PARAMETERS]

        parent_dir = os.path.dirname(self.csv_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        if not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0:
            with open(self.csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            self.row_count = 0
        else:
            try:
                with open(self.csv_path, mode="r", encoding="utf-8-sig") as f:
                    self.row_count = max(0, sum(1 for _ in f) - 1)
            except Exception:
                self.row_count = 0

    def append_snapshot(self, snapshot: PxrSnapshot) -> int:
        """Adaugă un rând nou în CSV pentru un `PxrSnapshot` individual."""
        row = [
            snapshot.timestamp,
            f"ID_{snapshot.slave_id}",
            snapshot.status_info.get("Stare Principală Disjunctor", ""),
            snapshot.status_info.get("Stare Secundară Unitate PXR", ""),
            snapshot.status_info.get("Cauză Stare / Eveniment", ""),
        ]
        for m in snapshot.measurements:
            row.append(f"{m.value:.2f}" if m.value is not None else "")

        with open(self.csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(row)

        self.row_count += 1
        return self.row_count

    def append_averages_row(
        self,
        timestamp: str,
        active_count: int,
        averages: List[MeasuredValue],
    ) -> int:
        """Adaugă în CSV rândul cu mediile calculate pe toate aparatele active din lanț."""
        if active_count <= 0:
            return self.row_count

        row = [
            timestamp,
            f"AVERAGE ({active_count} aparate)",
            f"{active_count} active",
            "—",
            "—",
        ]
        for m in averages:
            row.append(f"{m.value:.2f}" if m.value is not None else "")

        with open(self.csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(row)

        self.row_count += 1
        return self.row_count
