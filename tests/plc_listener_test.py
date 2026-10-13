import asyncio
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fast_server import main as m
from fast_server.capture import CaptureMode
from fast_server.plc_listener import FakePLC, FakeTag, PLCSignalWatcher


class ScriptedPLC:
    """
    A PLC connection that returns one scripted value per read, then repeats
    the last one. An Exception in the script is raised instead (a dropped
    connection), which makes the watcher open the next connection.
    """

    def __init__(self, tag, script, done: threading.Event):
        self.tag = tag
        self.script = list(script)
        self.done = done
        self.last = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *tags):
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            self.last = step
        else:
            self.done.set()
        if self.last is None:
            return FakeTag(self.tag, None, None, "Tag doesn't exist")
        return FakeTag(self.tag, self.last, "DINT", None)


def run_watcher(*connections, tag="Db_Stop") -> PLCSignalWatcher:
    """Runs a watcher over one scripted connection per argument, until the last script is used up."""
    done = threading.Event()
    pending = list(connections)

    def factory():
        script = pending.pop(0) if pending else []
        return ScriptedPLC(tag, script, done if not pending else threading.Event())

    watcher = PLCSignalWatcher(factory, tags=(tag,), poll_s=0.001, retry_delay_s=0.001)
    watcher.start()
    if not done.wait(5):
        watcher.close()
        raise AssertionError("scripted PLC never finished")
    watcher.close()
    return watcher


class PLCSignalWatcherTests(unittest.TestCase):

    def test_pulse_counts_once(self):
        watcher = run_watcher([0, 0, 1, 1, 1, 0, 0])
        self.assertEqual(watcher.count("Db_Stop"), 1)

    def test_each_pulse_counts(self):
        watcher = run_watcher([0, 1, 0, 1, 0, 1, 0])
        self.assertEqual(watcher.count("Db_Stop"), 3)

    def test_dint_values_count_as_on(self):
        # The lab PLC's tags are DINTs; anything non-zero is ON
        watcher = run_watcher([0, 5, 0])
        self.assertEqual(watcher.count("Db_Stop"), 1)

    def test_on_at_startup_is_not_counted(self):
        watcher = run_watcher([1, 1, 0])
        self.assertEqual(watcher.count("Db_Stop"), 0)

    def test_on_at_startup_counts_after_it_drops(self):
        watcher = run_watcher([1, 0, 1, 0])
        self.assertEqual(watcher.count("Db_Stop"), 1)

    def test_reconnect_does_not_fake_an_edge(self):
        # ON when the connection drops, still ON after reconnect: same pulse
        watcher = run_watcher([0, 1, ConnectionError("gone")], [1, 1, 0])
        self.assertEqual(watcher.count("Db_Stop"), 1)

    def test_pulse_rising_while_disconnected_is_seen_if_still_on(self):
        watcher = run_watcher([0, 0, ConnectionError("gone")], [1, 0])
        self.assertEqual(watcher.count("Db_Stop"), 1)

    def test_connection_error_reported(self):
        done = threading.Event()

        def factory():
            done.set()
            raise ConnectionRefusedError("refused")

        watcher = PLCSignalWatcher(factory, tags=("Db_Stop",), poll_s=0.001, retry_delay_s=0.001)
        watcher.start()
        done.wait(5)
        time.sleep(0.05)
        watcher.close()
        self.assertFalse(watcher.connected)
        self.assertIn("refused", watcher.last_error)

    def test_missing_tag_reported_separately(self):
        watcher = run_watcher([None, None])
        self.assertIsNone(watcher.last_error)
        self.assertIn("Tag doesn't exist", watcher.tag_errors)
        self.assertEqual(watcher.count("Db_Stop"), 0)

    def test_fake_plc_plays_one_pulse(self):
        plc = FakePLC(speed=1.0)
        with plc:
            plc._t0 -= 20.5
            self.assertEqual(plc.read("Db_Stop").value, 1)
            plc._t0 -= 1.0
            self.assertEqual(plc.read("Db_Stop").value, 0)


class PLCAutoStopTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.patches = [
            patch.multiple(m.loggers, cur_imu_logger=MagicMock(), cur_camera_logger=MagicMock(),
                           cur_robot_logger=MagicMock(), create_loggers=MagicMock(),
                           log_system_logger=MagicMock(), log_event=MagicMock()),
            patch("fast_server.main.broadcast_message", new_callable=AsyncMock),
            patch("fast_server.main.push_capture_to_tcp", new_callable=AsyncMock),
            patch("fast_server.main.drain_queues", new_callable=AsyncMock, return_value=(True, [])),
            patch("fast_server.main.try_backup", new_callable=AsyncMock, return_value={"success": True}),
            # A fresh lock per test: asyncio.Lock binds to the loop it first waits on
            patch("fast_server.main.session_lock", asyncio.Lock()),
            patch("fast_server.main.last_stop", None),
        ]
        for p in self.patches:
            p.start()

        self.remove = AsyncMock(return_value={"edge": {"success": True}})
        self.patches.append(patch("fast_server.main.remove_managed_stacks", self.remove))
        self.patches[-1].start()

        self.db = MagicMock()
        self.db.end_session = AsyncMock()
        m.app.state.db = self.db
        m.health.components["db"]["status"] = "ok"

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        m.capture.set(CaptureMode.IDLE)

    async def test_pulse_while_recording_stops_the_session(self):
        m.capture.set(CaptureMode.RECORD, session_id=7)

        result = await m.stop_session_from_plc()

        self.assertTrue(result["success"])
        self.db.end_session.assert_awaited_once()
        self.remove.assert_awaited_once()
        m.try_backup.assert_awaited_once()
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)
        self.assertEqual(m.last_stop[0], 7)
        self.assertIn("robot finished", m.last_stop[2])

    async def test_pulse_while_monitoring_is_ignored(self):
        m.capture.set(CaptureMode.MONITOR)

        self.assertIsNone(await m.stop_session_from_plc())

        self.remove.assert_not_awaited()
        self.db.end_session.assert_not_awaited()
        self.assertEqual(m.capture.mode, CaptureMode.MONITOR)

    async def test_pulse_while_idle_is_ignored(self):
        self.assertIsNone(await m.stop_session_from_plc())
        self.remove.assert_not_awaited()

    async def test_pulse_during_a_start_is_ignored(self):
        m.capture.set(CaptureMode.RECORD, session_id=7)
        async with m.session_lock:
            self.assertIsNone(await m.stop_session_from_plc())
        self.db.end_session.assert_not_awaited()
        self.assertEqual(m.capture.mode, CaptureMode.RECORD)

    async def test_pulse_during_a_button_stop_gives_one_stop(self):
        m.capture.set(CaptureMode.RECORD, session_id=7)
        release = asyncio.Event()

        async def slow_remove():
            await release.wait()
            return {"edge": {"success": True}}

        self.remove.side_effect = slow_remove

        button = asyncio.create_task(m.stop_session())
        await asyncio.sleep(0)   # button takes the lock, waits in remove
        plc_result = await m.stop_session_from_plc()
        release.set()
        button_result = await button

        self.assertIsNone(plc_result)
        self.assertTrue(button_result["success"])
        self.db.end_session.assert_awaited_once()
        m.try_backup.assert_awaited_once()

    async def test_button_right_after_plc_stop_says_already_stopped(self):
        m.capture.set(CaptureMode.RECORD, session_id=7)
        await m.stop_session_from_plc()

        result = await m.stop_session()

        self.assertTrue(result["success"])
        self.assertTrue(result["already_stopped"])
        self.assertIn("Session 7 was already stopped", result["message"])
        self.db.end_session.assert_awaited_once()
        self.remove.assert_awaited_once()

    async def test_button_stop_still_works_normally(self):
        m.capture.set(CaptureMode.RECORD, session_id=8)

        result = await m.stop_session()

        self.assertTrue(result["success"])
        self.assertNotIn("already_stopped", result)
        self.db.end_session.assert_awaited_once()

    async def test_supervisor_stops_on_a_new_pulse(self):
        m.capture.set(CaptureMode.RECORD, session_id=9)
        watcher = MagicMock()
        counts = iter([0, 0, 1])
        watcher.count.side_effect = lambda tag: next(counts, 1)

        with patch("fast_server.main.plc_watcher", watcher), \
             patch("fast_server.main.stop_session_from_plc", new_callable=AsyncMock) as stop:
            task = asyncio.create_task(m.plc_supervisor())
            for _ in range(50):
                if stop.await_count:
                    break
                await asyncio.sleep(0.05)
            task.cancel()

        stop.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
