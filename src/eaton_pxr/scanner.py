"""
Modul dedicat pentru:
  1. Scanarea automată în lanț (daisy-chain) a ID-urilor de Slave (1, 2, 3, ...).
     Deoarece aparatele sunt legate în lanț, în momentul în care un Slave ID nu mai
     răspunde, niciun aparat de după el nu mai poate primi sau transmite date.
  2. Calculul valorilor medii (Average) pe întregul lanț de disjunctoare active.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from pymodbus.client import ModbusSerialClient

from .connection import modbus_read_holding, open_usb_modbus_client
from .models import MeasuredValue, PxrSnapshot, SerialConnectionConfig
from .registers import PXR25_PARAMETERS, REG_STATUS_FIXED, REG_STATUS_FLOAT


def probe_slave_alive(
    client: ModbusSerialClient,
    slave_id: int,
    use_float: bool = False,
) -> bool:
    """
    Verifică rapid dacă dispozitivul cu `slave_id` răspunde pe magistrala RS-485
    citind perechea de registre de stare (0x1800 sau 0x1200).
    """
    addr = REG_STATUS_FLOAT if use_float else REG_STATUS_FIXED
    try:
        resp = modbus_read_holding(client, addr, 2, slave_id)
        return not resp.isError() and len(getattr(resp, "registers", [])) >= 2
    except Exception:
        return False


def discover_daisy_chain(
    config: SerialConnectionConfig,
    start_id: int = 1,
    max_id: int = 247,
) -> Tuple[List[int], int]:
    """
    Scanează secvențial lanțul de aparate pornind de la `start_id` (1, 2, 3, ...).
    Se oprește imediat la primul Slave ID care nu mai răspunde (deoarece conexiunea
    este în lanț și informația nu trece mai departe).

    Returnează:
      (lista_slave_id_active, primul_id_fara_raspuns)
    """
    active_ids: List[int] = []
    stopped_at_id: int = start_id

    # Folosim un timeout scurt pentru scanare rapidă
    scan_cfg = SerialConnectionConfig(
        port=config.port,
        baudrate=config.baudrate,
        parity=config.parity,
        stopbits=config.stopbits,
        bytesize=config.bytesize,
        slave_id=start_id,
        timeout=0.45,
        use_float=config.use_float,
        word_swap=config.word_swap,
    )

    with open_usb_modbus_client(scan_cfg) as client:
        for candidate_id in range(start_id, max_id + 1):
            if probe_slave_alive(client, candidate_id, use_float=config.use_float):
                active_ids.append(candidate_id)
            else:
                stopped_at_id = candidate_id
                break

    return active_ids, stopped_at_id


def compute_fleet_averages(
    snapshots: Dict[int, PxrSnapshot],
) -> List[MeasuredValue]:
    """
    Calculează media aritmetică (Average) a fiecărui parametru electric
    peste toate dispozitivele active din lanț.
    """
    if not snapshots:
        return [
            MeasuredValue(p.key, p.name, p.category, None, p.unit)
            for p in PXR25_PARAMETERS
        ]

    averages: List[MeasuredValue] = []
    ordered_snaps = [snapshots[k] for k in sorted(snapshots.keys())]

    for idx, param in enumerate(PXR25_PARAMETERS):
        valid_vals: List[float] = []
        for snap in ordered_snaps:
            if idx < len(snap.measurements):
                val = snap.measurements[idx].value
                if val is not None:
                    valid_vals.append(val)

        avg_val: Optional[float] = (
            sum(valid_vals) / len(valid_vals) if valid_vals else None
        )
        averages.append(
            MeasuredValue(
                key=param.key,
                name=f"Medie {param.name}",
                category=param.category,
                value=avg_val,
                unit=param.unit,
            )
        )

    return averages
