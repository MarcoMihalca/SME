"""
Serviciul de persistență PostgreSQL + TimescaleDB (Container Docker: SME)
cu Scriere în Loturi (Batch Insert / Write Buffer în RAM folosind `queue.Queue`).

Arhitectura implementată (Punctul 2):
  - Firul de achiziție Modbus la 2 secunde NU face INSERT direct în baza de date.
  - Fiecare citire este pusă instantaneu (non-blocking) într-o coadă în RAM (`queue.Queue`)
    cu capacitatea maximă `QUEUE_MAX_SIZE = 5000` de înregistrări.
  - Un fir de execuție dedicat (`db_batch_worker`) golește coada și execută un singur
    `Bulk Insert` tranzacțional fie o dată la `BULK_INSERT_INTERVAL_SEC = 15.0` secunde,
    fie anticipat în momentul în care în coadă s-au strâns `BULK_TRIGGER_THRESHOLD = 150`
    rânduri, inserând câte `100–300` de rânduri dintr-un foc (`MAX_ROWS_PER_BATCH = 300`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import EnergyIndicator, MeasuredValue, PxrSnapshot, TripEvent

# Parametrii cozii din RAM și ai scrierii în loturi (Batch / Bulk Insert)
QUEUE_MAX_SIZE: int = 5000
BULK_INSERT_INTERVAL_SEC: float = 15.0
BULK_TRIGGER_THRESHOLD: int = 150
MAX_ROWS_PER_BATCH: int = 300

MEASUREMENT_COLUMNS = (
    "time",
    "slave_id",
    "primary_status",
    "secondary_status",
    "cause_of_status",
    "i_a",
    "i_b",
    "i_c",
    "i_g",
    "i_n",
    "v_ab",
    "v_bc",
    "v_ca",
    "v_an",
    "v_bn",
    "v_cn",
    "p_tot",
    "q_tot",
    "s_tot",
    "pf_tot",
    "freq",
    "e_fwd",
    "e_rev",
    "e_tot",
    "e_app",
    "load_pct",
    "i_unbal",
    "v_ll_unbal",
    "v_ln_unbal",
    "pf_quality",
    "in_ratio",
    "freq_dev",
    "d_power",
)


class TimescaleBatchWriter:
    """
    Gestionează coada din RAM (`queue.Queue`) și inserarea în loturi (Bulk Insert)
    în containerul Docker `SME` (PostgreSQL 16 + TimescaleDB).
    """

    def __init__(
        self,
        host: str = os.environ.get("SME_DB_HOST", "127.0.0.1"),
        port: int = int(os.environ.get("SME_DB_PORT", "5432")),
        dbname: str = os.environ.get("SME_DB_NAME", "sme_energy"),
        user: str = os.environ.get("SME_DB_USER", "sme_user"),
        password: str = os.environ.get("SME_DB_PASSWORD", "sme_password"),
        flush_interval_sec: float = BULK_INSERT_INTERVAL_SEC,
        trigger_threshold: int = BULK_TRIGGER_THRESHOLD,
        max_batch_size: int = MAX_ROWS_PER_BATCH,
    ) -> None:
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self.password = password

        self.flush_interval_sec = flush_interval_sec
        self.trigger_threshold = trigger_threshold
        self.max_batch_size = max_batch_size

        # Coada în memorie RAM pentru măsurători și coada pentru evenimente/declanșări
        self.measurement_queue: queue.Queue[Tuple[Any, ...]] = queue.Queue(
            maxsize=QUEUE_MAX_SIZE
        )
        self.events_queue: queue.Queue[Tuple[Any, ...]] = queue.Queue(maxsize=1000)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_event = threading.Event()

        self.connected: bool = False
        self.schema_ready: bool = False
        self.total_inserted_rows: int = 0
        self.total_batches: int = 0
        self.last_batch_rows: int = 0
        self.last_flush_time: str = "—"
        self.last_error: str = "Inițializare conexiune către containerul Docker SME..."

        # Semnalizăm conectarea și verificarea schemei imediat la pornire
        self._flush_event.set()
        self._worker_thread = threading.Thread(
            target=self._batch_worker_loop, name="TimescaleBatchWorker", daemon=True
        )
        self._worker_thread.start()

    def _connect(self):
        """Deschide o conexiune către PostgreSQL/TimescaleDB folosind psycopg (v3) sau psycopg2."""
        try:
            import psycopg  # type: ignore

            return psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                connect_timeout=4,
                autocommit=False,
            )
        except ImportError:
            import psycopg2  # type: ignore

            return psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                connect_timeout=4,
            )

    def _ensure_schema(self, conn: Any) -> None:
        """Creează extensia TimescaleDB, hypertable-ul și politicile dacă nu există deja."""
        if self.schema_ready:
            return

        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pxr25_measurements (
                    time TIMESTAMPTZ NOT NULL,
                    slave_id TEXT NOT NULL,
                    primary_status TEXT,
                    secondary_status TEXT,
                    cause_of_status TEXT,
                    i_a DOUBLE PRECISION,
                    i_b DOUBLE PRECISION,
                    i_c DOUBLE PRECISION,
                    i_g DOUBLE PRECISION,
                    i_n DOUBLE PRECISION,
                    v_ab DOUBLE PRECISION,
                    v_bc DOUBLE PRECISION,
                    v_ca DOUBLE PRECISION,
                    v_an DOUBLE PRECISION,
                    v_bn DOUBLE PRECISION,
                    v_cn DOUBLE PRECISION,
                    p_tot DOUBLE PRECISION,
                    q_tot DOUBLE PRECISION,
                    s_tot DOUBLE PRECISION,
                    pf_tot DOUBLE PRECISION,
                    freq DOUBLE PRECISION,
                    e_fwd DOUBLE PRECISION,
                    e_rev DOUBLE PRECISION,
                    e_tot DOUBLE PRECISION,
                    e_app DOUBLE PRECISION,
                    load_pct DOUBLE PRECISION,
                    i_unbal DOUBLE PRECISION,
                    v_ll_unbal DOUBLE PRECISION,
                    v_ln_unbal DOUBLE PRECISION,
                    pf_quality DOUBLE PRECISION,
                    in_ratio DOUBLE PRECISION,
                    freq_dev DOUBLE PRECISION,
                    d_power DOUBLE PRECISION
                );
                """
            )
            cur.execute(
                """
                SELECT create_hypertable(
                    'pxr25_measurements',
                    'time',
                    chunk_time_interval => INTERVAL '1 day',
                    if_not_exists => TRUE
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pxr25_meas_slave_time
                    ON pxr25_measurements (slave_id, time DESC);
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trip_events (
                    id BIGSERIAL PRIMARY KEY,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    slave_id INT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_timestamp TEXT NOT NULL,
                    cause TEXT NOT NULL,
                    currents TEXT,
                    UNIQUE (slave_id, event_id, event_timestamp, cause)
                );
                """
            )
        conn.commit()
        self.schema_ready = True

    @staticmethod
    def _build_measurement_tuple(
        slave_label: str,
        status_info: Dict[str, str],
        measurements: List[MeasuredValue],
        indicators: List[EnergyIndicator],
    ) -> Tuple[Any, ...]:
        m_map: Dict[str, Optional[float]] = {m.key: m.value for m in measurements}
        i_map: Dict[str, Optional[float]] = {ind.key: ind.value for ind in indicators}
        now_dt = datetime.now(timezone.utc)

        return (
            now_dt,
            slave_label,
            status_info.get("Stare Principală Disjunctor", ""),
            status_info.get("Stare Secundară Unitate PXR", ""),
            status_info.get("Cauză Stare / Eveniment", ""),
            m_map.get("I_A"),
            m_map.get("I_B"),
            m_map.get("I_C"),
            m_map.get("I_G"),
            m_map.get("I_N"),
            m_map.get("V_AB"),
            m_map.get("V_BC"),
            m_map.get("V_CA"),
            m_map.get("V_AN"),
            m_map.get("V_BN"),
            m_map.get("V_CN"),
            m_map.get("P_TOT"),
            m_map.get("Q_TOT"),
            m_map.get("S_TOT"),
            m_map.get("PF_TOT"),
            m_map.get("FREQ"),
            m_map.get("E_FWD"),
            m_map.get("E_REV"),
            m_map.get("E_TOT"),
            m_map.get("E_APP"),
            i_map.get("LOAD_PCT"),
            i_map.get("I_UNBAL"),
            i_map.get("V_LL_UNBAL"),
            i_map.get("V_LN_UNBAL"),
            i_map.get("PF_QUALITY"),
            i_map.get("IN_RATIO"),
            i_map.get("FREQ_DEV"),
            i_map.get("D_POWER"),
        )

    def enqueue_snapshot(self, snapshot: PxrSnapshot) -> None:
        """
        Adaugă non-blocking în coada din RAM (`queue.Queue`) un snapshot al unui Slave ID
        și eventualele evenimente de declanșare.
        """
        row = self._build_measurement_tuple(
            slave_label=f"ID_{snapshot.slave_id}",
            status_info=snapshot.status_info,
            measurements=snapshot.measurements,
            indicators=snapshot.energy_indicators,
        )
        self._put_row_safe(row)

        for ev in snapshot.event_history:
            if ev.event_id != "ACTIV":
                self.enqueue_trip_event(snapshot.slave_id, ev)

    def enqueue_averages(
        self,
        active_count: int,
        averages: List[MeasuredValue],
        indicators: List[EnergyIndicator],
    ) -> None:
        """Adaugă în coada din RAM rândul de medii (AVERAGE) pe lanțul activ."""
        if active_count <= 0:
            return
        row = self._build_measurement_tuple(
            slave_label="AVERAGE",
            status_info={
                "Stare Principală Disjunctor": f"{active_count} active",
                "Stare Secundară Unitate PXR": "—",
                "Cauză Stare / Eveniment": "—",
            },
            measurements=averages,
            indicators=indicators,
        )
        self._put_row_safe(row)

    def enqueue_trip_event(self, slave_id: int, event: TripEvent) -> None:
        """Adaugă un eveniment de declanșare în coada dedicată tabelului permanent `trip_events`."""
        ev_tuple = (
            slave_id,
            str(event.event_id),
            event.event_type,
            event.timestamp,
            event.cause,
            event.currents,
        )
        try:
            self.events_queue.put_nowait(ev_tuple)
        except queue.Full:
            pass

    def _put_row_safe(self, row: Tuple[Any, ...]) -> None:
        try:
            self.measurement_queue.put_nowait(row)
        except queue.Full:
            # Dacă baza de date a fost oprită mult timp și coada de 5000 s-a umplut,
            # eliminăm cel mai vechi element pentru a face loc celui nou.
            try:
                self.measurement_queue.get_nowait()
                self.measurement_queue.put_nowait(row)
            except Exception:
                pass

        if self.measurement_queue.qsize() >= self.trigger_threshold:
            self._flush_event.set()

    def trigger_flush(self) -> None:
        """Declanșează imediat un Bulk Insert din coada RAM în TimescaleDB."""
        self._flush_event.set()

    def _batch_worker_loop(self) -> None:
        conn: Any = None
        cols_sql = ", ".join(MEASUREMENT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(MEASUREMENT_COLUMNS))
        insert_meas_sql = (
            f"INSERT INTO pxr25_measurements ({cols_sql}) VALUES ({placeholders})"
        )
        insert_event_sql = """
            INSERT INTO trip_events (slave_id, event_id, event_type, event_timestamp, cause, currents)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (slave_id, event_id, event_timestamp, cause) DO NOTHING
        """

        while not self._stop_event.is_set():
            self._flush_event.wait(timeout=self.flush_interval_sec)
            self._flush_event.clear()

            # Verificăm conexiunea și schema chiar dacă nu sunt rânduri încă
            if conn is None:
                try:
                    conn = self._connect()
                    self._ensure_schema(conn)
                    with self._lock:
                        self.connected = True
                        self.last_error = ""
                except Exception as exc:
                    with self._lock:
                        self.connected = False
                        self.last_error = f"Conexiune TimescaleDB (SME) indisponibilă: {exc}"
                    conn = None
                    continue

            # Extragem un lot (batch) de până la MAX_ROWS_PER_BATCH (300) rânduri din coada RAM
            batch: List[Tuple[Any, ...]] = []
            while len(batch) < self.max_batch_size:
                try:
                    batch.append(self.measurement_queue.get_nowait())
                except queue.Empty:
                    break

            ev_batch: List[Tuple[Any, ...]] = []
            while len(ev_batch) < 200:
                try:
                    ev_batch.append(self.events_queue.get_nowait())
                except queue.Empty:
                    break

            if not batch and not ev_batch:
                continue

            try:
                with conn.cursor() as cur:
                    if batch:
                        cur.executemany(insert_meas_sql, batch)
                    if ev_batch:
                        cur.executemany(insert_event_sql, ev_batch)
                conn.commit()

                now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                with self._lock:
                    self.connected = True
                    self.last_error = ""
                    if batch:
                        self.total_inserted_rows += len(batch)
                        self.total_batches += 1
                        self.last_batch_rows = len(batch)
                        self.last_flush_time = now_str
            except Exception as exc:
                # Dacă inserarea a eșuat (ex. containerul a fost repornit), punem rândurile înapoi în coadă
                for row in batch:
                    try:
                        self.measurement_queue.put_nowait(row)
                    except queue.Full:
                        break
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
                with self._lock:
                    self.connected = False
                    self.last_error = f"Eroare la Bulk Insert în TimescaleDB: {exc}"

    def close(self) -> None:
        self._stop_event.set()
        self._flush_event.set()

    def get_status_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "connected": self.connected,
                "container_name": "SME",
                "db_target": f"{self.host}:{self.port}/{self.dbname}",
                "queue_size": self.measurement_queue.qsize(),
                "queue_max_size": QUEUE_MAX_SIZE,
                "flush_interval_sec": self.flush_interval_sec,
                "trigger_threshold": self.trigger_threshold,
                "max_batch_size": self.max_batch_size,
                "total_inserted_rows": self.total_inserted_rows,
                "total_batches": self.total_batches,
                "last_batch_rows": self.last_batch_rows,
                "last_flush_time": self.last_flush_time,
                "last_error": self.last_error,
            }
