import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import fast_server.main as m
from fast_server.capture import CaptureMode


class SummarizeEdgeTests(unittest.TestCase):

    def test_waiting_until_every_device_is_running(self):
        summary = m.summarize_edge([
            {"key": "imu/106", "state": "running", "since": 105.0},
            {"key": "imu/107", "state": "deploying"},
        ], started=100.0)

        self.assertEqual(summary["state"], "waiting")
        self.assertEqual(summary["waiting_for"], ["imu/107"])
        self.assertIsNone(summary["ready_at"])

    def test_ready_at_is_when_the_last_device_turned_healthy(self):
        summary = m.summarize_edge([
            {"key": "imu/106", "state": "running", "since": 105.0},
            {"key": "camera/113_cam1", "state": "running", "since": 109.5},
        ], started=100.0)

        self.assertEqual(summary["state"], "ready")
        self.assertEqual((summary["ready_at"], summary["last"]), (109.5, "camera/113_cam1"))

    def test_devices_already_healthy_count_from_the_start(self):
        # Monitoring -> recording without a redeploy: containers predate the start
        summary = m.summarize_edge([{"key": "imu/106", "state": "running", "since": 50.0}], started=100.0)
        self.assertEqual(summary["ready_at"], 100.0)

    def test_unplaceable_device_does_not_hold_up_readiness(self):
        summary = m.summarize_edge([
            {"key": "imu/106", "state": "running", "since": 103.0},
            {"key": "imu/111", "state": "unavailable", "error": "no suitable node"},
        ], started=100.0)

        self.assertEqual(summary["state"], "ready")
        self.assertEqual(summary["unavailable"], ["imu/111"])


class DeviceSwarmStateTests(unittest.TestCase):

    def test_matches_service_and_passes_since(self):
        status = {"success": True, "state": "running",
                  "services": [{"name": "edge_imu-106", "state": "running", "since": 5.0, "error": None}]}
        self.assertEqual(m.device_swarm_state(status, "imu-106"), {"state": "running", "since": 5.0, "error": None})
        self.assertEqual(m.device_swarm_state(status, "imu-107"), {"state": "not_deployed"})

    def test_removing_and_unreachable(self):
        self.assertEqual(m.device_swarm_state({"success": True, "state": "removing"}, "imu-106"), {"state": "removing"})
        self.assertEqual(m.device_swarm_state({"success": False}, "imu-106"), {"state": "unknown"})


class EdgeReadyMonitorTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.states = AsyncMock(return_value=[{"key": "imu/106", "state": "deploying"}])
        self.patches = [
            patch("fast_server.main.EDGE_READY_POLL_S", 0),
            patch("fast_server.main.session_lock", asyncio.Lock()),
            patch("fast_server.main.deploy_started_at", None),
            patch("fast_server.main.edge_ready", {"state": "idle"}),
            patch("fast_server.main.load_device_catalog", AsyncMock(return_value=[{"key": "imu/106"}])),
            patch("fast_server.main.edge_device_states", self.states),
            patch("fast_server.main.broadcast_message", new_callable=AsyncMock),
            patch.object(m.loggers, "log_event", MagicMock()),
        ]
        for p in self.patches:
            p.start()
        m.capture.set(CaptureMode.RECORD, session_id=3)
        self.task = asyncio.create_task(m.edge_ready_monitor())

    async def asyncTearDown(self):
        self.task.cancel()
        for p in self.patches:
            p.stop()
        m.capture.set(CaptureMode.IDLE)

    async def spin(self, n=20):
        for _ in range(n):
            await asyncio.sleep(0)

    def announcements(self):
        return [c for c in m.broadcast_message.await_args_list if "Edge ready" in c.args[1]]

    async def test_announces_once_when_everything_is_healthy(self):
        self.states.return_value = [{"key": "imu/106", "state": "deploying"}]
        await self.spin()
        self.assertEqual(m.edge_ready["state"], "waiting")
        self.assertEqual(self.announcements(), [])

        self.states.return_value = [{"key": "imu/106", "state": "running", "since": 9e12}]
        await self.spin()

        self.assertEqual(m.edge_ready["state"], "ready")
        self.assertEqual(len(self.announcements()), 1)
        self.assertIn("the robot can start", self.announcements()[0].args[1])

    async def test_nothing_is_judged_while_a_start_holds_the_lock(self):
        await self.spin()   # first passes see the default: still deploying
        async with m.session_lock:
            await self.spin(3)
            self.states.reset_mock()
            # Old containers look healthy while the redeploy is still in flight
            self.states.return_value = [{"key": "imu/106", "state": "running", "since": 1.0}]
            await self.spin()
            self.assertEqual(m.edge_ready["state"], "busy")
            self.states.assert_not_awaited()
            self.assertEqual(self.announcements(), [])

        await self.spin()
        self.assertEqual(len(self.announcements()), 1)

    async def test_a_capture_change_starts_a_new_period(self):
        self.states.return_value = [{"key": "imu/106", "state": "running", "since": 1.0}]
        await self.spin()
        self.assertEqual(len(self.announcements()), 1)

        m.capture.set(CaptureMode.MONITOR)
        await self.spin()
        self.assertEqual(len(self.announcements()), 2)

    async def test_no_edge_devices_selected_is_ready_without_an_announcement(self):
        self.states.return_value = []
        await self.spin()
        self.assertEqual(m.edge_ready["state"], "ready")
        self.assertEqual(self.announcements(), [])

    async def test_idle_resets(self):
        m.capture.set(CaptureMode.IDLE)
        await self.spin()
        self.states.reset_mock()
        await self.spin()
        self.assertEqual(m.edge_ready, {"state": "idle"})
        self.states.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
