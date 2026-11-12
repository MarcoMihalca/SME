# Detalii Proiect — Sistem de Monitorizare Energetică Multi-Device Eaton PXR25 (Daisy-Chain RS-485)

## 1. Prezentare Generală
Acest proiect implementează o platformă software modulară în **Python** pentru monitorizarea în timp real, analiza calității energiei electrice, stocarea scalabilă în **PostgreSQL + TimescaleDB (Container Docker `SME`)** și diagnoza unui lanț (**daisy-chain RS-485 / Modbus RTU**) de disjunctoare automate **Eaton `NZMH4-PX1600-TAZ`** (echipate cu unitate electronică de protecție **PXR25**) și module **Eaton `NZM4-XBSM-TAZ-N`**.

---

## 2. Funcționalități Implementate în Versiunea Curentă

### 2.1. Scanare Automată în Lanț (Daisy-Chain Discovery) & Detecție Întreruperi
- **Auto-Discovery (`1, 2, 3, ...`)**: La pornire sau la schimbarea portului USB (`COM`), aplicația interoghează secvențial adresele Modbus Slave pornind de la ID `#1`.
- **Comportament fizic de lanț (Daisy-Chain)**: Dacă un aparat din lanț (ex: Slave ID `#10` dintr-un lanț `#1..#20`) își pierde alimentarea sau conexiunea RS-485 se întrerupe în dreptul său, toate aparatele din aval (`#10..#20`) dispar instantaneu din afișare, iar operatorul primește un **Pop-up interactiv de decizie**:
  1. **✅ OK (Continuă citirea)** — recalculează mediile pe aparatele rămase active (`#1..#9`).
  2. **🛑 Problemă! (Oprește citirea pentru reparații hardware)** — suspendă complet traficul pe magistrala RS-485 pentru intervenție fizică în siguranță.

### 2.2. Grafice Live Modulare cu Persistență a Configurației
- **6 Grafice în Timp Real** (randate nativ pe `HTML5 Canvas` la rezoluție High-DPI, fără dependență de conexiune la internet în laborator):
  1. *Curenți de Fază & Nul (`IA`, `IB`, `IC`, `IN`, `IG`) [A]*
  2. *Tensiuni Linie-Linie (`VAB`, `VBC`, `VCA`) [V]*
  3. *Tensiuni Fază-Nul (`VAN`, `VBN`, `VCN`) [V]*
  4. *Profil Puteri Electrice (`P` Activă, `Q` Reactivă, `S` Aparentă)*
  5. *Stabilitate Frecvență (`Hz`) & Factor de Putere (`cos φ`)*
  6. *Indicatori Calitate: Dezechilibru Curent (`%`) & Grad Încărcare (`% In`)*
- **Mutare Modulară & Personalizare**:
  - Fiecare grafic poate fi mutat prin **Drag & Drop** direct cu mouse-ul sau cu butoanele `⬅` / `➡`.
  - Fiecare grafic poate fi **activat / dezactivat (Enable / Disable)** și redimensionat pe **1 coloană** sau **2 coloane** (`⤢ 1 Col / 2 Col`).
- **Persistență Dublă pentru Data Viitoare**:
  - Ordinea graficelor, starea lor (`enabled/disabled`), lățimea, fereastra de timp (`30 / 60 / 120` citiri) și setarea alertei sonore se salvează automat atât în **`localStorage`** (în browser), cât și pe **server în fișierul `ui_preferences.json`** (prin ruta `/api/ui-config`).

### 2.3. Calculul Automat al Indicatorilor Energetici Suplimentari (`src/eaton_pxr/analytics.py`)
Pe lângă mărimile brute citite din registrele Modbus, sistemul calculează automat la fiecare ciclu (atât pentru fiecare Slave ID individual, cât și pentru mediile pe întregul lanț) 8 indicatori derivați de calitate a energiei electrice:

1. **Gradul de Încărcare al Disjunctorului (`LOAD_PCT`)**:
   $$\text{Încărcare (\%)} = \frac{\max(I_A, I_B, I_C)}{I_n} \times 100, \quad (I_n = 1600\text{ A})$$
   - *Praguri*: Normal ($< 70\%$), Încărcare ridicată ($70\% - 90\%$), Risc suprasarcină ($> 90\%$).
2. **Dezechilibrul de Curent între Faze (`I_UNBAL` — conform NEMA / IEEE)**:
   $$I_{\text{med}} = \frac{I_A + I_B + I_C}{3}, \quad \Delta I_{\%} = \frac{\max(|I_A - I_{\text{med}}|, |I_B - I_{\text{med}}|, |I_C - I_{\text{med}}|)}{I_{\text{med}}} \times 100$$
   - *Praguri*: Echilibrat ($< 10\%$), Dezechilibru moderat ($10\% - 20\%$), Dezechilibru sever ($> 20\%$).
3. **Dezechilibrul Tensiunilor Linie-Linie (`V_LL_UNBAL` — conform EN 50160 / NEMA MG1)**:
   $$\Delta V_{LL\%} = \frac{\max(|V_{AB} - V_{\text{med}}|, |V_{BC} - V_{\text{med}}|, |V_{CA} - V_{\text{med}}|)}{V_{\text{med}}} \times 100$$
   - *Praguri*: Normal ($< 2\%$), Atenție ($2\% - 5\%$), Critic pentru motoare ($> 5\%$).
4. **Dezechilibrul Tensiunilor Fază-Nul (`V_LN_UNBAL`)**:
   - Monitorizează deplasarea punctului neutru și nesimetria tensiunilor de fază ($V_{AN}, V_{BN}, V_{CN}$).
5. **Eficiența Factorului de Putere ($\cos \varphi$) & Puterea Reactivă de Compensare (`PF_QUALITY`)**:
   - *Încadrare tarifară ANRE*: Fără penalizare ($\cos \varphi \ge 0.92$), Penalizare energie reactivă ($0.65 \le \cos \varphi < 0.92$), Penalizare triplă critică ($\cos \varphi < 0.65$).
   - *Calcul baterie condensatoare necesară ($Q_{\text{comp}}$)* pentru a aduce factorul de putere la ținta $\cos \varphi_{\text{target}} = 0.95$:
     $$Q_{\text{comp}} = P \cdot \left(\tan(\arccos(\cos \varphi_{\text{actual}})) - \tan(\arccos(0.95))\right) \text{ [kVAr]}$$
6. **Încărcarea Conductorului de Nul (`IN_RATIO`)**:
   $$\text{Raport Nul (\%)} = \frac{I_N}{I_{\text{med}}} \times 100$$
   - Valori $> 15\%$ semnalează nesimetrie de sarcină sau circulație de curenți armonici homopolari (armonica a 3-a și multiplii ei).
7. **Abaterea Frecvenței Rețelei (`FREQ_DEV` — conform EN 50160)**:
   $$\Delta f = f_{\text{măsurat}} - 50.00\text{ Hz}$$
   - Domeniul normal în SEN este $50\text{ Hz} \pm 0.2\text{ Hz}$ (maxim admisibil $\pm 1\%$, adică $49.50 .. 50.50\text{ Hz}$).
8. **Puterea Deformantă Estimată (`D_POWER`)**:
   $$D = \sqrt{\max(0, S^2 - P^2 - Q^2)} \text{ [VA]}$$
   - Evaluează reziduul de putere aparentă cauzat de distorsiunile armonice.

### 2.4. Alertă Sonoră în Caz de Stare de Alarmă
- Implementată prin **Web Audio API** (sintetizator audio integrat în browser, fără fișiere audio externe).
- Se declanșează automat atunci când:
  - Un disjunctor intră în stare **Declanșat / Tripat (`0x03`)** sau **Alarmă activă (`0x04`)**;
  - Apare o **Pre-alarmă (`0x02`)** sau o cauză de eveniment diferită de starea Normală (`0x0000`);
  - Se întrerupe comunicarea cu un dispozitiv din lanțul RS-485 (`chain_break`);
  - Un indicator energetic suplimentar atinge pragul critic (`danger`).
- Include buton de **Mute / Unmute** persistent, buton de **Test Alarmă** și buton de **Confirmare (Acknowledge)** pentru oprirea sunetului alarmei curente.

---

## 3. Dezvoltări Viitoare (Roadmap) — Serviciul de Notificare Externă Automată

> **Statut:** *Planificat pentru implementare în versiunea viitoare a proiectului.*

Pe lângă alerta vizuală (Pop-up modal + Banner de alarmă) și alerta sonoră locală din browser implementate în prezent, sistemul va fi extins cu un **Serviciu de Notificare Externă Automată (`src/eaton_pxr/notifier.py`)** pentru alertarea la distanță a personalului tehnic de mentenanță.

### 3.1. Canale de Comunicare Planificate
1. **Telegram Bot API**:
   - Trimiterea instantanee pe un grup/canal de intervenție a unui mesaj formatat cu ID-ul disjunctorului, cauza declanșării (`Ir`, `Isd`, `Ii`, `Ig`, `Overtemperature`), curenții măsurați în momentul declanșării ($I_A, I_B, I_C, I_G$) și topologia lanțului rămas activ.
2. **Email Automat (SMTP / TLS)**:
   - Trimiterea de alerte detaliate către inginerul energetician, având atașat automat un extras CSV/PDF cu ultimele 5 minute de măsurători dinaintea incidentului.
3. **Webhook Industrial (Discord / Microsoft Teams / Slack / SCADA REST)**:
   - Integrare prin cereri HTTP `POST` (JSON) către platformele de comunicare ale echipei de mentenanță.
4. **SMS / Apel de Urgență (prin gateway GSM local sau Twilio API)**:
   - Pentru avarii critice (întreruperea totală a lanțului RS-485 sau declanșarea prin scurtcircuit a unui disjunctor principal de $1600\text{ A}$).

### 3.2. Arhitectura Viitorului Modul de Notificare
- **Execuție Asincronă (Non-Blocking)**: Trimiterea notificărilor prin rețea va rula pe un fir de execuție dedicat (`NotificationWorker` cu `queue.Queue`), astfel încât o eventuală întârziere a conexiunii la internet să nu încetinească niciodată bucla de citire Modbus RTU de la 2 secunde.
- **Mecanism de Deduplicare & Cooldown (Anti-Spam)**:
  - Pentru aceeași semnătură de alarmă (ex: Slave ID `#4` în stare `Tripped`), sistemul va trimite **o singură notificare inițială**, urmată de un reminder doar dacă problema nu a fost remediată după un interval configurabil (ex: 30 de minute), și o **notificare de revenire la normal (Recovery)** în momentul în care disjunctorul este reînchis sau lanțul RS-485 este restabilit.

---

## 4. Arhitectura Bazei de Date pe Termen Lung & Implementarea PostgreSQL + TimescaleDB

### Scriere în loturi (Batch Insert / Write Buffer în RAM)
Nu faci INSERT în baza de date la fiecare 2 secunde. Firul Modbus pune citirile într-o coadă în memorie (`queue.Queue`), iar un fir de DB face un singur Bulk Insert o dată la 10–20 de secunde (câte 100–300 de rânduri dintr-un foc).

### Downsampling Automat & Politici de Retenție (Continuous Aggregates)
Nu ai nevoie de rezoluție la 2 secunde pentru datele de acum 2 ani! Se configurează 3 niveluri automate în baza de date:
- **Date brute (la 2 secunde)**: se păstrează doar 14–30 zile (pentru analiza fină a unei avarii recente), după care partițiile vechi se șterg automat.
- **Date agregate la 1 minut (`AVG`, `MIN`, `MAX`)**: calculate automat de baza de date și păstrate 1 an (ocupă de $30\times$ mai puțin loc).
- **Date agregate la 15 minute / 1 oră (curba de sarcină și consumul `kWh`)**: păstrate 5–10 ani (ocupă de $1800\times$ mai puțin loc decât datele la 2 secunde).
- **Tabel separat de Evenimente/Declanșări (`trip_events`)**: pentru că declanșările apar rar, acestea se păstrează permanent fără ștergere.

### Arhivare Rece (Cold Storage în fișiere Apache Parquet)
Dacă vrei totuși să nu pierzi niciodată datele brute la 2 secunde, înainte ca politica de retenție să șteargă luna trecută din DB, un script le exportă într-un fișier lunar `.parquet` (format binar comprimat pe coloane, de ~10 ori mai mic și de zeci de ori mai rapid la citire decât CSV-ul).

---

## 5. Detalii Tehnice ale Implementării Actuale: Containerul Docker `SME` & Coada `queue.Queue` (`src/eaton_pxr/database.py`)

### 5.1. Containerul Docker `SME` (PostgreSQL 16 + TimescaleDB)
Baza de date rulează într-un container Docker dedicat numit **`SME`**, definit în `docker-compose.yml` și inițializat prin `docker/init_timescaledb.sql`:
- **Nume Container**: `SME`
- **Imagine Docker**: `timescale/timescaledb:latest-pg16`
- **Port expus**: `127.0.0.1:5432`
- **Bază de date / Credențiale**: DB = `sme_energy`, User = `sme_user`, Password = `sme_password`
- **Structură Hypertable & Tabele**:
  - `pxr25_measurements`: Hypertable TimescaleDB partiționat automat în *chunk*-uri de `1 day`, care stochează atât cele 20 de mărimi Modbus, cât și cei 8 indicatori energetici suplimentari (pentru fiecare `ID_k` și pentru `AVERAGE`).
  - `trip_events`: Tabel relațional permanent (fără ștergere) pentru istoricul de declanșări și alarme.
  - `pxr25_metrics_1m` și `pxr25_metrics_15m`: *Continuous Aggregates* (view-uri materializate actualizate automat de TimescaleDB la 1 minut și la 15 minute), însoțite de politicile automate de retenție (`30 days` pentru datele brute, `365 days` pentru 1 minut, `1825 days` / 5 ani pentru 15 minute).

### 5.2. Parametrii Exacți pentru Punctul 2 (Coada RAM `queue.Queue` și `Bulk Insert`)
În modulul `src/eaton_pxr/database.py` (clasa `TimescaleBatchWriter`), mecanismul de **Write Buffer în RAM + Bulk Insert** este configurat cu următorii parametri exacți:

1. **Cât de lungă este coada în RAM (`QUEUE_MAX_SIZE`)**:
   - Coada principală de măsurători `self.measurement_queue` este o instanță `queue.Queue(maxsize=5000)` cu o capacitate de **`5.000` de rânduri** în memoria RAM (plus o coadă separată `self.events_queue` de **`1.000` de evenimente** pentru tabelul `trip_events`).
   - Dacă baza de date ar fi oprită temporar pentru mentenanță și coada ar atinge limita de `5.000` de rânduri, sistemul aplică o politică *FIFO ring-buffer* (elimină cel mai vechi rând din coadă pentru a-l adăuga pe cel mai nou), astfel încât firul de citire Modbus RTU la 2 secunde **nu se blochează niciodată**.

2. **La cât timp se face Insert (`BULK_INSERT_INTERVAL_SEC`)**:
   - Firul de fundal `TimescaleBatchWorker` execută `Bulk Insert` la un interval regulat de **`15.0` secunde** (`BULK_INSERT_INTERVAL_SEC = 15.0`, exact în mijlocul ferestrei optime de 10–20 secunde).

3. **Când se declanșează `Bulk Insert`-ul (3 condiții de declanșare)**:
   - **Declanșare la timp (la fiecare `15` secunde)**: Chiar dacă în coadă s-au adunat mai puține rânduri (de exemplu, când sunt doar 1–5 disjunctoare în lanț), la expirarea celor `15` secunde firul golește coada și scrie toate rândurile acumulate într-o singură tranzacție.
   - **Declanșare anticipată la prag de umplere (`BULK_TRIGGER_THRESHOLD = 150` rânduri)**: Dacă în lanț sunt multe disjunctoare și în coada din RAM se strâng **`150` de rânduri** înainte să treacă cele `15` secunde, metoda `_put_row_safe` activează imediat semnalul `self._flush_event.set()`, declanșând `Bulk Insert`-ul pe loc, fără așteptare.
   - **Declanșare manuală din Dashboard**: Utilizatorul poate apăsa oricând butonul **„💾 Flush Coadă RAM ➔ DB Acum”** din interfața Web (`POST /api/db-flush`), care forțează golirea imediată a cozii în TimescaleDB.

4. **Cu câte rânduri se face `Bulk Insert` (`MAX_ROWS_PER_BATCH`)**:
   - Fiecare operație de `Bulk Insert` extrage din coada RAM **până la `300` de rânduri dintr-un foc** (`MAX_ROWS_PER_BATCH = 300`) și le inserează într-o singură tranzacție SQL (`cur.executemany(...)` urmat de un singur `conn.commit()`).
   - În regim cu multe aparate în lanț (sau când se declanșează la pragul de `150`–`300` rânduri), un lot conține între **`100` și `300` de rânduri** inserate simultan. În cazul unei erori de rețea/conexiune, toate rândurile din lotul curent sunt repuse automat înapoi în `queue.Queue`, prevenind pierderea datelor.

### 5.3. Cele 4 Politici de Retenție Configurate în TimescaleDB (`docker/init_timescaledb.sql`)
Politicile de retenție ale bazei de date sunt împărțite pe **4 niveluri**:

1. **Datele brute la 2 secunde (`pxr25_measurements`) — păstrate `30 de zile` (`INTERVAL '30 days'`)**
   - Sunt folosite pentru analiza în detaliu a incidentelor recente. După 30 de zile, TimescaleDB șterge automat partițiile (*chunks*) vechi de 2 secunde (`add_retention_policy`) ca să elibereze spațiul pe disc.
2. **Datele agregate la 1 minut (`pxr25_metrics_1m`) — păstrate `1 an (365 zile)` (`INTERVAL '365 days'`)**
   - Baza de date calculează automat în fundal `AVG`, `MIN` și `MAX` pe fiecare minut (ocupă de $30\times$ mai puțin loc) și le șterge abia după 1 an.
3. **Datele agregate la 15 minute (`pxr25_metrics_15m`) — păstrate `5 ani (1.825 zile)` (`INTERVAL '1825 days'`)**
   - Păstrează profilul de sarcină (`P`, `Q`, `S`, $\cos \varphi$) și contoarele de energie (`kWh`) pe termen lung, pentru istoric și audit energetic (ocupă de $450\times$ mai puțin loc decât datele la 2 secunde).
4. **Istoricul de declanșări și alarme (`trip_events`) — păstrat `Permanent (fără limită de timp)`**
   - Deoarece declanșările (`Trip`) și alarmele apar doar la evenimente (nu la fiecare 2 secunde), acest tabel nu are politică de ștergere și păstrează toate avariile definitiv.
