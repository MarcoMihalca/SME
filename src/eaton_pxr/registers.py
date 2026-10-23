"""
Harta registrelor Modbus RTU și tabelele de coduri pentru:
  - Disjunctor Eaton NZMH4-PX1600-TAZ (unitate electronică PXR25)
  - Modul stare/comunicație Eaton NZM4-XBSM-TAZ-N

Referință oficială: Manualul Eaton MN012005EN (Capitolul 9 - Modbus RTU).
"""

from __future__ import annotations

from typing import Dict, List, Tuple
from .models import PxrParameterDef

# Coduri stare principală (High Byte din registrul 0x1800 / 0x1200)
PRIMARY_STATUS_CODES: Dict[int, str] = {
    0x00: "Necunoscut / Indisponibil (Unknown)",
    0x01: "Deschis (Open)",
    0x02: "Închis (Closed)",
    0x03: "Declanșat / Tripat (Tripped)",
    0x04: "Alarmă activă (Alarm)",
}

# Coduri stare secundară (Low Byte din registrul 0x1800 / 0x1200)
SECONDARY_STATUS_CODES: Dict[int, str] = {
    0x00: "Normal / Fără stare secundară",
    0x01: "Nealimentat / Eroare internă",
    0x02: "Pre-alarmă / Pickup activ",
    0x03: "Mod Test (Test Mode)",
    0x07: "Alimentat / Normal (Powered-Up)",
    0x08: "Alarmă activă (Active Alarm)",
}

# Coduri pentru cauza stării / motivul declanșării (Registrul 0x1801 / 0x1201)
CAUSE_OF_STATUS_CODES: Dict[int, str] = {
    0x0000: "Normal (Fără eveniment de declanșare/alarmă)",
    0x0001: "Suprasarcină / Long Delay (Ir)",
    0x0002: "Scurtcircuit temporizat / Short Delay (Isd)",
    0x0003: "Scurtcircuit instantaneu / Instantaneous (Ii)",
    0x0004: "Defect pământare / Ground Fault (Ig)",
    0x0005: "Temperatură ridicată (Overtemperature)",
    0x0006: "Declanșare ARMS / Maintenance Mode",
    0x0007: "Declanșare prin comunicație / Comandă externă",
    0x0008: "Dezechilibru de fază / Pierdere fază",
    0x0009: "Tensiune în afara limitelor (Sub/Supratensiune)",
}

# Adresele registrelor de stare (pereche de 2 registre: Status + Cause)
REG_STATUS_FLOAT = 0x1200       # Reg 404609..404610
REG_STATUS_FIXED = 0x1800       # Reg 406145..406146
REG_PRODUCT_ID = 0x186E         # Reg 406255..406256

# Adresele pentru Tabelul 27 (Setting Group 1: Protection Group)
REG_PASSWORD = 0x0BB7           # Reg 403000
REG_GROUP_SELECT = 0x0BB8       # Reg 403001
PROTECTION_BLOCK_COUNT = 24     # 0x0BB8..0x0BCF

# Definițiile registrelor din Tabelul 27 (Setări de protecție PXR25)
PROTECTION_REGISTER_SPECS: List[Tuple[int, str, str, str]] = [
    (0x0BB9, "403002 (0x0BB9)", "Curent Nominal (In)", "In"),
    (0x0BBA, "403003 (0x0BBA)", "Mărime Cadru (Frame Size)", "frame"),
    (0x0BBC, "403005 (0x0BBC)", "Module Instalate (Modbus/CAM/ZSI/LCD)", "modules"),
    (0x0BBE, "403007 (0x0BBE)", "Prag Suprasarcină Long-Delay (Ir)", "Ir"),
    (0x0BBF, "403008 (0x0BBF)", "Curbă Suprasarcină (I²t / Flat)", "curve"),
    (0x0BC0, "403009 (0x0BC0)", "Memorie Termică Suprasarcină", "on_off"),
    (0x0BC1, "403010 (0x0BC1)", "Temporizare Suprasarcină (tr)", "tr"),
    (0x0BC2, "403011 (0x0BC2)", "Protecție Dezechilibru Curent", "unbal_mode"),
    (0x0BC4, "403013 (0x0BC4)", "Prag Scurtcircuit Temporizat (Isd)", "Isd"),
    (0x0BC5, "403014 (0x0BC5)", "Temporizare Scurtcircuit (tsd)", "tsd"),
    (0x0BC6, "403015 (0x0BC6)", "Prag Scurtcircuit Instantaneu (Ii)", "Ii"),
    (0x0BC7, "403016 (0x0BC7)", "Mod Protecție Defect Pământ (Ig)", "ig_mode"),
    (0x0BC9, "403018 (0x0BC9)", "Curbă Defect Pământ (I²t / Flat)", "curve"),
    (0x0BCA, "403019 (0x0BCA)", "Prag Defect Pământ (Ig)", "Ig"),
    (0x0BCB, "403020 (0x0BCB)", "Temporizare Defect Pământ (tg)", "tg"),
    (0x0BCC, "403021 (0x0BCC)", "Memorie Termică Defect Pământ", "on_off"),
    (0x0BCD, "403022 (0x0BCD)", "Protecție Conductor Nul (IN %)", "pct"),
]

# Registrele de configurare a portului Modbus RTU (404000..404003)
MODBUS_PORT_CONFIG_SPECS: List[Tuple[int, str, str, Dict[int, str]]] = [
    (0x0F9F, "404000 (0x0F9F)", "Adresă Modbus Slave (PXR25)", {1: "Slave ID = 1", 2: "Slave ID = 2"}),
    (0x0FA0, "404001 (0x0FA0)", "Baud Rate Modbus RTU", {0: "9600 bps", 1: "19200 bps", 2: "38400 bps", 3: "57600 bps"}),
    (0x0FA1, "404002 (0x0FA1)", "Paritate Modbus RTU", {0: "None (N)", 1: "Odd (O)", 2: "Even (E)"}),
    (0x0FA2, "404003 (0x0FA2)", "Stop Bits Modbus RTU", {0: "1 stop bit", 1: "2 stop bits"}),
]

# Lista completă a parametrilor măsurați în timp real (Tabelul Real-Time Data PXR25)
PXR25_PARAMETERS: List[PxrParameterDef] = [
    # --- 1. Curenți (A) ---
    PxrParameterDef("I_A", "Curent Faza L1 (IA)", "currents", "A", 0x1202, 0x1802, 10.0, True),
    PxrParameterDef("I_B", "Curent Faza L2 (IB)", "currents", "A", 0x1204, 0x1804, 10.0, True),
    PxrParameterDef("I_C", "Curent Faza L3 (IC)", "currents", "A", 0x1206, 0x1806, 10.0, True),
    PxrParameterDef("I_G", "Curent Defect Pământ (IG)", "currents", "A", 0x1208, 0x1808, 10.0, True),
    PxrParameterDef("I_N", "Curent Nul (IN)", "currents", "A", 0x120A, 0x180A, 10.0, True),
    # --- 2. Tensiuni Linie-Linie și Fază-Nul (V) ---
    PxrParameterDef("V_AB", "Tensiune L1-L2 (VAB)", "voltages", "V", 0x120E, 0x180E, 10.0, False),
    PxrParameterDef("V_BC", "Tensiune L2-L3 (VBC)", "voltages", "V", 0x1210, 0x1810, 10.0, False),
    PxrParameterDef("V_CA", "Tensiune L3-L1 (VCA)", "voltages", "V", 0x1212, 0x1812, 10.0, False),
    PxrParameterDef("V_AN", "Tensiune L1-N (VAN)", "voltages", "V", 0x1216, 0x1816, 10.0, False),
    PxrParameterDef("V_BN", "Tensiune L2-N (VBN)", "voltages", "V", 0x1218, 0x1818, 10.0, False),
    PxrParameterDef("V_CN", "Tensiune L3-N (VCN)", "voltages", "V", 0x121A, 0x181A, 10.0, False),
    # --- 3. Puteri, Factor de Putere și Frecvență ---
    PxrParameterDef("P_TOT", "Putere Activă Totală (P)", "powers", "W", 0x122A, 0x182A, 1.0, True),
    PxrParameterDef("Q_TOT", "Putere Reactivă Totală (Q)", "powers", "VAR", 0x122C, 0x182C, 1.0, True),
    PxrParameterDef("S_TOT", "Putere Aparentă Totală (S)", "powers", "VA", 0x122E, 0x182E, 1.0, False),
    PxrParameterDef("PF_TOT", "Factor de Putere (cos φ)", "powers", "", 0x1232, 0x1832, 100.0, True),
    PxrParameterDef("FREQ", "Frecvență Rețea", "powers", "Hz", 0x1234, 0x1834, 10.0, False),
    # --- 4. Contoare de Energie (Clasa 1) ---
    PxrParameterDef("E_FWD", "Energie Activă Directă (Forward)", "energy", "kWh", None, 0x1872, 1.0, False),
    PxrParameterDef("E_REV", "Energie Activă Inversă (Reverse)", "energy", "kWh", None, 0x1874, 1.0, False),
    PxrParameterDef("E_TOT", "Energie Activă Totală", "energy", "kWh", None, 0x1876, 1.0, False),
    PxrParameterDef("E_APP", "Energie Aparentă Totală", "energy", "kVAh", None, 0x187E, 1.0, False),
]
