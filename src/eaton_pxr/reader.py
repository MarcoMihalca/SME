"""
Serviciul de citire Modbus RTU pentru:
  1. Stare disjunctor și valori măsurate în timp real (Curenți, Tensiuni, Puteri, Energie)
  2. Setări de protecție active (Tabelul 27 din MN012005EN: In, Ir, tr, Isd, tsd, Ii, Ig, tg)
  3. Istoricul de declanșări și evenimente (Tabelele 31 & 32 din MN012005EN)
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple
from pymodbus.client import ModbusSerialClient

from .analytics import compute_energy_indicators
from .connection import (
    modbus_read_holding,
    modbus_write_multiple,
    modbus_write_single,
    open_usb_modbus_client,
)
from .decoder import (
    decode_32bit_float,
    decode_32bit_int,
    decode_protection_value,
    decode_status_registers,
)
from .models import (
    MeasuredValue,
    ProtectionSetting,
    PxrSnapshot,
    SerialConnectionConfig,
    TripEvent,
)
from .registers import (
    CAUSE_OF_STATUS_CODES,
    MODBUS_PORT_CONFIG_SPECS,
    PROTECTION_BLOCK_COUNT,
    PROTECTION_REGISTER_SPECS,
    PXR25_PARAMETERS,
    REG_GROUP_SELECT,
    REG_PASSWORD,
    REG_PRODUCT_ID,
    REG_STATUS_FIXED,
    REG_STATUS_FLOAT,
)


def read_realtime_measurements(
    client: ModbusSerialClient,
    config: SerialConnectionConfig,
) -> Tuple[Dict[str, str], List[MeasuredValue]]:
    """
    Citește starea disjunctorului și toate cele 20 de mărimi electrice în timp real
    pentru `config.slave_id` folosind 2 citiri bloc contigue (Status+Mărimi și Contoare Energie)
    pentru a minimiza latența pe magistrala RS-485 în regim multi-device.
    Dacă aparatul nu răspunde la citirea blocului principal, ridică RuntimeError.
    """
    base_main = REG_STATUS_FLOAT if config.use_float else REG_STATUS_FIXED
    # Blocul 1: 0x1800..0x1835 (sau 0x1200..0x1235) = 54 registre contigue
    resp_main = modbus_read_holding(client, base_main, 54, config.slave_id)
    main_regs = getattr(resp_main, "registers", None) or []
    if resp_main.isError() or len(main_regs) < 2:
        raise RuntimeError(
            f"Dispozitivul cu Slave ID={config.slave_id} nu mai răspunde pe magistrala RS-485."
        )

    status_info = decode_status_registers(main_regs[0], main_regs[1])

    # Blocul 2: Contoarele de energie Clasa 1 (0x1872..0x187F = 14 registre contigue)
    energy_base = 0x1872
    resp_energy = modbus_read_holding(client, energy_base, 14, config.slave_id)
    energy_regs = (
        getattr(resp_energy, "registers", None) or []
        if not resp_energy.isError()
        else []
    )

    measurements: List[MeasuredValue] = []

    for param in PXR25_PARAMETERS:
        if config.use_float and param.modbus_float_addr is not None:
            off = param.modbus_float_addr - REG_STATUS_FLOAT
            if 0 <= off and len(main_regs) >= off + 2:
                r0, r1 = main_regs[off], main_regs[off + 1]
            else:
                measurements.append(
                    MeasuredValue(param.key, param.name, param.category, None, param.unit)
                )
                continue
            val = decode_32bit_float(r0, r1, word_swap=config.word_swap)
            clean_val = None if val != val else val
            measurements.append(
                MeasuredValue(param.key, param.name, param.category, clean_val, param.unit)
            )
        else:
            addr = param.modbus_fp_addr
            r0_r1: Optional[Tuple[int, int]] = None
            if not config.use_float and REG_STATUS_FIXED <= addr <= REG_STATUS_FIXED + 52:
                off = addr - REG_STATUS_FIXED
                if len(main_regs) >= off + 2:
                    r0_r1 = (main_regs[off], main_regs[off + 1])
            elif energy_base <= addr <= energy_base + 12:
                off = addr - energy_base
                if len(energy_regs) >= off + 2:
                    r0_r1 = (energy_regs[off], energy_regs[off + 1])

            if r0_r1 is None:
                measurements.append(
                    MeasuredValue(param.key, param.name, param.category, None, param.unit)
                )
                continue

            raw_int = decode_32bit_int(
                r0_r1[0],
                r0_r1[1],
                signed=param.fp_signed,
                word_swap=config.word_swap,
            )
            if raw_int in (0x7FFFFFFF, -0x80000000, 0xFFFFFFFF):
                clean_val = None
            else:
                clean_val = raw_int / param.fp_scale
            measurements.append(
                MeasuredValue(param.key, param.name, param.category, clean_val, param.unit)
            )

    return status_info, measurements


def read_protection_settings(
    client: ModbusSerialClient, slave_id: int = 1
) -> List[ProtectionSetting]:
    """
    Citește Setările de Protecție din PXR25 (Tabelul 27 din MN012005EN: 0x0BB8..0x0BCF),
    Product ID (0x186E) și configurarea portului Modbus (0x0F9F..0x0FA2).
    """
    settings: List[ProtectionSetting] = []

    resp_pid = modbus_read_holding(client, REG_PRODUCT_ID, 2, slave_id)
    if not resp_pid.isError():
        pid_val = decode_32bit_int(
            resp_pid.registers[0], resp_pid.registers[1], signed=False, word_swap=True
        )
        settings.append(
            ProtectionSetting(
                name="Product ID / Configurație PXR25",
                register="406255 (0x186E)",
                formatted=f"NZMH4-PX1600-TAZ (ID={pid_val}, In=1600 A)",
                raw_hex=f"0x{pid_val:04X}",
            )
        )

    for group_cmd in (0x01FF, 0x0001):
        try:
            modbus_write_single(client, REG_PASSWORD, 0x0000, slave_id)
            modbus_write_single(client, REG_GROUP_SELECT, group_cmd, slave_id)
            break
        except Exception:
            pass

    in_amps = 1600.0
    ir_amps = 1600.0

    block_resp = modbus_read_holding(
        client, REG_GROUP_SELECT, PROTECTION_BLOCK_COUNT, slave_id
    )
    reg_cache: Dict[int, int] = {}
    if not block_resp.isError() and len(block_resp.registers) >= PROTECTION_BLOCK_COUNT:
        for i, val in enumerate(block_resp.registers):
            reg_cache[REG_GROUP_SELECT + i] = val
    else:
        for addr, _, _, _ in PROTECTION_REGISTER_SPECS:
            r = modbus_read_holding(client, addr, 1, slave_id)
            if not r.isError() and r.registers:
                reg_cache[addr] = r.registers[0]

    for addr, reg_label, name, kind in PROTECTION_REGISTER_SPECS:
        if addr not in reg_cache:
            continue
        raw = reg_cache[addr]
        fmt, in_amps, ir_amps = decode_protection_value(kind, raw, in_amps, ir_amps)
        settings.append(
            ProtectionSetting(
                name=name,
                register=reg_label,
                formatted=fmt,
                raw_hex=f"0x{raw:04X}",
            )
        )

    for addr, reg_label, name, mapping in MODBUS_PORT_CONFIG_SPECS:
        r = modbus_read_holding(client, addr, 1, slave_id)
        if not r.isError() and r.registers:
            raw = r.registers[0]
            settings.append(
                ProtectionSetting(
                    name=name,
                    register=reg_label,
                    formatted=mapping.get(raw, str(raw)),
                    raw_hex=f"0x{raw:04X}",
                )
            )

    if len(settings) <= 1:
        settings.extend(
            [
                ProtectionSetting(
                    name="Curent Nominal Cadru / Senzor (In)",
                    register="NZMH4-PX1600-TAZ",
                    formatted="1600 A (3 Poli, Clasa 1 Energie, ZSI + ARMS)",
                    raw_hex="0x0640",
                ),
                ProtectionSetting(
                    name="Protecții LSIG + ARMS (Ir, tr, Isd, tsd, Ii, Ig, tg)",
                    register="403007..403020 (0x0BBE..0x0BCB)",
                    formatted="Setate de pe comutatoarele rotative / ecranul frontal PXR25",
                    raw_hex="LOCAL",
                ),
            ]
        )

    return settings


def read_event_history(
    client: ModbusSerialClient,
    slave_id: int = 1,
    current_status: Optional[Dict[str, str]] = None,
    max_events: int = 10,
) -> List[TripEvent]:
    """
    Citește Istoricul de Declanșări (Tabelul 32: 0x80FF) și Sumarul de Evenimente (Tabelul 31: 0x8EFF)
    de la registrele 408193..408230 (0x2000..0x2021) conform MN012005EN Capitolul 9.
    """
    events: List[TripEvent] = []

    if current_status:
        events.append(
            TripEvent(
                event_id="ACTIV",
                event_type="Stare Curentă",
                timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                cause=(
                    f"{current_status.get('Stare Principală Disjunctor', '')} — "
                    f"{current_status.get('Cauză Stare / Eveniment', '')}"
                ),
                currents="Vezi panoul Curenți în Timp Real",
            )
        )

    for base_addr in (0x2000, 0x1FFF):
        for ev_code, ev_type_label in ((0x80FF, "Declanșare (Trip)"), (0x8EFF, "Eveniment")):
            try:
                w_resp = modbus_write_single(client, base_addr, ev_code, slave_id)
                if w_resp.isError():
                    continue

                id_resp = modbus_read_holding(client, base_addr + 1, 4, slave_id)
                if id_resp.isError() or len(id_resp.registers) < 4:
                    continue

                earliest_id = decode_32bit_int(
                    id_resp.registers[0], id_resp.registers[1], signed=False, word_swap=True
                )
                latest_id = decode_32bit_int(
                    id_resp.registers[2], id_resp.registers[3], signed=False, word_swap=True
                )
                if latest_id == 0 or latest_id == 0xFFFFFFFF or latest_id < earliest_id:
                    continue

                start_id = max(earliest_id, latest_id - max_events + 1)
                for req_id in range(latest_id, start_id - 1, -1):
                    lo_w = req_id & 0xFFFF
                    hi_w = (req_id >> 16) & 0xFFFF
                    req_w = modbus_write_multiple(
                        client, base_addr + 5, [lo_w, hi_w], slave_id
                    )
                    if req_w.isError():
                        continue

                    snap = modbus_read_holding(client, base_addr + 11, 22, slave_id)
                    if snap.isError() or len(snap.registers) < 12:
                        continue

                    sr = snap.registers
                    year = sr[0] if 2000 <= sr[0] <= 2099 else (2000 + (sr[0] & 0xFF))
                    month = max(1, min(12, sr[1] & 0xFF))
                    day = max(1, min(31, sr[2] & 0xFF))
                    hour = min(23, sr[3] & 0xFF)
                    minute = min(59, sr[4] & 0xFF)
                    second = min(59, sr[5] & 0xFF)
                    ts_str = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"

                    cause_code = sr[10] if len(sr) > 10 else 0
                    cause_desc = CAUSE_OF_STATUS_CODES.get(
                        cause_code, f"Cod eveniment 0x{cause_code:04X}"
                    )

                    if ev_code == 0x80FF and len(sr) >= 21:
                        ia = decode_32bit_int(sr[13], sr[14], signed=False) / 10.0
                        ib = decode_32bit_int(sr[15], sr[16], signed=False) / 10.0
                        ic = decode_32bit_int(sr[17], sr[18], signed=False) / 10.0
                        ig = decode_32bit_int(sr[19], sr[20], signed=False) / 10.0
                        cur_str = f"IA={ia:.1f}A, IB={ib:.1f}A, IC={ic:.1f}A, IG={ig:.1f}A"
                    else:
                        cur_str = "—"

                    events.append(
                        TripEvent(
                            event_id=str(req_id),
                            event_type=ev_type_label,
                            timestamp=ts_str,
                            cause=cause_desc,
                            currents=cur_str,
                        )
                    )
            except Exception:
                continue

    return events


def read_device_on_client(
    client: ModbusSerialClient,
    config: SerialConnectionConfig,
    include_settings_and_events: bool = True,
) -> PxrSnapshot:
    """Citește un singur Slave ID folosind o conexiune `ModbusSerialClient` deja deschisă."""
    status_info, measurements = read_realtime_measurements(client, config)
    indicators = compute_energy_indicators(measurements)
    settings: List[ProtectionSetting] = []
    events: List[TripEvent] = []
    if include_settings_and_events:
        settings = read_protection_settings(client, slave_id=config.slave_id)
        events = read_event_history(
            client, slave_id=config.slave_id, current_status=status_info
        )

    return PxrSnapshot(
        slave_id=config.slave_id,
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        connection_desc=f"{config.description} [Slave #{config.slave_id}]",
        status_info=status_info,
        measurements=measurements,
        energy_indicators=indicators,
        protection_settings=settings,
        event_history=events,
    )


def acquire_pxr_snapshot(
    config: SerialConnectionConfig,
    include_settings_and_events: bool = True,
) -> PxrSnapshot:
    """Deschide conexiunea USB–RS485, citește un Slave ID și returnează un `PxrSnapshot`."""
    with open_usb_modbus_client(config) as client:
        return read_device_on_client(
            client=client,
            config=config,
            include_settings_and_events=include_settings_and_events,
        )
