"""
Funcții de decodare binară a registrelor Modbus (16 biți / 32 biți Fixed-Point / IEEE 754 Float).
"""

from __future__ import annotations

from datetime import datetime
import struct
from typing import Dict, List, Optional, Tuple
from .registers import (
    CAUSE_OF_STATUS_CODES,
    PRIMARY_STATUS_CODES,
    SECONDARY_STATUS_CODES,
)


def decode_status_registers(reg_status: int, reg_cause: int) -> Dict[str, str]:
    """
    Decodează perechea de registre Status (0x1800 / 0x1200) și Cause (0x1801 / 0x1201):
      - High byte din primul registru: Starea principală a disjunctorului (Open/Closed/Tripped)
      - Low byte din primul registru: Starea secundară a unității PXR25 (Powered-Up/Test/Alarm)
      - Al doilea registru: Cauza stării sau a ultimei declanșări (Ir, Isd, Ii, Ig, ARMS)
    """
    primary_code = (reg_status >> 8) & 0xFF
    secondary_code = reg_status & 0xFF

    primary_str = PRIMARY_STATUS_CODES.get(
        primary_code, f"Cod necunoscut (0x{primary_code:02X})"
    )
    secondary_str = SECONDARY_STATUS_CODES.get(
        secondary_code, f"Cod necunoscut (0x{secondary_code:02X})"
    )
    cause_str = CAUSE_OF_STATUS_CODES.get(
        reg_cause, f"Cod eveniment 0x{reg_cause:04X}"
    )

    return {
        "Stare Principală Disjunctor": f"{primary_str} [0x{primary_code:02X}]",
        "Stare Secundară Unitate PXR": f"{secondary_str} [0x{secondary_code:02X}]",
        "Cauză Stare / Eveniment": f"{cause_str} [0x{reg_cause:04X}]",
    }


def decode_32bit_float(reg_0: int, reg_1: int, word_swap: bool = True) -> float:
    """Decodează 2 registre Modbus de 16 biți într-un număr IEEE 754 float pe 32 biți."""
    raw = (
        struct.pack(">HH", reg_1 & 0xFFFF, reg_0 & 0xFFFF)
        if word_swap
        else struct.pack(">HH", reg_0 & 0xFFFF, reg_1 & 0xFFFF)
    )
    return struct.unpack(">f", raw)[0]


def decode_32bit_int(
    reg_0: int, reg_1: int, signed: bool = True, word_swap: bool = True
) -> int:
    """Decodează 2 registre Modbus de 16 biți într-un întreg pe 32 biți (Fixed-Point)."""
    raw = (
        struct.pack(">HH", reg_1 & 0xFFFF, reg_0 & 0xFFFF)
        if word_swap
        else struct.pack(">HH", reg_0 & 0xFFFF, reg_1 & 0xFFFF)
    )
    return struct.unpack(">i" if signed else ">I", raw)[0]


def decode_protection_value(
    kind: str, raw: int, in_amps: float, ir_amps: float
) -> Tuple[str, float, float]:
    """
    Formatează o valoare brută din Tabelul 27 (Protection Group) în unități fizice (A, s, ms, %).
    Returnează (valoare_formatată, in_amps_actualizat, ir_amps_actualizat).
    """
    if kind == "In":
        if 100 <= raw <= 4000:
            in_amps = float(raw)
        return f"{in_amps:.0f} A (cod={raw})", in_amps, ir_amps

    if kind == "Ir":
        if 40 <= raw <= 100:
            mult = raw / 100.0
            ir_amps = mult * in_amps
            return f"{mult:.2f} × In ({ir_amps:.0f} A)", in_amps, ir_amps
        if 4 <= raw <= 10:
            mult = raw / 10.0
            ir_amps = mult * in_amps
            return f"{mult:.1f} × In ({ir_amps:.0f} A)", in_amps, ir_amps
        if raw > 100:
            ir_amps = float(raw)
            return f"{ir_amps:.0f} A ({ir_amps / in_amps:.2f} × In)", in_amps, ir_amps
        return f"Treaptă/Valoare = {raw}", in_amps, ir_amps

    if kind == "tr":
        val_s = raw / 10.0 if raw > 30 else float(raw)
        return f"{val_s:.1f} s", in_amps, ir_amps

    if kind == "Isd":
        mult = raw / 10.0 if raw >= 15 else float(raw)
        return f"{mult:.1f} × Ir ({mult * ir_amps:.0f} A)", in_amps, ir_amps

    if kind == "tsd":
        return f"{raw} ms", in_amps, ir_amps

    if kind == "Ii":
        mult = raw / 10.0 if raw >= 20 else float(raw)
        return f"{mult:.1f} × In ({mult * in_amps:.0f} A)", in_amps, ir_amps

    if kind == "Ig":
        mult = raw / 100.0 if raw >= 20 else raw / 10.0
        return f"{mult:.2f} × In ({mult * in_amps:.0f} A)", in_amps, ir_amps

    if kind == "tg":
        return f"{raw} ms", in_amps, ir_amps

    if kind == "curve":
        fmt = "I²t (Inversă)" if raw == 1 else ("Flat (Constantă)" if raw == 0 else f"Cod {raw}")
        return fmt, in_amps, ir_amps

    if kind == "on_off":
        fmt = "Activă (ON)" if raw == 1 else ("Oprită (OFF)" if raw == 0 else f"Cod {raw}")
        return fmt, in_amps, ir_amps

    if kind in ("unbal_mode", "ig_mode"):
        modes = {0: "Declanșare (Trip)", 1: "Alarmă (Alarm)", 2: "Oprit (OFF)"}
        return modes.get(raw, f"Cod {raw}"), in_amps, ir_amps

    if kind == "pct":
        return f"{raw} %", in_amps, ir_amps

    return str(raw), in_amps, ir_amps


def encode_rtc_registers(dt: Optional[datetime] = None) -> List[int]:
    """
    Codifică data și ora într-un bloc de 8 registre Modbus RTC (402921..402928 / 0x0B68..0x0B6F)
    conform manualului Eaton MN012005EN:
      [Month (1-12), Day (1-31), Year (2000-2099), DayOfWeek (1=Dum..7=Sâm),
       Hour (0-23), Minute (0-59), Second (0-59), 1/100th Sec (0-99)]
    """
    target = dt or datetime.now()
    # Python weekday(): Monday=0..Sunday=6 -> Eaton PXR: Sunday=1, Monday=2, ..., Saturday=7
    day_of_week = ((target.weekday() + 1) % 7) + 1
    hundredths = min(99, max(0, int(target.microsecond // 10000)))
    return [
        target.month,
        target.day,
        target.year,
        day_of_week,
        target.hour,
        target.minute,
        target.second,
        hundredths,
    ]


def decode_rtc_registers(regs: List[int]) -> Optional[str]:
    """Decodează cele 7-8 registre Modbus RTC (0x0B68..0x0B6F) în format 'YYYY-MM-DD HH:MM:SS'."""
    if not regs or len(regs) < 7:
        return None
    month = int(regs[0])
    day = int(regs[1])
    year = int(regs[2])
    hour = int(regs[4])
    minute = int(regs[5])
    second = int(regs[6])

    if not (1 <= month <= 12 and 1 <= day <= 31 and 2000 <= year <= 2099):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
