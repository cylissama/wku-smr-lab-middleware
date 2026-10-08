import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from db.database import SessionNotStarted
from fast_server import main as m
from fast_server.capture import CaptureMode, CaptureState, LiveSampler, split_current

IMU_PAYLOAD = b"1, 1700779200.1, 1700779200.2, 0.1, 0.2, 0.3, 4, 5, 6, 7, 8, 9, 10, 20, 30"
CAMERA_PAYLOAD = b"1, 1700779200.1, 1700779200.2, 3, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6"


def drain(queue: asyncio.Queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


class CaptureStateTests(unittest.TestCase):

    def test_idle_accepts_and_stores_nothing(self):
        state = CaptureState()
        self.assertFalse(state.is_listening())
        self.assertFalse(state.accepts("imu", "106"))
        self.assertFalse(state.should_store())

    def test_monitor_accepts_but_does_not_store(self):
        state = CaptureState()
        state.set(CaptureMode.MONITOR)
        self.assertTrue(state.accepts("imu", "106"))
        self.assertFalse(state.should_store())

    def test_record_accepts_and_stores(self):
        state = CaptureState()
        state.set(CaptureMode.RECORD, session_id=7)
        self.assertTrue(state.accepts("camera", "front"))
        self.assertTrue(state.should_store())

    def test_stopping_accepts_nothing(self):
        state = CaptureState()
        state.set(CaptureMode.STOPPING, session_id=7)
        self.assertFalse(state.accepts("imu", "106"))
        self.assertFalse(state.should_store())

    def test_device_selection_filters(self):
        state = CaptureState()
        state.set(CaptureMode.RECORD, session_id=7, devices={"imu/106", "robot/main"})
        self.assertTrue(state.accepts("imu", "106"))
        self.assertTrue(state.accepts("robot", "main"))
        self.assertFalse(state.accepts("imu", "107"))
        self.assertFalse(state.accepts("camera", "front"))

    def test_is_current_only_for_matching_session_while_recording_or_stopping(self):
        state = CaptureState()
        state.set(CaptureMode.RECORD, session_id=7)
        self.assertTrue(state.is_current({"session_id": 7}))
        self.assertFalse(state.is_current({"session_id": 6}))
        self.assertFalse(state.is_current({}))

        state.set(CaptureMode.STOPPING, session_id=7)
        self.assertTrue(state.is_current({"session_id": 7}))

        state.set(CaptureMode.IDLE)
        self.assertFalse(state.is_current({"session_id": 7}))

    def test_split_current(self):
        state = CaptureState()
        state.set(CaptureMode.RECORD, session_id=2)
        current, stale = split_current(state, [{"session_id": 1}, {"session_id": 2}, {"session_id": 2}])
        self.assertEqual(len(current), 2)
        self.assertEqual(len(stale), 1)

    def test_set_always_increases_version(self):
        state = CaptureState()
        state.set(CaptureMode.RECORD, session_id=1)
        first = state.version
        state.set(CaptureMode.IDLE)
        self.assertGreater(state.version, first)

    def test_apply_round_trip_and_ignores_stale_or_repeated(self):
        source = CaptureState()
        source.set(CaptureMode.RECORD, session_id=3, devices={"imu/106"})
        old = source.to_dict()
        source.set(CaptureMode.STOPPING, session_id=3)
        new = source.to_dict()

        copy = CaptureState()
        self.assertTrue(copy.apply(new))
        self.assertEqual(copy.mode, CaptureMode.STOPPING)
        self.assertEqual(copy.session_id, 3)
        self.assertIsNone(copy.devices)

        self.assertFalse(copy.apply(old))   # older version
        self.assertFalse(copy.apply(new))   # same version
        self.assertEqual(copy.mode, CaptureMode.STOPPING)

    def test_apply_restores_device_set(self):
        source = CaptureState()
        source.set(CaptureMode.RECORD, session_id=3, devices={"imu/106", "robot/main"})
        copy = CaptureState()
        copy.apply(source.to_dict())
        self.assertEqual(copy.devices, {"imu/106", "robot/main"})


class LiveSamplerTests(unittest.TestCase):

    def test_first_message_sampled_then_throttled(self):
        s = LiveSampler(interval_s=1.0)
        self.assertEqual(s.tick("imu/106", now=10.0), 0.0)
        self.assertIsNone(s.tick("imu/106", now=10.5))
        self.assertIsNone(s.tick("imu/106", now=10.9))

    def test_rate_counts_messages_since_last_sample(self):
        s = LiveSampler(interval_s=1.0)
        s.tick("imu/106", now=10.0)
        for i in range(1, 100):
            self.assertIsNone(s.tick("imu/106", now=10.0 + i * 0.01))
        self.assertAlmostEqual(s.tick("imu/106", now=12.0), 100 / 2.0)

    def test_activity_never_seen(self):
        self.assertEqual(LiveSampler().activity("imu/106", now=5.0),
                         {"receiving": False, "rate": None, "last_seen_s": None})

    def test_activity_receiving_then_stale(self):
        s = LiveSampler(interval_s=1.0)
        s.tick("imu/106", now=10.0)
        self.assertEqual(s.activity("imu/106", timeout_s=3, now=10.5),
                         {"receiving": True, "rate": None, "last_seen_s": 0.5})   # no rate after one sample

        for i in range(1, 101):
            s.tick("imu/106", now=10.0 + i * 0.01)                              # 100 msgs over 1 s
        live = s.activity("imu/106", timeout_s=3, now=11.2)
        self.assertTrue(live["receiving"])
        self.assertEqual(live["rate"], 100.0)

        stale = s.activity("imu/106", timeout_s=3, now=15.0)
        self.assertEqual(stale, {"receiving": False, "rate": None, "last_seen_s": 4.0})   # last tick at 11.0

    def test_describe_rate(self):
        self.assertEqual(LiveSampler.describe_rate(0.0), "first sample")
        self.assertEqual(LiveSampler.describe_rate(99.6), "100 msg/s")

    def test_devices_throttled_independently(self):
        s = LiveSampler(interval_s=1.0)
        s.tick("imu/106", now=10.0)
        self.assertEqual(s.tick("imu/107", now=10.1), 0.0)


class HandlerGateTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        drain(m.imu_queue)
        drain(m.camera_queue)
        self.loggers = patch.multiple(m.loggers, cur_imu_logger=MagicMock(), cur_camera_logger=MagicMock())
        self.loggers.start()
        self.broadcast = patch("fast_server.main.broadcast_message", new_callable=AsyncMock)
        self.mock_broadcast = self.broadcast.start()
        m.live_sampler.reset()

    async def asyncTearDown(self):
        self.loggers.stop()
        self.broadcast.stop()
        m.capture.set(CaptureMode.IDLE)

    async def test_idle_drops_without_parsing(self):
        m.capture.set(CaptureMode.IDLE)

        await m.handle_sensors(None, "imu/106", IMU_PAYLOAD, None, None)
        await m.handle_camera(None, "camera/front", b"garbage", None, None)

        self.assertTrue(m.imu_queue.empty())
        self.assertTrue(m.camera_queue.empty())
        self.mock_broadcast.assert_not_called()   # garbage was never parsed

    async def test_record_queues_tagged_with_session(self):
        m.capture.set(CaptureMode.RECORD, session_id=42)

        await m.handle_sensors(None, "imu/106", IMU_PAYLOAD, None, None)
        await m.handle_camera(None, "camera/front", CAMERA_PAYLOAD, None, None)

        [imu] = drain(m.imu_queue)
        [cam] = drain(m.camera_queue)
        self.assertEqual(imu["device_label"], "106")
        self.assertEqual(imu["session_id"], 42)
        self.assertEqual(cam["device_label"], "front")
        self.assertEqual(cam["session_id"], 42)

    async def test_monitor_does_not_queue(self):
        m.capture.set(CaptureMode.MONITOR)

        await m.handle_sensors(None, "imu/106", IMU_PAYLOAD, None, None)

        self.assertTrue(m.imu_queue.empty())

    async def test_monitor_sends_throttled_live_samples(self):
        m.capture.set(CaptureMode.MONITOR)

        for _ in range(5):
            await m.handle_sensors(None, "imu/106", IMU_PAYLOAD, None, None)
        await m.handle_camera(None, "camera/front", CAMERA_PAYLOAD, None, None)

        live = [c.args for c in self.mock_broadcast.call_args_list if c.args[2] == "live"]
        self.assertEqual(len(live), 2)   # one per device, not one per message
        self.assertIs(live[0][0], m.imu_manager)
        self.assertIn("[live] imu/106", live[0][1])
        self.assertIn("accel (0.10, 0.20, 0.30)", live[0][1])
        self.assertIs(live[1][0], m.camera_manager)
        self.assertIn("[live] camera/front", live[1][1])

    async def test_record_also_sends_live_samples(self):
        m.capture.set(CaptureMode.RECORD, session_id=42)

        await m.handle_sensors(None, "imu/106", IMU_PAYLOAD, None, None)

        self.assertEqual(len(drain(m.imu_queue)), 1)
        self.assertTrue(any(c.args[2] == "live" for c in self.mock_broadcast.call_args_list))

    async def test_idle_sends_no_live_samples(self):
        await m.handle_sensors(None, "imu/106", IMU_PAYLOAD, None, None)
        self.mock_broadcast.assert_not_called()

    async def test_stopping_drops(self):
        m.capture.set(CaptureMode.STOPPING, session_id=42)

        await m.handle_sensors(None, "imu/106", IMU_PAYLOAD, None, None)

        self.assertTrue(m.imu_queue.empty())

    async def test_unselected_device_dropped(self):
        m.capture.set(CaptureMode.RECORD, session_id=42, devices={"imu/107"})

        await m.handle_sensors(None, "imu/106", IMU_PAYLOAD, None, None)
        await m.handle_sensors(None, "imu/107", IMU_PAYLOAD, None, None)

        [item] = drain(m.imu_queue)
        self.assertEqual(item["device_label"], "107")

    async def test_parse_error_reported_while_recording(self):
        m.capture.set(CaptureMode.RECORD, session_id=42)

        await m.handle_sensors(None, "imu/106", b"bad,fields", None, None)

        self.assertTrue(m.imu_queue.empty())
        texts = [c.args[1] for c in self.mock_broadcast.call_args_list]
        self.assertTrue(any("IMU parse error" in t for t in texts))


class FlushBatchTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.logger = MagicMock()
        self.broadcast = patch("fast_server.main.broadcast_message", new_callable=AsyncMock)
        self.broadcast.start()
        m.capture.set(CaptureMode.RECORD, session_id=5)

    async def asyncTearDown(self):
        self.broadcast.stop()
        m.capture.set(CaptureMode.IDLE)

    async def test_inserts_only_current_session_rows(self):
        insert = AsyncMock()
        batch = [{"session_id": 4}, {"session_id": 5}]

        done = await m.flush_batch(batch, insert, "IMU", self.logger, MagicMock())

        self.assertTrue(done)
        insert.assert_awaited_once_with([{"session_id": 5}])
        self.logger.warning.assert_called()

    async def test_all_stale_is_dropped_without_insert(self):
        insert = AsyncMock()
        m.capture.set(CaptureMode.IDLE)

        done = await m.flush_batch([{"session_id": 5}], insert, "IMU", self.logger, MagicMock())

        self.assertTrue(done)
        insert.assert_not_awaited()

    async def test_no_session_drops_batch(self):
        insert = AsyncMock(side_effect=SessionNotStarted("no session"))

        done = await m.flush_batch([{"session_id": 5}], insert, "IMU", self.logger, MagicMock())

        self.assertTrue(done)   # cleared, not retried into the next session

    async def test_db_error_keeps_batch_for_retry(self):
        insert = AsyncMock(side_effect=ConnectionError("db down"))

        done = await m.flush_batch([{"session_id": 5}], insert, "IMU", self.logger, MagicMock())

        self.assertFalse(done)


class SessionCaptureTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.patches = [
            patch.multiple(m.loggers, cur_imu_logger=MagicMock(), cur_camera_logger=MagicMock(),
                           cur_robot_logger=MagicMock(), create_loggers=MagicMock(),
                           log_system_logger=MagicMock()),
            patch("fast_server.main.broadcast_message", new_callable=AsyncMock),
            patch("fast_server.main.push_capture_to_tcp", new_callable=AsyncMock),
        ]
        for p in self.patches:
            p.start()

        self.db = MagicMock()
        self.db.create_session = AsyncMock(return_value=11)
        self.db.end_session = AsyncMock()
        m.app.state.db = self.db
        m.capture.set(CaptureMode.IDLE)

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        m.capture.set(CaptureMode.IDLE)

    async def test_start_session_opens_gate_before_deploy(self):
        modes_at_deploy = []

        async def deploy(plan=None):
            modes_at_deploy.append((m.capture.mode, m.capture.session_id))
            return {"edge": {"success": True}}

        with patch("fast_server.main.deploy_managed_stacks", side_effect=deploy):
            result = await m.start_session("lbl", session_label="Full System")

        self.assertTrue(result["success"])
        self.assertEqual(modes_at_deploy, [(CaptureMode.RECORD, 11)])
        self.assertEqual(m.capture.mode, CaptureMode.RECORD)

    async def test_start_session_deploy_failure_closes_gate(self):
        with patch("fast_server.main.deploy_managed_stacks", new_callable=AsyncMock,
                   return_value={"edge": {"success": False, "error": "nope"}}):
            result = await m.start_session("lbl", session_label="Full System")

        self.assertFalse(result["success"])
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)
        self.db.end_session.assert_awaited_once()

    async def test_start_session_db_error_leaves_gate_closed(self):
        self.db.create_session = AsyncMock(side_effect=RuntimeError("db down"))

        result = await m.start_session("lbl", session_label="Full System")

        self.assertFalse(result["success"])
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)

    async def test_failed_start_keeps_existing_recording_open(self):
        m.capture.set(CaptureMode.RECORD, session_id=10)
        self.db.create_session = AsyncMock(side_effect=RuntimeError("label already exists"))

        result = await m.start_session("lbl", session_label="Full System")

        self.assertFalse(result["success"])
        self.assertEqual((m.capture.mode, m.capture.session_id), (CaptureMode.RECORD, 10))

    async def test_stop_session_closes_gate_before_removing_stacks(self):
        m.capture.set(CaptureMode.RECORD, session_id=11)
        seen = {}

        async def remove():
            seen["remove"] = (m.capture.mode, m.capture.session_id)
            return {"edge": {"success": True}}

        async def drain_queues():
            seen["drain"] = (m.capture.mode, m.capture.session_id)
            return True, []

        with patch("fast_server.main.remove_managed_stacks", side_effect=remove), \
             patch("fast_server.main.drain_queues", side_effect=drain_queues), \
             patch("fast_server.main.try_backup", new_callable=AsyncMock, return_value={"success": True}):
            result = await m.stop_session()

        self.assertTrue(result["success"])
        # session_id kept while STOPPING so workers can still flush its rows
        self.assertEqual(seen["remove"], (CaptureMode.STOPPING, 11))
        self.assertEqual(seen["drain"], (CaptureMode.STOPPING, 11))
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)

    async def test_stop_session_failure_still_closes_gate(self):
        m.capture.set(CaptureMode.RECORD, session_id=11)
        self.db.end_session = AsyncMock(side_effect=SessionNotStarted("none"))

        with patch("fast_server.main.remove_managed_stacks", new_callable=AsyncMock, return_value={}), \
             patch("fast_server.main.drain_queues", new_callable=AsyncMock, return_value=(True, [])):
            result = await m.stop_session()

        self.assertFalse(result["success"])
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)

    async def test_listen_start_deploys_and_monitors(self):
        with patch("fast_server.main.deploy_managed_stacks", new_callable=AsyncMock,
                   return_value={"edge": {"success": True}}) as deploy:
            result = await m.start_listening()

        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "monitor")
        deploy.assert_awaited_once()
        self.assertEqual(m.capture.mode, CaptureMode.MONITOR)

    async def test_listen_start_deploy_failure_returns_to_idle(self):
        with patch("fast_server.main.deploy_managed_stacks", new_callable=AsyncMock,
                   return_value={"edge": {"success": False, "error": "nope"}}):
            result = await m.start_listening()

        self.assertFalse(result["success"])
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)

    async def test_listen_start_refused_while_recording(self):
        m.capture.set(CaptureMode.RECORD, session_id=11)

        with patch("fast_server.main.deploy_managed_stacks", new_callable=AsyncMock) as deploy:
            result = await m.start_listening()

        self.assertFalse(result["success"])
        deploy.assert_not_awaited()
        self.assertEqual(m.capture.mode, CaptureMode.RECORD)

    async def test_listen_stop_removes_stacks(self):
        m.capture.set(CaptureMode.MONITOR)

        with patch("fast_server.main.remove_managed_stacks", new_callable=AsyncMock,
                   return_value={"edge": {"success": True}}) as remove:
            result = await m.stop_listening()

        self.assertTrue(result["success"])
        remove.assert_awaited_once()
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)

    async def test_listen_stop_refused_while_recording(self):
        m.capture.set(CaptureMode.RECORD, session_id=11)

        with patch("fast_server.main.remove_managed_stacks", new_callable=AsyncMock) as remove:
            result = await m.stop_listening()

        self.assertFalse(result["success"])
        remove.assert_not_awaited()
        self.assertEqual(m.capture.mode, CaptureMode.RECORD)

    async def test_start_session_from_monitor_skips_redeploy(self):
        m.capture.set(CaptureMode.MONITOR)

        with patch("fast_server.main.deploy_managed_stacks", new_callable=AsyncMock) as deploy:
            result = await m.start_session("lbl", session_label="Full System")

        self.assertTrue(result["success"])
        deploy.assert_not_awaited()
        self.assertEqual((m.capture.mode, m.capture.session_id), (CaptureMode.RECORD, 11))

    async def test_failed_start_from_monitor_keeps_monitoring(self):
        m.capture.set(CaptureMode.MONITOR)
        self.db.create_session = AsyncMock(side_effect=RuntimeError("db down"))

        result = await m.start_session("lbl", session_label="Full System")

        self.assertFalse(result["success"])
        self.assertEqual(m.capture.mode, CaptureMode.MONITOR)

    async def test_restore_capture_resumes_open_session(self):
        self.db.get_latest_session = AsyncMock(return_value=99)

        await m.restore_capture()

        self.assertEqual(m.capture.mode, CaptureMode.RECORD)
        self.assertEqual(m.capture.session_id, 99)

    async def test_restore_capture_idle_without_session(self):
        self.db.get_latest_session = AsyncMock(return_value=None)
        m.capture.set(CaptureMode.RECORD, session_id=1)

        await m.restore_capture()

        self.assertEqual(m.capture.mode, CaptureMode.IDLE)

    async def test_get_capture_reports_state(self):
        m.capture.set(CaptureMode.RECORD, session_id=11)

        state = await m.get_capture()

        self.assertEqual(state["mode"], "record")
        self.assertEqual(state["session_id"], 11)



EDGE_SERVICES = {"success": True, "services": [
    {"service": "imu-106", "category": "imu", "device_label": "106"},
    {"service": "imu-107", "category": "imu", "device_label": "107"},
    {"service": "camera-front", "category": "camera", "device_label": "113"},
    {"service": "unlabelled", "category": None, "device_label": None},
]}


class DeviceSelectionTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.calls = []
        self.status = {"success": True, "state": "running", "services": [
            {"name": "edge_imu-106", "state": "running"},
            {"name": "edge_camera-front", "state": "deploying"},
        ]}

        async def fake_request(method, path, body=None):
            self.calls.append((method, path, body))
            if path.endswith("/services"):
                return EDGE_SERVICES
            if path.endswith("/status"):
                return self.status
            return {"success": True}

        self.patches = [
            patch.object(m, "MANAGED_STACKS", ["edge"]),
            patch("fast_server.main.stack_controller_request", side_effect=fake_request),
            patch.multiple(m.loggers, cur_imu_logger=MagicMock(), cur_camera_logger=MagicMock(),
                           cur_robot_logger=MagicMock(), create_loggers=MagicMock(),
                           log_system_logger=MagicMock()),
            patch("fast_server.main.broadcast_message", new_callable=AsyncMock),
            patch("fast_server.main.push_capture_to_tcp", new_callable=AsyncMock),
            patch("fast_server.main.get_robot_queue_status", new_callable=AsyncMock,
                  return_value={"empty": True, "connections": 1}),
        ]
        for p in self.patches:
            p.start()

        self.db = MagicMock()
        self.db.create_session = AsyncMock(return_value=21)
        self.db.end_session = AsyncMock()
        m.app.state.db = self.db
        m.capture.set(CaptureMode.IDLE)

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        m.capture.set(CaptureMode.IDLE)

    def posts(self):
        return [(path, body) for method, path, body in self.calls if method == "POST"]

    async def test_catalog_has_labelled_services_plus_robot(self):
        keys = [d["key"] for d in await m.load_device_catalog()]
        self.assertEqual(keys, ["imu/106", "imu/107", "camera/113", "robot/main"])

    async def test_resolve_selection_builds_plan(self):
        selected, plan = await m.resolve_selection(["imu/107", "robot/main", "imu/106"])

        self.assertEqual(selected, {"imu/106", "imu/107", "robot/main"})
        self.assertEqual(plan, {"edge": ["imu-106", "imu-107"]})

    async def test_resolve_selection_none_means_everything(self):
        self.assertEqual(await m.resolve_selection(None), (None, None))
        self.assertEqual(self.calls, [])

    async def test_resolve_selection_rejects_unknown_and_empty(self):
        with self.assertRaisesRegex(ValueError, "imu/999"):
            await m.resolve_selection(["imu/106", "imu/999"])
        with self.assertRaises(ValueError):
            await m.resolve_selection([])

    async def test_robot_only_removes_edge_stack_instead_of_deploying(self):
        results = await m.deploy_managed_stacks({"edge": []})

        self.assertTrue(results["edge"]["success"])
        self.assertEqual(self.posts(), [("/stacks/edge/remove", None)])

    async def test_get_devices_reports_states(self):
        result = await m.get_devices()

        states = {d["key"]: d["state"] for d in result["data"]}
        self.assertEqual(states, {"imu/106": "running", "imu/107": "not_deployed",
                                  "camera/113": "deploying", "robot/main": "connected"})

    async def test_get_devices_reports_receiving(self):
        m.live_sampler.reset()
        m.live_sampler.tick("imu/106")
        robot_activity = {"receiving": True, "rate": 50.0, "last_seen_s": 0.2}

        with patch("fast_server.main.get_robot_queue_status", new_callable=AsyncMock,
                   return_value={"empty": True, "connections": 1, "activity": robot_activity}):
            result = await m.get_devices()
        m.live_sampler.reset()

        by_key = {d["key"]: d for d in result["data"]}
        self.assertTrue(by_key["imu/106"]["receiving"])
        self.assertFalse(by_key["imu/107"]["receiving"])
        self.assertIsNone(by_key["imu/107"]["last_seen_s"])
        self.assertEqual(by_key["robot/main"]["rate"], 50.0)

    async def test_get_devices_old_tcp_without_activity(self):
        result = await m.get_devices()   # robot status mock has no "activity" key

        robot = next(d for d in result["data"] if d["key"] == "robot/main")
        self.assertFalse(robot["receiving"])

    async def test_get_devices_unknown_when_stack_controller_down(self):
        self.status = {"success": False, "error": "unreachable"}

        result = await m.get_devices()

        self.assertEqual({d["state"] for d in result["data"] if d["stack"]}, {"unknown"})

    async def test_listen_start_with_selection(self):
        result = await m.start_listening(m.DeviceSelection(devices=["imu/106"]))

        self.assertTrue(result["success"])
        self.assertEqual(result["devices"], ["imu/106"])
        self.assertEqual(m.capture.devices, {"imu/106"})
        self.assertEqual(self.posts(), [("/stacks/edge/deploy", {"services": ["imu-106"]})])

    async def test_listen_start_bad_selection_changes_nothing(self):
        result = await m.start_listening(m.DeviceSelection(devices=["imu/999"]))

        self.assertFalse(result["success"])
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)
        self.assertEqual(self.posts(), [])

    async def test_start_session_stores_selection_and_deploys_it(self):
        result = await m.start_session("lbl", session_label="Full System", devices=["camera/113", "robot/main"])

        self.assertTrue(result["success"])
        self.assertEqual(self.db.create_session.await_args.kwargs["devices"], {"camera/113", "robot/main"})
        self.assertEqual(m.capture.devices, {"camera/113", "robot/main"})
        self.assertEqual(self.posts(), [("/stacks/edge/deploy", {"services": ["camera-front"]})])

    async def test_start_session_bad_selection_creates_no_session(self):
        result = await m.start_session("lbl", session_label="Full System", devices=["imu/999"])

        self.assertFalse(result["success"])
        self.db.create_session.assert_not_awaited()
        self.assertEqual(m.capture.mode, CaptureMode.IDLE)

    async def test_start_session_from_monitor_same_selection_skips_redeploy(self):
        m.capture.set(CaptureMode.MONITOR, devices={"imu/106"})

        await m.start_session("lbl", session_label="Full System", devices=["imu/106"])

        self.assertEqual(self.posts(), [])
        self.assertEqual((m.capture.mode, m.capture.devices), (CaptureMode.RECORD, {"imu/106"}))

    async def test_start_session_from_monitor_changed_selection_redeploys(self):
        m.capture.set(CaptureMode.MONITOR, devices={"imu/106"})

        await m.start_session("lbl", session_label="Full System", devices=["imu/106", "imu/107"])

        self.assertEqual(self.posts(), [("/stacks/edge/deploy", {"services": ["imu-106", "imu-107"]})])

    async def test_failed_start_from_monitor_restores_monitored_selection(self):
        m.capture.set(CaptureMode.MONITOR, devices={"imu/106"})
        self.db.create_session = AsyncMock(return_value=21)
        with patch("fast_server.main.deploy_managed_stacks", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            result = await m.start_session("lbl", session_label="Full System", devices=["imu/107"])

        self.assertFalse(result["success"])
        self.assertEqual((m.capture.mode, m.capture.devices), (CaptureMode.MONITOR, {"imu/106"}))

    async def test_restore_capture_uses_session_selection(self):
        self.db.get_latest_session = AsyncMock(return_value=21)
        self.db.get_session_devices = AsyncMock(return_value={"imu/106"})

        await m.restore_capture()

        self.assertEqual((m.capture.mode, m.capture.devices), (CaptureMode.RECORD, {"imu/106"}))

    async def test_restore_capture_fails_open_if_selection_unreadable(self):
        self.db.get_latest_session = AsyncMock(return_value=21)
        self.db.get_session_devices = AsyncMock(side_effect=RuntimeError("column missing"))

        await m.restore_capture()

        self.assertEqual((m.capture.mode, m.capture.devices), (CaptureMode.RECORD, None))


if __name__ == "__main__":
    unittest.main()
