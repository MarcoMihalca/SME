"""
Modele de date (Data Transfer Objects) utilizate în întreaga aplicație
pentru monitorizarea multi-device în lanț (daisy-chain RS-485).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SerialConnectionConfig:
    """Configurația conexiunii USB–RS485 (Modbus RTU) către lanțul de unități PXR25."""
    port: str = "COM5"
    baudrate: int = 19200
    parity: str = "E"
    stopbits: int = 1
    bytesize: int = 8
    slave_id: int = 1
    timeout: float = 0.7
    use_float: bool = False
    word_swap: bool = True

    def with_slave(self, slave_id: int) -> "SerialConnectionConfig":
        return SerialConnectionConfig(
            port=self.port,
            baudrate=self.baudrate,
            parity=self.parity,
            stopbits=self.stopbits,
            bytesize=self.bytesize,
            slave_id=slave_id,
            timeout=self.timeout,
            use_float=self.use_float,
            word_swap=self.word_swap,
        )

    @property
    def description(self) -> str:
        return (
            f"USB-RS485 pe {self.port} ({self.baudrate} bps, "
            f"{self.bytesize}{self.parity}{self.stopbits})"
        )


@dataclass(frozen=True)
class PxrParameterDef:
    """Definiția unui registru de măsurare în timp real din harta Modbus PXR25."""
    key: str
    name: str
    category: str
    unit: str
    modbus_float_addr: Optional[int]
    modbus_fp_addr: int
    fp_scale: float
    fp_signed: bool


@dataclass(frozen=True)
class MeasuredValue:
    """Valoarea citită și decodată a unui parametru electric."""
    key: str
    name: str
    category: str
    value: Optional[float]
    unit: str


@dataclass(frozen=True)
class ProtectionSetting:
    """O setare de protecție citită din Tabelul 27 (Protection Group) al PXR25."""
    name: str
    register: str
    formatted: str
    raw_hex: str


@dataclass(frozen=True)
class TripEvent:
    """Un eveniment de declanșare sau alarmă din istoricul unității PXR25."""
    event_id: str
    event_type: str
    timestamp: str
    cause: str
    currents: str


@dataclass
class PxrSnapshot:
    """Snapshot complet cu toate datele preluate la o citire dintr-un disjunctor (Slave ID)."""
    slave_id: int
    timestamp: str
    connection_desc: str
    status_info: Dict[str, str]
    measurements: List[MeasuredValue] = field(default_factory=list)
    protection_settings: List[ProtectionSetting] = field(default_factory=list)
    event_history: List[TripEvent] = field(default_factory=list)
