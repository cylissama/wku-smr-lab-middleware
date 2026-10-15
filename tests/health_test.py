import asyncio
import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from common.log_schema import JsonLineFormatter, make_record
from fast_server import loggers
from fast_server import main as m
from fast_server.capture import CaptureMode
from fast_server.health import HealthRegistry, PathProbe, backoff_delay
from tcp_server import tcp_server as t


def fresh_health() -> None:
    m.health.components = HealthRegistry(list(m.health.components)).components


async def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


class HealthRegistryTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.log_event = patch.object(loggers, "log_event", MagicMock())
        self.mock_log_event = self.log_event.start()

    async def asyncTearDown(self):
        self.log_event.stop()

    async def test_announces_transitions_once(self):
        notify = AsyncMock()
        reg = HealthRegistry(["db"], notify=notify)

        await reg.down("db", "connection refused", retry_in=5)
        await reg.down("db", "connection refused", retry_in=5)
        await reg.ok("db")
        await reg.ok("db")

        self.assertEqual([c.args[1] for c in notify.await_args_list], ["error", "info"])
        self.assertIn("db down: connection refused", notify.await_args_list[0].args[0])
        self.assertIn("db recovered after", notify.await_args_list[1].args[0])

    async def test_overall_status(self):
        reg = HealthRegistry(["db", "mqtt"])
        self.assertEqual(reg.snapshot()["overall"], "starting")

        await reg.ok("db")
        await reg.ok("mqtt")
        self.assertEqual(reg.snapshot()["overall"], "ok")

        await reg.down("mqtt", "broker gone")
        snap = reg.snapshot()
        self.assertEqual(snap["overall"], "degraded")
        self.assertEqual(snap["components"]["mqtt"]["error"], "broker gone")

    async def test_describe_includes_retry(self):
        reg = HealthRegistry(["db"])
        await reg.down("db", "timeout", retry_in=30)
        self.assertRegex(reg.describe("db"), r"db down 0s: timeout \(retrying in \d+s\)")

    def test_backoff_is_capped(self):
        self.assertEqual([backoff_delay(n) for n in (1, 2, 3, 4, 5, 9)], [1, 2, 5, 10, 30, 30])

    async def test_path_probe_times_out_and_refuses_overlap(self):
        release = asyncio.Event()
        loop = asyncio.get_running_loop()
        probe = PathProbe(lambda: asyncio.run_coroutine_threadsafe(release.wait(), loop).result(), timeout=0.05)

        with self.assertRaises(TimeoutError):
            await probe.run()
        with self.assertRaisesRegex(TimeoutError, "previous check"):
            await probe.run()
        release.set()


class DegradedApiTests(unittest.TestCase):

    def setUp(self):
        self.saved_startup = list(m.app.router.on_startup)
        m.app.router.on_startup.clear()
        self.client = TestClient(m.app)
        self.saved_db = m.app.state.db
        m.app.state.db = None
        fresh_health()
        self.patches = [
            patch.object(loggers, "log_event", MagicMock()),
            patch.object(loggers, "log_system_logger", MagicMock()),
            patch("fast_server.main.broadcast_message", new_callable=AsyncMock),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        m.app.state.db = self.saved_db
        m.app.router.on_startup[:] = self.saved_startup
        fresh_health()
        m.capture.set(CaptureMode.IDLE)

    def test_db_routes_return_503_with_reason(self):
        for path in ("/sessions", "/session/labels", "/imu/x", "/camera/x", "/robot/x", "/backup",
                     "/session/start/x?session_label=y"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 503, path)
            body = resp.json()
            self.assertFalse(body["success"])
            self.assertIn("Database unavailable", body["error"])

    def test_routes_without_db_keep_working(self):
        self.assertEqual(self.client.get("/capture").status_code, 200)
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertIn("db", health.json()["components"])

    def test_session_status_falls_back_to_capture_state(self):
        m.capture.set(CaptureMode.RECORD, session_id=42)
        body = self.client.get("/session").json()
        self.assertTrue(body["degraded"])
        self.assertTrue(body["data"])
        self.assertEqual(body["id"], 42)

    def test_known_down_db_is_refused_even_with_a_pool(self):
        m.app.state.db = MagicMock()
        asyncio.run(m.health.down("db", "connection refused"))
        self.assertEqual(self.client.get("/sessions").status_code, 503)


class SupervisorTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        fresh_health()
        self.saved_db = m.app.state.db
        m.app.state.db = None
        m.pending_session_end = None
        self.patches = [
            patch.object(loggers, "log_event", MagicMock()),
            patch.object(loggers, "log_system_logger", MagicMock()),
            patch("fast_server.main.broadcast_message", new_callable=AsyncMock),
            patch("fast_server.main.push_capture_to_tcp", new_callable=AsyncMock),
            patch("fast_server.main.backoff_delay", return_value=0),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        m.app.state.db = self.saved_db
        m.pending_session_end = None
        fresh_health()
        m.capture.set(CaptureMode.IDLE)

    async def test_db_supervisor_retries_then_starts_workers(self):
        db = MagicMock()
        db.get_latest_session = AsyncMock(return_value=None)
        get_instance = AsyncMock(side_effect=[OSError("Connection refused"), TimeoutError(), db])

        with patch("fast_server.main.DatabaseSingleton.get_instance", get_instance), \
             patch("fast_server.main.start_background") as start_background, \
             patch("fast_server.main.run_forever", new=MagicMock()):
            await m.db_supervisor()

        self.assertIs(m.app.state.db, db)
        self.assertEqual(get_instance.await_count, 3)
        self.assertEqual(m.health.components["db"]["status"], "ok")
        self.assertEqual(start_background.call_count, 2)  # camera + imu workers

    async def test_mqtt_supervisor_retries_first_connect(self):
        client = MagicMock()
        client.is_connected = False
        attempts = []

        async def startup():
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("Connection refused")
            client.is_connected = True

        with patch.object(m.mqtt, "client", client), patch.object(m.mqtt, "mqtt_startup", side_effect=startup):
            task = asyncio.create_task(m.mqtt_supervisor())
            await wait_until(lambda: m.health.components["mqtt"]["status"] == "ok")
            task.cancel()

        self.assertEqual(len(attempts), 3)

    async def test_stop_session_with_db_down_closes_gate_and_defers_end(self):
        m.capture.set(CaptureMode.RECORD, session_id=5)

        with patch("fast_server.main.remove_managed_stacks", new_callable=AsyncMock, return_value={"edge": {"success": True}}), \
             patch("fast_server.main.drain_queues", new_callable=AsyncMock) as drain:
            result = await m.stop_session()

        self.assertTrue(result["success"])
        self.assertTrue(result["degraded"])
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)
        self.assertEqual(m.pending_session_end[0], 5)
        drain.assert_not_awaited()
        stopped_at = m.pending_session_end[1]

        db = MagicMock()
        db.end_session_at = AsyncMock()
        m.app.state.db = db
        await m.apply_pending_session_end()

        db.end_session_at.assert_awaited_once_with(5, stopped_at)
        self.assertIsNone(m.pending_session_end)

    async def test_pending_end_survives_a_failed_retry(self):
        m.pending_session_end = (7, 1000.0)
        db = MagicMock()
        db.end_session_at = AsyncMock(side_effect=OSError("still down"))
        m.app.state.db = db

        await m.apply_pending_session_end()
        self.assertEqual(m.pending_session_end, (7, 1000.0))

    async def test_restore_capture_keeps_monitor_started_during_outage(self):
        m.capture.set(CaptureMode.MONITOR)
        db = MagicMock()
        db.get_latest_session = AsyncMock(return_value=9)
        m.app.state.db = db

        await m.restore_capture()

        self.assertEqual(m.capture.mode, CaptureMode.MONITOR)


class BacklogTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        m.insert_failures.clear()
        self.patches = [
            patch.object(loggers, "log_event", MagicMock()),
            patch("fast_server.main.broadcast_message", new_callable=AsyncMock),
        ]
        for p in self.patches:
            p.start()
        self.broadcast = m.broadcast_message
        m.capture.set(CaptureMode.RECORD, session_id=3)

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        m.insert_failures.clear()
        m.capture.set(CaptureMode.IDLE)

    async def test_failures_reported_once_per_interval_then_recovery(self):
        batch = [{"session_id": 3}]
        failing = AsyncMock(side_effect=OSError("db down"))

        for _ in range(3):
            self.assertFalse(await m.flush_batch(batch, failing, "IMU", MagicMock(), MagicMock()))
        self.assertEqual(self.broadcast.await_count, 1)
        self.assertIn("IMU inserts failing", self.broadcast.await_args.args[1])

        self.assertTrue(await m.flush_batch(batch, AsyncMock(), "IMU", MagicMock(), MagicMock()))
        self.assertNotIn("IMU", m.insert_failures)
        self.assertTrue(any("recovered" in c.args[1] for c in self.broadcast.await_args_list))

    def test_trim_backlog_drops_oldest(self):
        batch = list(range(10))
        with patch("fast_server.main.MAX_BACKLOG_ROWS", 4):
            m.trim_backlog(batch, "IMU", MagicMock())
        self.assertEqual(batch, [6, 7, 8, 9])
        self.assertEqual(m.insert_failures["IMU"]["dropped"], 6)


class QuietPollFilterTests(unittest.TestCase):

    def record(self, method, path, status):
        return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                 ("1.2.3.4:5", method, path, "1.1", status), None)

    def test_drops_only_successful_poll_gets(self):
        f = m.QuietPollFilter()
        self.assertFalse(f.filter(self.record("GET", "/health", 200)))
        self.assertFalse(f.filter(self.record("GET", "/devices?x=1", 200)))
        self.assertTrue(f.filter(self.record("GET", "/health", 503)))
        self.assertTrue(f.filter(self.record("GET", "/sessions", 200)))
        self.assertTrue(f.filter(self.record("POST", "/listen/start", 200)))


class LogRecordTests(unittest.TestCase):

    def test_json_line_formatter_emits_a_log_record(self):
        record = logging.LogRecord("system_logger_x", logging.ERROR, __file__, 1, "db down", None, None)
        record.smr_logger = "system"
        record.category = "health"
        record.important = True
        record.context = {"component": "db"}

        data = json.loads(JsonLineFormatter().format(record))

        self.assertEqual((data["level"], data["level_name"], data["logger"]), (40, "ERROR", "system"))
        self.assertEqual((data["category"], data["important"], data["context"]), ("health", True, {"component": "db"}))
        self.assertIsNone(data["priority"])
        self.assertTrue(data["ts"].endswith("Z"))

    def test_unknown_category_becomes_other(self):
        self.assertEqual(make_record("x", category="nope")["category"], "other")

    def test_unwritable_log_dir_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "not-a-dir"
            blocker.write_text("")
            handler = loggers.NonBlockingFileHandler(blocker / "sub" / "x.log")
            handler.setFormatter(loggers.formatter)
            logger = logging.getLogger("health_test_unwritable")
            logger.addHandler(handler)
            logger.propagate = False

            with patch.object(loggers, "_status_logger", MagicMock()):
                logger.error("hello")
                loggers._writer.flush()
                deadline = time.monotonic() + 2
                while loggers.file_logging_status()["ok"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertFalse(loggers.file_logging_status()["ok"])

                good = loggers.NonBlockingFileHandler(Path(tmp) / "ok.log")
                good.setFormatter(loggers.formatter)
                logger.addHandler(good)
                logger.removeHandler(handler)
                logger.error("again")
                deadline = time.monotonic() + 2
                while not loggers.file_logging_status()["ok"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(loggers.file_logging_status()["ok"])
                self.assertIn("again", (Path(tmp) / "ok.log").read_text())


class TcpDbTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.saved = (t.db, t.db_ready, dict(t.db_status))
        t.db = None
        t.db_ready = asyncio.Event()
        self.patches = [
            patch.object(t.loggers, "log_event", MagicMock()),
            patch("tcp_server.tcp_server.backoff_delay", return_value=0),
            patch("tcp_server.tcp_server.HEALTH_INTERVAL", 0.01),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        t.db, t.db_ready, status = self.saved
        t.db_status.clear()
        t.db_status.update(status)

    async def test_db_monitor_retries_and_reports(self):
        db = MagicMock()
        db.pool.fetchval = AsyncMock(return_value=1)
        get_instance = AsyncMock(side_effect=[OSError("Connection refused"), db])

        with patch("tcp_server.tcp_server.DatabaseSingleton.get_instance", get_instance):
            task = asyncio.create_task(t.db_monitor())
            await asyncio.wait_for(t.db_ready.wait(), 2)
            task.cancel()

        self.assertIs(t.db, db)
        self.assertEqual(t.db_status["status"], "ok")

    async def test_queue_status_reports_db(self):
        t.set_db_status(False, "OSError: Connection refused")
        resp = await t.queue_status(None)
        body = json.loads(resp.body)
        self.assertEqual(body["db"]["status"], "down")
        self.assertIn("Connection refused", body["db"]["error"])


if __name__ == "__main__":
    unittest.main()
