"""
Suite de teste unitare și de regresie pentru verificarea remedierii bug-urilor
Critice, Importante și Minore din platforma Eaton PXR25 (SME).
"""

from __future__ import annotations

from datetime import datetime
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.eaton_pxr import decoder
from src.eaton_pxr.analytics import (
    compute_energy_indicators,
    evaluate_alarm_state,
    evaluate_overcurrent_notification,
)
from src.eaton_pxr.csv_exporter import CsvExporter
from src.eaton_pxr.database import TimescaleBatchWriter
from src.eaton_pxr.models import (
    MeasuredValue,
    PxrSnapshot,
    SerialConnectionConfig,
    TripEvent,
)
from src.eaton_pxr.reader import (
    read_device_datetime,
    read_device_on_client,
    read_max_current_setting,
    read_realtime_measurements,
    sync_device_datetime,
)
from src.eaton_pxr.registers import PXR25_PARAMETERS, REG_RTC_START
from src.eaton_pxr.scanner import compute_fleet_averages
from src.eaton_pxr.web import server
from src.eaton_pxr.web.server import (
    MultiDeviceDashboardState,
    trigger_manual_time_sync,
    update_state_after_poll,
)


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


class TestNewFeaturesRtcDropdownSimpleModeAndOvercurrent(unittest.TestCase):
    """Teste pentru sincronizare RTC, citire prag maxim amperaj, notificare și UI."""

    def test_rtc_encode_decode_and_sync_device_datetime(self) -> None:
        """Sincronizează ceasul dispozitivului (0x0B68..0x0B6F) cu data și ora serverului."""
        sample_dt = datetime(2026, 11, 16, 17, 45, 30, 250000)  # Luni (weekday=0 -> Eaton=2)
        regs = decoder.encode_rtc_registers(sample_dt)
        self.assertEqual(regs, [11, 16, 2026, 2, 17, 45, 30, 25])
        self.assertEqual(decoder.decode_rtc_registers(regs), "2026-11-16 17:45:30")

        fake_client = MagicMock()
        ok_resp = MagicMock()
        ok_resp.isError.return_value = False
        fake_client.write_registers.return_value = ok_resp

        ok, ts_str = sync_device_datetime(fake_client, slave_id=3, dt=sample_dt)
        self.assertTrue(ok)
        self.assertEqual(ts_str, "2026-11-16 17:45:30")
        fake_client.write_registers.assert_called_once()
        call_kwargs = fake_client.write_registers.call_args.kwargs
        self.assertEqual(call_kwargs["address"], REG_RTC_START)
        self.assertEqual(call_kwargs["values"], regs)

        # Verificăm și citirea ceasului RTC
        read_resp = MagicMock()
        read_resp.isError.return_value = False
        read_resp.registers = regs
        fake_client.read_holding_registers.return_value = read_resp
        self.assertEqual(read_device_datetime(fake_client, slave_id=3), "2026-11-16 17:45:30")

    def test_rtc_sync_fallback_when_day_of_week_readonly(self) -> None:
        """Dacă scrierea blocului de 8 registre eșuează, fallback-ul scrie data și ora separat."""
        sample_dt = datetime(2026, 11, 16, 18, 0, 5)
        fake_client = MagicMock()
        err_resp = MagicMock()
        err_resp.isError.return_value = True
        ok_resp = MagicMock()
        ok_resp.isError.return_value = False
        fake_client.write_registers.side_effect = [err_resp, ok_resp, ok_resp]

        ok, ts_str = sync_device_datetime(fake_client, slave_id=1, dt=sample_dt)
        self.assertTrue(ok)
        self.assertEqual(ts_str, "2026-11-16 18:00:05")
        self.assertEqual(fake_client.write_registers.call_count, 3)

    def test_read_max_current_setting_and_overcurrent_notification(self) -> None:
        """Citește registrul Ir (0x0BBE) și notifică utilizatorul când sarcina depășește pragul."""
        fake_client = MagicMock()
        write_ok = MagicMock()
        write_ok.isError.return_value = False
        fake_client.write_register.return_value = write_ok

        # Bloc 0x0BB9..0x0BBE (6 registre): In=1600 A la index 0, Ir=75 (% din In = 1200 A) la index 5
        block_resp = MagicMock()
        block_resp.isError.return_value = False
        block_resp.registers = [1600, 0, 0, 0, 0, 75]
        fake_client.read_holding_registers.return_value = block_resp

        max_ir, in_amps, reg_lbl = read_max_current_setting(fake_client, slave_id=1)
        self.assertAlmostEqual(in_amps, 1600.0)
        self.assertAlmostEqual(max_ir, 1200.0)
        self.assertEqual(reg_lbl, "403007 (0x0BBE)")

        # Sub limită (400 A < 1200 A) -> fără notificare
        meas_ok = _make_sample_measurements(ia=400.0)
        alert_ok = evaluate_overcurrent_notification(
            meas_ok, max_current_limit_a=max_ir, slave_id=1, register_label=reg_lbl
        )
        self.assertFalse(alert_ok["exceeded"])
        self.assertEqual(alert_ok["message"], "")

        # Peste limită (1350 A > 1200 A) -> notificare + alarmă critică
        meas_over = _make_sample_measurements(ia=1350.0)
        alert_over = evaluate_overcurrent_notification(
            meas_over, max_current_limit_a=max_ir, slave_id=1, register_label=reg_lbl
        )
        self.assertTrue(alert_over["exceeded"])
        self.assertAlmostEqual(alert_over["current_load_a"], 1350.0)
        self.assertAlmostEqual(alert_over["excess_a"], 150.0)
        self.assertIn("DEPĂȘIT", alert_over["message"])
        self.assertIn("1200.0 A", alert_over["message"])

        alarm = evaluate_alarm_state(
            devices={
                "1": {
                    "status_info": {
                        "Stare Principală Disjunctor": "Închis (Closed) [0x02]",
                        "Stare Secundară Unitate PXR": "Alimentat / Normal [0x07]",
                        "Cauză Stare / Eveniment": "Normal [0x0000]",
                    },
                    "energy_indicators": [],
                    "overcurrent_alert": alert_over,
                }
            },
            chain_alert={"pending": False},
            halted=False,
        )
        self.assertTrue(alarm["active"])
        self.assertEqual(alarm["severity"], "critical")
        self.assertTrue(any("DEPĂȘIT" in r for r in alarm["reasons"]))

    def test_server_state_tracks_time_sync_and_overcurrent_alerts(self) -> None:
        """Starea dashboard-ului păstrează timestamp-ul sincronizării și alertele de depășire prag."""
        cfg = SerialConnectionConfig(port="COM5")
        state = MultiDeviceDashboardState(config=cfg, csv_path="dummy.csv", db_writer=None)
        synced_ts = trigger_manual_time_sync(state)
        self.assertTrue(state.force_time_sync)
        self.assertEqual(state.last_time_sync, synced_ts)

        over_meas = _make_sample_measurements(ia=1700.0)
        oc = evaluate_overcurrent_notification(over_meas, max_current_limit_a=1600.0, slave_id=2)
        snap = PxrSnapshot(
            slave_id=2,
            timestamp="2026-11-16 17:50:00",
            connection_desc="COM5 [Slave #2]",
            status_info={
                "Stare Principală Disjunctor": "Închis (Closed) [0x02]",
                "Stare Secundară Unitate PXR": "Alimentat / Normal [0x07]",
                "Cauză Stare / Eveniment": "Normal [0x0000]",
            },
            measurements=over_meas,
            energy_indicators=compute_energy_indicators(over_meas, nominal_current_in=1600.0),
            max_current_limit_a=1600.0,
            nominal_current_in_a=1600.0,
            time_synced_at="2026-11-16 17:50:00",
            overcurrent_alert=oc,
        )
        update_state_after_poll(
            state=state,
            chain_to_poll=[2],
            current_snapshots={2: snap},
            broken_at_id=None,
            now_str="2026-11-16 17:50:00",
            total_csv_rows=1,
            settings_cache={},
            events_cache={},
            session_events_per_id={},
            time_sync_cache={2: "2026-11-16 17:50:00"},
        )
        payload = state.to_json_dict()
        self.assertEqual(payload["last_time_sync"], "2026-11-16 17:50:00")
        self.assertEqual(len(payload["overcurrent_alerts"]), 1)
        self.assertEqual(payload["overcurrent_alerts"][0]["slave_id"], 2)
        self.assertTrue(payload["alarm_state"]["active"])

    def test_dashboard_template_has_dropdown_simple_mode_and_notifications(self) -> None:
        """Template-ul HTML conține dropdown pentru device-uri, toggle Simplu/Avansat și toast notificare."""
        with open(server.TEMPLATE_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="device-select"', html)
        self.assertIn('id="btn-mode-simple"', html)
        self.assertIn('id="btn-mode-advanced"', html)
        self.assertIn('id="overcurrent-toast"', html)
        self.assertIn('/api/sync-time', html)
        self.assertNotIn('id="view-averages"', html)


if __name__ == "__main__":
    unittest.main()
