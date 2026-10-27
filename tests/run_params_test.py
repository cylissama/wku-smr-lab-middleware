import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from fast_server import main as m
from fast_server import run_params
from fast_server.capture import CaptureMode


class ParseTests(unittest.TestCase):

    def test_int_in_bounds(self):
        self.assertEqual(run_params.parse("IMU_SAMPLE_HZ", 200), 200)
        self.assertEqual(run_params.parse("IMU_SAMPLE_HZ", "50"), 50)   # env-file form

    def test_int_rejects_out_of_bounds_fractions_bools_and_junk(self):
        for bad in (0, 201, 99.5, True, "abc", None, float("nan")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                run_params.parse("IMU_SAMPLE_HZ", bad)

    def test_bool(self):
        self.assertIs(run_params.parse("IMU_PLC_TRIGGER_ON_RECORD", False), False)
        self.assertIs(run_params.parse("IMU_PLC_TRIGGER_ON_RECORD", "true"), True)
        with self.assertRaises(ValueError):
            run_params.parse("IMU_PLC_TRIGGER_ON_RECORD", "maybe")

    def test_env_value(self):
        self.assertEqual(run_params.env_value(True), "true")
        self.assertEqual(run_params.env_value(200), "200")

    def test_every_edge_param_is_overridable_in_stacks_yml(self):
        stacks = yaml.safe_load(Path("stack_controller/stacks.yml").read_text())["stacks"]
        self.assertLessEqual(set(run_params.EDGE_PARAMS), set(stacks["edge"]["env_overrides"]))


class StoreTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state" / "run_parameters.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_means_no_overrides(self):
        self.assertEqual(run_params.load(self.path), ({}, []))

    def test_round_trip(self):
        run_params.save(self.path, {"IMU_SAMPLE_HZ": 200, "IMU_PLC_TRIGGER_ON_RECORD": False})
        self.assertEqual(run_params.load(self.path), ({"IMU_SAMPLE_HZ": 200, "IMU_PLC_TRIGGER_ON_RECORD": False}, []))

    def test_drops_unknown_and_invalid_entries(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"IMU_SAMPLE_HZ": 5000, "GONE": 1, "IMU_PLC_MAX_RUN_S": 60}))

        values, problems = run_params.load(self.path)

        self.assertEqual(values, {"IMU_PLC_MAX_RUN_S": 60})
        self.assertEqual(len(problems), 2)

    def test_corrupt_file(self):
        self.path.parent.mkdir()
        self.path.write_text("{not json")

        values, problems = run_params.load(self.path)

        self.assertEqual(values, {})
        self.assertEqual(len(problems), 1)


class ParametersApiTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.deploys = []

        async def fake_request(method, path, body=None):
            if path.endswith("/env"):
                return {"success": True, "env": {"IMU_SAMPLE_HZ": "100", "IMU_PLC_MAX_RUN_S": "600"}}
            if path.endswith("/deploy"):
                self.deploys.append(body)
            return {"success": True}

        self.patches = [
            patch.object(m, "RUN_PARAMS_PATH", Path(self.tmp.name) / "run_parameters.json"),
            patch.object(m, "MANAGED_STACKS", ["edge"]),
            patch("fast_server.main.stack_controller_request", side_effect=fake_request),
            patch.multiple(m.loggers, cur_imu_logger=MagicMock(), cur_camera_logger=MagicMock(),
                           cur_robot_logger=MagicMock(), create_loggers=MagicMock(),
                           log_system_logger=MagicMock(), log_event=MagicMock()),
            patch("fast_server.main.broadcast_message", new_callable=AsyncMock),
            patch("fast_server.main.push_capture_to_tcp", new_callable=AsyncMock),
        ]
        for p in self.patches:
            p.start()

        self.db = MagicMock()
        self.db.create_session = AsyncMock(return_value=31)
        m.app.state.db = self.db
        m.capture.set(CaptureMode.IDLE)
        m.deployed_env, m.run_overrides = None, {}

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        m.capture.set(CaptureMode.IDLE)
        m.deployed_env, m.run_overrides = None, {}
        self.tmp.cleanup()

    async def test_get_shows_defaults_and_overrides(self):
        m.run_overrides = {"IMU_SAMPLE_HZ": 200}

        result = await m.get_parameters()

        by_key = {p["key"]: p for p in result["data"]}
        self.assertEqual((by_key["IMU_SAMPLE_HZ"]["default"], by_key["IMU_SAMPLE_HZ"]["value"]), (100, 200))
        self.assertTrue(by_key["IMU_SAMPLE_HZ"]["overridden"])
        self.assertEqual(by_key["IMU_PLC_MAX_RUN_S"]["default"], 600)
        self.assertTrue(result["editable"])

    async def test_put_saves_and_null_resets(self):
        self.assertTrue((await m.put_parameters(m.RunParamsUpdate(values={"IMU_SAMPLE_HZ": 200})))["success"])
        self.assertEqual(run_params.load(m.RUN_PARAMS_PATH)[0], {"IMU_SAMPLE_HZ": 200})

        await m.put_parameters(m.RunParamsUpdate(values={"IMU_SAMPLE_HZ": None}))

        self.assertEqual(m.run_overrides, {})
        self.assertEqual(self.deploys, [])          # idle: applies on the next deploy

    async def test_put_rejects_bad_values_without_changing_anything(self):
        result = await m.put_parameters(m.RunParamsUpdate(values={"IMU_SAMPLE_HZ": 5000, "IMU_PLC_MAX_RUN_S": 60}))

        self.assertFalse(result["success"])
        self.assertIn("IMU_SAMPLE_HZ", result["errors"])
        self.assertEqual(m.run_overrides, {})
        self.assertFalse(m.RUN_PARAMS_PATH.exists())

    async def test_put_rejects_unknown_key(self):
        result = await m.put_parameters(m.RunParamsUpdate(values={"DB_PASSWORD": "x"}))

        self.assertFalse(result["success"])
        self.assertIn("DB_PASSWORD", result["errors"])

    async def test_put_locked_while_recording_or_stopping(self):
        for mode in (CaptureMode.RECORD, CaptureMode.STOPPING):
            m.capture.set(mode, session_id=31)
            result = await m.put_parameters(m.RunParamsUpdate(values={"IMU_SAMPLE_HZ": 200}))
            self.assertFalse(result["success"])
            self.assertFalse((await m.get_parameters())["editable"])
        self.assertEqual(m.run_overrides, {})

    async def test_put_while_monitoring_redeploys_selection_with_new_env(self):
        m.capture.set(CaptureMode.MONITOR, devices=None)
        m.deployed_env = {"IMU_PLC_TRIGGER": "false"}

        result = await m.put_parameters(m.RunParamsUpdate(values={"IMU_SAMPLE_HZ": 50}))

        self.assertTrue(result["redeployed"])
        self.assertEqual(self.deploys, [{"env": {"IMU_SAMPLE_HZ": "50", "IMU_PLC_TRIGGER": "false"}}])
        self.assertEqual(m.deployed_env, {"IMU_SAMPLE_HZ": "50", "IMU_PLC_TRIGGER": "false"})

    async def test_put_while_monitoring_skips_redeploy_for_record_only_change(self):
        m.capture.set(CaptureMode.MONITOR, devices=None)
        m.deployed_env = {"IMU_PLC_TRIGGER": "false"}

        result = await m.put_parameters(m.RunParamsUpdate(values={"IMU_PLC_TRIGGER_ON_RECORD": False}))

        self.assertFalse(result["redeployed"])
        self.assertEqual(self.deploys, [])

    async def test_stack_env_per_mode(self):
        m.run_overrides = {"IMU_SAMPLE_HZ": 200, "IMU_PLC_TRIGGER_ON_RECORD": True}
        self.assertEqual(m.stack_env(CaptureMode.MONITOR), {"IMU_SAMPLE_HZ": "200", "IMU_PLC_TRIGGER": "false"})
        self.assertEqual(m.stack_env(CaptureMode.RECORD), {"IMU_SAMPLE_HZ": "200", "IMU_PLC_TRIGGER": "true"})

        m.run_overrides = {"IMU_PLC_TRIGGER_ON_RECORD": False}
        self.assertEqual(m.stack_env(CaptureMode.RECORD), {"IMU_PLC_TRIGGER": "false"})

    async def test_start_session_records_what_it_deploys(self):
        m.run_overrides = {"IMU_SAMPLE_HZ": 200}

        result = await m.start_session("lbl", session_label="Full System")

        self.assertTrue(result["success"])
        params = self.db.create_session.await_args.kwargs["parameters"]
        self.assertEqual((params["IMU_SAMPLE_HZ"], params["IMU_PLC_MAX_RUN_S"]), (200, 600))
        self.assertEqual(self.deploys, [{"env": {"IMU_SAMPLE_HZ": "200", "IMU_PLC_TRIGGER": "true"}}])


if __name__ == "__main__":
    unittest.main()
