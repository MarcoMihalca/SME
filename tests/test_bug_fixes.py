"""
Suite de teste unitare și de regresie pentru verificarea remedierii bug-urilor
Critice, Importante și Minore din platforma Eaton PXR25 (SME).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.eaton_pxr import decoder
from src.eaton_pxr.analytics import compute_energy_indicators, evaluate_alarm_state
from src.eaton_pxr.csv_exporter import CsvExporter
from src.eaton_pxr.database import TimescaleBatchWriter
from src.eaton_pxr.models import (
    MeasuredValue,
    PxrSnapshot,
    SerialConnectionConfig,
    TripEvent,
)
from src.eaton_pxr.reader import read_realtime_measurements
from src.eaton_pxr.registers import PXR25_PARAMETERS
from src.eaton_pxr.scanner import compute_fleet_averages
from src.eaton_pxr.web import server
from src.eaton_pxr.web.server import MultiDeviceDashboardState


def _make_sample_measurements(ia: float = 400.0) -> list[MeasuredValue]:
    vals = {
        "I_A": ia,
        "I_B": ia,
        "I_C": ia,
        "I_G": 0.0,
        "I_N": 10.0,
        "V_AB": 400.0,
        "V_BC": 400.0,
        "V_CA": 400.0,
        "V_AN": 230.0,
        "V_BN": 230.0,
        "V_CN": 230.0,
        "P_TOT": 250000.0,
        "Q_TOT": 80000.0,
        "S_TOT": 262488.0,
        "PF_TOT": 0.95,
        "FREQ": 50.0,
        "E_FWD": 1200.0,
        "E_REV": 0.0,
        "E_TOT": 1200.0,
        "E_APP": 1260.0,
    }
    return [
        MeasuredValue(p.key, p.name, p.category, vals.get(p.key), p.unit)
        for p in PXR25_PARAMETERS
    ]


def _make_snapshot(slave_id: int = 1, cause: str = "Normal [0x0000]") -> PxrSnapshot:
    meas = _make_sample_measurements()
    inds = compute_energy_indicators(meas)
    return PxrSnapshot(
        slave_id=slave_id,
        timestamp="2026-11-12 21:00:00",
        connection_desc=f"COM5 [Slave #{slave_id}]",
        status_info={
            "Stare Principală Disjunctor": "Închis (Closed) [0x02]",
            "Stare Secundară Unitate PXR": "Alimentat / Normal (Powered-Up) [0x07]",
            "Cauză Stare / Eveniment": cause,
        },
        measurements=meas,
        energy_indicators=inds,
        protection_settings=[],
        event_history=[],
    )


class TestCriticalBugFixes(unittest.TestCase):
    """Teste pentru cele 4 probleme Critice raportate la Code Review."""

    def test_critical_1a_live_status_transition_enqueues_trip_event_to_db(self) -> None:
        """Când apare o schimbare de stare/cauză în timpul monitorizării live, evenimentul ajunge și în db_writer."""
        db_mock = MagicMock()
        last_cause: dict[int, str] = {}
        session_events: dict[int, list[TripEvent]] = {}

        record_fn = getattr(server, "record_live_status_transition", None)
        self.assertIsNotNone(record_fn, "record_live_status_transition lipseste din server.py")
        # Prima citire în stare normală nu trebuie să insereze declanșare falsă în trip_events
        snap_normal = _make_snapshot(slave_id=2, cause="Normal (Fără eveniment de declanșare/alarmă) [0x0000]")
        record_fn(
            snap=snap_normal,
            last_cause_per_id=last_cause,
            session_events_per_id=session_events,
            db_writer=db_mock,
        )
        db_mock.enqueue_trip_event.assert_not_called()

        # Tranziție în stare de declanșare (Trip pe Suprasarcină Ir) -> trebuie trimisă în trip_events
        snap_trip = _make_snapshot(slave_id=2, cause="Suprasarcină / Long Delay (Ir) [0x0001]")
        snap_trip.status_info["Stare Principală Disjunctor"] = "Declanșat / Tripat (Tripped) [0x03]"
        record_fn(
            snap=snap_trip,
            last_cause_per_id=last_cause,
            session_events_per_id=session_events,
            db_writer=db_mock,
        )
        db_mock.enqueue_trip_event.assert_called_once()
        called_sid, called_ev = db_mock.enqueue_trip_event.call_args[0]
        self.assertEqual(called_sid, 2)
        self.assertIn("Suprasarcină", called_ev.cause)

    def test_critical_1b_events_queue_preserved_on_db_insert_error(self) -> None:
        """Dacă inserarea în DB eșuează, atât measurement_queue cât și events_queue își păstrează elementele."""
        with patch.object(TimescaleBatchWriter, "_connect") as mock_connect:
            failing_conn = MagicMock()
            failing_cursor = MagicMock()
            # _ensure_schema reușește, dar executemany la batch eșuează
            failing_cursor.executemany.side_effect = RuntimeError("DB connection lost")
            failing_conn.cursor.return_value.__enter__.return_value = failing_cursor
            mock_connect.return_value = failing_conn

            writer = TimescaleBatchWriter(flush_interval_sec=60.0)
            writer.schema_ready = True
            ev = TripEvent(
                event_id="99",
                event_type="Declanșare (Trip)",
                timestamp="2026-11-12 21:00:00",
                cause="Scurtcircuit (Isd)",
                currents="IA=4800.0A",
            )
            writer.enqueue_trip_event(1, ev)
            writer.trigger_flush()

            # Așteptăm scurt ca worker-ul să încerce flush-ul și să eșueze
            import time

            time.sleep(0.15)
            self.assertEqual(writer.events_queue.qsize(), 1)
            writer._stop_event.set()

    def test_critical_2_close_flushes_remaining_queues_and_joins_worker(self) -> None:
        """La apelul close(), TimescaleBatchWriter golește cozile rămase în DB și așteaptă firul worker."""
        inserted_meas: list = []
        inserted_events: list = []

        with patch.object(TimescaleBatchWriter, "_connect") as mock_connect:
            fake_conn = MagicMock()
            fake_cursor = MagicMock()

            def side_execmany(sql: str, seq: list) -> None:
                if "pxr25_measurements" in sql:
                    inserted_meas.extend(seq)
                elif "trip_events" in sql:
                    inserted_events.extend(seq)

            fake_cursor.executemany.side_effect = side_execmany
            fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
            mock_connect.return_value = fake_conn

            writer = TimescaleBatchWriter(flush_interval_sec=60.0)
            writer.schema_ready = True
            snap = _make_snapshot(slave_id=1)
            writer.enqueue_snapshot(snap)
            writer.enqueue_trip_event(
                1,
                TripEvent("1", "Trip", "2026-11-12 21:00:00", "Ir", "IA=2000A"),
            )

            writer.close()

            self.assertFalse(writer._worker_thread.is_alive())
            self.assertEqual(writer.measurement_queue.qsize(), 0)
            self.assertEqual(writer.events_queue.qsize(), 0)
            self.assertGreaterEqual(len(inserted_meas), 1)
            self.assertEqual(len(inserted_events), 1)

    def test_critical_3_chain_break_preserves_error_and_recovers_when_empty(self) -> None:
        """Întreruperea lanțului nu șterge eroarea la ciclul următor și permite rescanarea dacă ID #1 a picat."""
        cfg = SerialConnectionConfig(port="COM5")
        state = MultiDeviceDashboardState(config=cfg, csv_path="dummy.csv", db_writer=None)
        state.active_ids = [1, 2, 3]
        state.confirmed_ids = [1, 2, 3]

        update_fn = getattr(server, "update_state_after_poll", None)
        apply_fn = getattr(server, "apply_chain_alert_action", None)
        self.assertIsNotNone(update_fn, "update_state_after_poll lipseste din server.py")
        self.assertIsNotNone(apply_fn, "apply_chain_alert_action lipseste din server.py")

        # Simulăm că dispozitivul #3 nu mai răspunde (broken_at_id = 3)
        snaps = {1: _make_snapshot(1), 2: _make_snapshot(2)}
        update_fn(
            state=state,
            chain_to_poll=[1, 2, 3],
            current_snapshots=snaps,
            broken_at_id=3,
            now_str="2026-11-12 21:00:00",
            total_csv_rows=10,
            settings_cache={},
            events_cache={},
            session_events_per_id={},
        )
        self.assertTrue(state.chain_alert["pending"])
        self.assertIn("Slave ID #3", state.last_error)

        # Dacă operatorul apasă "OK" când nu mai există niciun aparat supraviețuitor (ex: #1 a picat),
        # trebuie să se declanșeze needs_discovery = True pentru a nu bloca bucla infinită.
        state.active_ids = []
        state.confirmed_ids = []
        state.needs_discovery = False
        apply_fn(state, "ok")
        self.assertTrue(state.needs_discovery)

    def test_critical_4_csv_exporter_handles_permission_error_gracefully(self) -> None:
        """Dacă fișierul CSV este blocat de Excel (PermissionError), append_snapshot nu aruncă excepție."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = os.path.join(tmpdir, "test_log.csv")
            exporter = CsvExporter(csv_file)
            snap = _make_snapshot(1)

            with patch("builtins.open", side_effect=PermissionError("Locked by Excel")):
                rows_after_snap = exporter.append_snapshot(snap)
                rows_after_avg = exporter.append_averages_row(
                    "2026-11-12 21:00:00", 1, snap.measurements
                )

            self.assertEqual(rows_after_snap, 0)
            self.assertEqual(rows_after_avg, 0)


class TestImportantAndMinorBugFixes(unittest.TestCase):
    """Teste pentru problemele Importante (5..9) și Minore (10..12)."""

    def test_important_6_halted_state_does_not_trigger_unacknowledged_audio_alarm(self) -> None:
        """Oprirea voită a citirii (halted=True) de către operator nu declanșează alarma sonoră continuă."""
        alarm = evaluate_alarm_state(devices={}, chain_alert={"pending": False}, halted=True)
        self.assertFalse(alarm["active"])

    def test_important_7_read_realtime_measurements_uses_contiguous_block_reads(self) -> None:
        """read_realtime_measurements citește registrele în 2 blocuri contigue în loc de 21 cereri separate."""
        fake_client = MagicMock()

        def fake_read(address: int, count: int = 2, slave: int = 1, **kwargs):
            resp = MagicMock()
            resp.isError.return_value = False
            # Returnăm un vector de registre suficiente pentru orice bloc cerut
            resp.registers = [0x0207, 0x0000] + [100, 0] * max(1, count)
            return resp

        fake_client.read_holding_registers.side_effect = fake_read
        cfg = SerialConnectionConfig(port="COM5", slave_id=1, use_float=False)

        status_info, measurements = read_realtime_measurements(fake_client, cfg)
        self.assertEqual(len(measurements), 20)
        self.assertIn("Închis", status_info["Stare Principală Disjunctor"])
        # Trebuie să facă cel mult 2 citiri Modbus (blocul 0x1800..0x1835 și blocul 0x1872..0x187F), nu 21!
        self.assertLessEqual(fake_client.read_holding_registers.call_count, 2)

    def test_important_9_decoder_and_analytics_and_fleet_averages(self) -> None:
        """Verifică decodarea 32-bit, Tuple în decoder, media pe flotă și indicatorii energetici."""
        self.assertIn("Tuple", decoder.__dict__)
        self.assertEqual(decoder.decode_32bit_int(0x03E8, 0x0000, signed=True, word_swap=True), 1000)
        fmt, in_a, ir_a = decoder.decode_protection_value("In", 1600, 1600.0, 1600.0)
        self.assertIn("1600 A", fmt)

        s1 = _make_snapshot(1)
        s2 = _make_snapshot(2)
        avgs = compute_fleet_averages({1: s1, 2: s2})
        self.assertEqual(len(avgs), 20)
        self.assertAlmostEqual(avgs[0].value or 0.0, 400.0)


if __name__ == "__main__":
    unittest.main()
