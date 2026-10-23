# Monitorizare Multi-Device Eaton `NZMH4-PX1600-TAZ` (PXR25) + `NZM4-XBSM-TAZ-N` (Daisy-Chain USB)

Aplicație modulară în Python pentru conectarea prin **adaptor USB–RS485 (Modbus RTU)** la un lanț (daisy-chain) de disjunctoare **`NZMH4-PX1600-TAZ`** (unitate electronică **PXR25**) și module **`NZM4-XBSM-TAZ-N`**:
- **Scanare automată a ID-urilor de Slave în lanț (`1, 2, 3, ...`)**: detectează automat toate dispozitivele din lanț până la primul ID care nu mai răspunde.
- **Pop-up interactiv de verificare a lanțului / detecție întrerupere hardware**:
  - Afișează numărul total de dispozitive conectate în lanț.
  - Dacă un dispozitiv din lanț se defectează (ex: dispozitivul `#10` dintr-un lanț `1..20`), toate dispozitivele de la `#10` încolo (`#10..#20`) **dispar** imediat (informația nu trece mai departe în lanț) și apare Pop-up-ul cu două opțiuni:
    1. **„✅ OK (Toate device-urile sunt conectate)”** — continuă citirea cu aparatele active.
    2. **„🛑 Problemă! (Oprește citirea pentru reparații hardware)”** — oprește complet citirea pe magistrala RS-485 pentru intervenție hardware în siguranță.
- **Pagină de Average-uri (Medii Sistem)** + **Pagini Individuale pentru fiecare Slave ID separat**.
- **Selectare directă a portului USB (COM) din Dashboard-ul Web** (fără introducere manuală în consolă).
- **Salvare automată în CSV** (`pxr25_log.csv`) pentru fiecare Slave ID + rândul `AVERAGE`.

---

## Structura Proiectului

```text
cool-galileo/
├── main.py                              # Punctul de intrare (Entry-point) — pornește direct Dashboard-ul Web
├── requirements.txt                     # Dependențe Python (pymodbus, pyserial)
├── README.md                            # Documentația proiectului
├── backup_v1_single_device/             # Backup complet al versiunii anterioare (Single-Device)
└── src/
    └── eaton_pxr/
        ├── __init__.py                  # Inițializare pachet
        ├── models.py                    # Modele de date (SerialConnectionConfig, PxrSnapshot, TripEvent)
        ├── registers.py                 # Harta registrelor Modbus PXR25 și tabelele de coduri Eaton
        ├── decoder.py                   # Decodare binară registre 16/32 biți (Fixed-Point, Float, Protecții)
        ├── connection.py                # Gestiune conexiune USB–RS485 și detecție porturi COM
        ├── scanner.py                   # Scanare automată lanț Slave ID (daisy-chain) și calcul Average-uri
        ├── reader.py                    # Citire Modbus: valori în timp real, setări protecție, istoric declanșări
        ├── csv_exporter.py              # Modul dedicat pentru crearea și scrierea fișierului CSV
        ├── cli.py                       # Interfața linie de comandă (CLI)
        └── web/
            ├── __init__.py
            ├── server.py                # Serverul HTTP Multi-Device și firul de achiziție la 2 secunde
            └── templates/
                └── dashboard.html       # Interfața Web (Average-uri, Pagini per ID, Pop-up verificare lanț)
```

---

## Utilizare

Pornește direct Dashboard-ul Web (fără niciun parametru în consolă):
```powershell
.\.venv\Scripts\python.exe main.py
```
Se va deschide automat în browser pagina `http://127.0.0.1:8080`, de unde poți selecta portul USB (COM), poți vedea numărul de dispozitive găsite în lanț, pagina de **Average-uri** și paginile individuale pentru fiecare **Slave ID**.
