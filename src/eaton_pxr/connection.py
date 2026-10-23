"""
Modul pentru gestionarea conexiunii USB–RS485 (Modbus RTU),
detecția automată a porturilor COM și selectarea parametrilor de conectare.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, List, Tuple
from pymodbus.client import ModbusSerialClient
from serial.tools import list_ports

from .models import SerialConnectionConfig


def normalize_com_port(port_str: str) -> str:
    """
    Normalizează intrarea utilizatorului pentru portul COM:
    Dacă utilizatorul tastează '5', returnează 'COM5'.
    """
    cleaned = port_str.strip()
    if cleaned.isdigit():
        return f"COM{cleaned}"
    return cleaned.upper()


def get_available_serial_ports() -> List[Tuple[str, str]]:
    """Returnează o listă de tupluri (nume_port, descriere) pentru porturile COM active."""
    return [(p.device, p.description) for p in list_ports.comports()]


def detect_preferred_usb_port(default_port: str = "COM5") -> str:
    """
    Caută automat un adaptor USB–RS485 (ex: CH340, FTDI, CP210x, USB-SERIAL)
    printre porturile COM active. Dacă nu găsește, returnează `default_port`.
    """
    ports = get_available_serial_ports()
    for dev, desc in ports:
        upper_desc = desc.upper()
        if any(k in upper_desc for k in ("USB", "CH340", "FTDI", "CP210", "RS485", "SERIAL")):
            if "BLUETOOTH" not in upper_desc:
                return dev
    return default_port


def print_serial_ports() -> None:
    """Afișează în consolă porturile COM detectate pe sistem."""
    ports = get_available_serial_ports()
    if not ports:
        print("Nu s-a detectat niciun port serial (COM) pe acest sistem.")
        return

    print("\n=== Porturi USB / Seriale (COM) Disponibile ===")
    for device, description in ports:
        marker = " <-- [Adaptor USB detectat]" if "USB" in description.upper() else ""
        print(f"  - {device}: {description}{marker}")
    print()


def prompt_usb_connection_config(
    default_config: SerialConnectionConfig,
) -> Tuple[SerialConnectionConfig, str]:
    """
    Meniu interactiv pentru selectarea portului USB–RS485, Slave ID și modului de vizualizare.
    Returnează (SerialConnectionConfig, mod_vizualizare: 'web' | 'watch' | 'once').
    """
    print("=" * 74)
    print(" CONECTARE USB–RS485 LA EATON NZMH4-PX1600-TAZ + NZM4-XBSM-TAZ-N")
    print("=" * 74)
    print_serial_ports()

    suggested_port = detect_preferred_usb_port(default_config.port)
    port_in = input(f"Port COM adaptor USB [{suggested_port}]: ").strip()
    chosen_port = normalize_com_port(port_in) if port_in else suggested_port

    slave_in = input(f"Modbus Slave ID PXR25 [{default_config.slave_id}]: ").strip()
    chosen_slave = int(slave_in) if slave_in.isdigit() else default_config.slave_id

    print("\nCum dorești să rulezi monitorizarea?")
    print("  [1] Dashboard Web în timp real (actualizare la 2s + CSV + Protecții & Istoric)")
    print("  [2] În consolă în timp real (actualizare la 2s + CSV + Protecții & Istoric)")
    print("  [3] O singură citire completă în consolă (+ CSV, Protecții & Istoric)")
    view_choice = input("Selectează opțiunea [1-3, implicit 1]: ").strip() or "1"

    view_mode = "web"
    if view_choice == "2":
        view_mode = "watch"
    elif view_choice == "3":
        view_mode = "once"

    config = SerialConnectionConfig(
        port=chosen_port,
        baudrate=default_config.baudrate,
        parity=default_config.parity,
        stopbits=default_config.stopbits,
        bytesize=default_config.bytesize,
        slave_id=chosen_slave,
        timeout=default_config.timeout,
        use_float=default_config.use_float,
        word_swap=default_config.word_swap,
    )
    return config, view_mode


@contextmanager
def open_usb_modbus_client(
    config: SerialConnectionConfig,
) -> Generator[ModbusSerialClient, None, None]:
    """Context manager care deschide și închide în siguranță conexiunea USB Modbus RTU."""
    client = ModbusSerialClient(
        port=config.port,
        baudrate=config.baudrate,
        parity=config.parity,
        stopbits=config.stopbits,
        bytesize=config.bytesize,
        timeout=config.timeout,
    )
    if not client.connect():
        raise RuntimeError(
            f"Nu s-a putut deschide portul {config.port} "
            f"({config.baudrate} bps, {config.bytesize}{config.parity}{config.stopbits}). "
            "Verifică dacă adaptorul USB–RS485 este conectat și nu este blocat de alt program."
        )
    try:
        yield client
    finally:
        client.close()


def modbus_read_holding(
    client: ModbusSerialClient, address: int, count: int, slave_id: int
):
    """Apel compatibil între versiunile pymodbus 3.x (`device_id=` / `slave=`)."""
    for kw in ("device_id", "slave", "unit"):
        try:
            return client.read_holding_registers(
                address=address, count=count, **{kw: slave_id}
            )
        except TypeError:
            continue
    return client.read_holding_registers(address, count)


def modbus_write_single(
    client: ModbusSerialClient, address: int, value: int, slave_id: int
):
    """Scrie un singur registru Holding (Function Code 06)."""
    for kw in ("device_id", "slave", "unit"):
        try:
            return client.write_register(address=address, value=value, **{kw: slave_id})
        except TypeError:
            continue
    return client.write_register(address, value)


def modbus_write_multiple(
    client: ModbusSerialClient, address: int, values: List[int], slave_id: int
):
    """Scrie mai multe registre Holding consecutive (Function Code 16)."""
    for kw in ("device_id", "slave", "unit"):
        try:
            return client.write_registers(
                address=address, values=values, **{kw: slave_id}
            )
        except TypeError:
            continue
    return client.write_registers(address, values)
