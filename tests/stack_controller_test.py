import os
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from stack_controller import main as sc

COMPOSE = """\
services:
  imu-106:
    image: smart-mfg-imu:latest
    deploy:
      replicas: 1
      labels:
        smr.category: imu
        smr.device: "${IMU_106_DEVICE_ID}"
    environment:
      MQTT_TOPIC: imu/${IMU_106_DEVICE_ID}
  camera-front:
    image: camera-edge:latest
    deploy:
      labels:
        - smr.category=camera
        - smr.device=${CAMERA_FRONT_DEVICE_ID:-999}
  helper:
    image: busybox
networks:
  default:
    driver: overlay
"""


class InterpolateTests(unittest.TestCase):

    def test_forms(self):
        env = {"A": "1", "EMPTY": ""}
        self.assertEqual(sc.interpolate("x${A}y", env), "x1y")
        self.assertEqual(sc.interpolate("${MISSING}", env), "")
        self.assertEqual(sc.interpolate("${MISSING:-d}", env), "d")
        self.assertEqual(sc.interpolate("${EMPTY:-d}", env), "d")
        self.assertEqual(sc.interpolate("no vars", env), "no vars")


class StackControllerTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "edge.yml").write_text(COMPOSE)
        (root / ".env").write_text("IMU_106_DEVICE_ID=106\nIMU_PLC_TRIGGER=false\n")
        (root / "stacks.yml").write_text(yaml.safe_dump({"stacks": {"edge": {
            "compose_file": str(root / "edge.yml"),
            "env_file": str(root / ".env"),
            "stack_name": "edge",
            "deploy_flags": ["--resolve-image", "never"],
            "env_overrides": ["IMU_PLC_TRIGGER"],
        }}}))

        self.env = patch.dict(os.environ, {"STACK_CONTROLLER_TOKEN": "t"})
        self.env.start()
        self.config = patch.object(sc, "STACKS_CONFIG_PATH", str(root / "stacks.yml"))
        self.config.start()
        self.client = TestClient(sc.app)
        self.headers = {"Authorization": "Bearer t"}

        self.deployed = []

        def fake_deploy(compose_file, stack_name, flags, stack_env):
            self.deployed.append({
                "path": compose_file,
                "compose": yaml.safe_load(Path(compose_file).read_text()),
                "flags": flags,
                "env": stack_env,
            })
            return subprocess.CompletedProcess([], 0, stdout="ok", stderr="")

        self.docker = patch.object(sc.docker_ops, "deploy_stack", side_effect=fake_deploy)
        self.docker.start()

    def tearDown(self):
        self.docker.stop()
        self.config.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_services_lists_labelled_devices(self):
        resp = self.client.get("/stacks/edge/services", headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["services"], [
            {"service": "imu-106", "category": "imu", "device_label": "106"},
            {"service": "camera-front", "category": "camera", "device_label": "999"},
            {"service": "helper", "category": None, "device_label": None},
        ])

    def test_services_requires_token(self):
        self.assertEqual(self.client.get("/stacks/edge/services").status_code, 401)

    def test_deploy_without_body_uses_whole_file(self):
        resp = self.client.post("/stacks/edge/deploy", headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        [call] = self.deployed
        self.assertTrue(call["path"].endswith("edge.yml"))
        self.assertNotIn("--prune", call["flags"])

    def test_deploy_selected_services_filters_and_prunes(self):
        resp = self.client.post("/stacks/edge/deploy", headers=self.headers, json={"services": ["imu-106"]})

        self.assertEqual(resp.status_code, 200)
        [call] = self.deployed
        self.assertEqual(list(call["compose"]["services"]), ["imu-106"])
        self.assertIn("networks", call["compose"])                 # other keys kept
        # ${VAR}s left for docker stack deploy to interpolate
        self.assertEqual(call["compose"]["services"]["imu-106"]["environment"]["MQTT_TOPIC"],
                         "imu/${IMU_106_DEVICE_ID}")
        self.assertEqual(call["flags"], ["--resolve-image", "never", "--prune"])
        self.assertFalse(Path(call["path"]).exists())               # temp file cleaned up

    def test_deploy_unknown_service_rejected(self):
        resp = self.client.post("/stacks/edge/deploy", headers=self.headers, json={"services": ["imu-999"]})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.deployed, [])

    def test_deploy_empty_selection_rejected(self):
        resp = self.client.post("/stacks/edge/deploy", headers=self.headers, json={"services": []})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.deployed, [])

    def test_deploy_env_override_layered_over_env_file(self):
        resp = self.client.post("/stacks/edge/deploy", headers=self.headers,
                                json={"services": ["imu-106"], "env": {"IMU_PLC_TRIGGER": "true"}})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["env"], {"IMU_PLC_TRIGGER": "true"})
        [call] = self.deployed
        self.assertEqual(call["env"]["IMU_PLC_TRIGGER"], "true")
        self.assertEqual(call["env"]["IMU_106_DEVICE_ID"], "106")    # rest of env_file kept

    def test_deploy_without_override_uses_env_file(self):
        self.client.post("/stacks/edge/deploy", headers=self.headers)

        [call] = self.deployed
        self.assertEqual(call["env"]["IMU_PLC_TRIGGER"], "false")

    def test_env_returns_only_overridable_values(self):
        resp = self.client.get("/stacks/edge/env", headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["env"], {"IMU_PLC_TRIGGER": "false"})   # not IMU_106_DEVICE_ID

    def test_env_requires_token(self):
        self.assertEqual(self.client.get("/stacks/edge/env").status_code, 401)

    def test_deploy_refuses_unlisted_env_override(self):
        resp = self.client.post("/stacks/edge/deploy", headers=self.headers,
                                json={"env": {"MQTT_BROKER_IP": "10.0.0.1"}})

        self.assertEqual(resp.status_code, 400)
        self.assertIn("MQTT_BROKER_IP", resp.text)
        self.assertEqual(self.deployed, [])

    def test_temp_file_removed_when_deploy_fails(self):
        self.docker.stop()
        paths = []

        def failing(compose_file, *args):
            paths.append(compose_file)
            return subprocess.CompletedProcess([], 1, stdout="", stderr="boom")

        with patch.object(sc.docker_ops, "deploy_stack", side_effect=failing):
            resp = self.client.post("/stacks/edge/deploy", headers=self.headers, json={"services": ["imu-106"]})
        self.docker.start()

        self.assertEqual(resp.status_code, 500)
        self.assertFalse(Path(paths[0]).exists())


class RemoveWaitsForTeardownTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "edge.yml").write_text(COMPOSE)
        (root / "stacks.yml").write_text(yaml.safe_dump({"stacks": {"edge": {
            "compose_file": str(root / "edge.yml"), "stack_name": "edge"}}}))
        self.patches = [
            patch.dict(os.environ, {"STACK_CONTROLLER_TOKEN": "t"}),
            patch.object(sc, "STACKS_CONFIG_PATH", str(root / "stacks.yml")),
            patch.object(sc, "REMOVE_POLL_S", 0.01),
            patch.object(sc.docker_ops, "remove_stack",
                         return_value=subprocess.CompletedProcess([], 0, stdout="Removing service edge_imu-106", stderr="")),
        ]
        for p in self.patches:
            p.start()
        self.client = TestClient(sc.app)
        self.headers = {"Authorization": "Bearer t"}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_returns_once_the_containers_are_gone(self):
        polls = iter([["edge_imu-106.1@RPIIMUJ1"], ["edge_imu-106.1@RPIIMUJ1"], []])
        statuses = []

        def live_tasks(stack_name):
            # Status asked mid-teardown says "removing", not "not_deployed"
            statuses.append(self.client.get("/stacks/edge/status", headers=self.headers).json()["state"])
            return next(polls)

        with patch.object(sc.docker_ops, "live_tasks", side_effect=live_tasks) as live:
            resp = self.client.post("/stacks/edge/remove", headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["teardown_confirmed"])
        self.assertIsNone(resp.json()["still_running"])
        self.assertEqual(live.call_count, 3)
        self.assertEqual(statuses, ["removing"] * 3)
        self.assertNotIn("edge", sc._removing)

    def test_gives_up_at_the_deadline_and_says_what_is_still_up(self):
        with patch.object(sc, "REMOVE_WAIT_S", 0.05), \
             patch.object(sc.docker_ops, "live_tasks", return_value=["edge_imu-106.1@RPIIMUJ1"]):
            resp = self.client.post("/stacks/edge/remove", headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["teardown_confirmed"])
        self.assertEqual(resp.json()["still_running"], ["edge_imu-106.1@RPIIMUJ1"])

    def test_docker_unreachable_is_unconfirmed_not_an_error(self):
        with patch.object(sc.docker_ops, "live_tasks", side_effect=RuntimeError("no docker")):
            resp = self.client.post("/stacks/edge/remove", headers=self.headers)

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["teardown_confirmed"])

    def test_failed_rm_is_an_error_and_clears_removing(self):
        with patch.object(sc.docker_ops, "remove_stack",
                          return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="boom")):
            resp = self.client.post("/stacks/edge/remove", headers=self.headers)

        self.assertEqual(resp.status_code, 500)
        self.assertNotIn("edge", sc._removing)


class LiveTasksTests(unittest.TestCase):

    def test_only_containers_that_may_still_be_up_on_ready_nodes(self):
        nodes = [
            {"ID": "n1", "Status": {"State": "ready"}, "Description": {"Hostname": "RPIIMUJ1"}},
            {"ID": "n2", "Status": {"State": "down"}, "Description": {"Hostname": "RPI-IMU-BENCH"}},
        ]
        tasks = [
            {"ID": "a", "NodeID": "n1", "Annotations": {"Name": "edge_imu-106.1"}, "Status": {"State": "running"}},
            {"ID": "b", "NodeID": "n1", "Annotations": {"Name": "edge_imu-106.2"}, "Status": {"State": "shutdown"}},
            {"ID": "c", "NodeID": "n2", "Annotations": {"Name": "edge_imu-111.1"}, "Status": {"State": "running"}},
            {"ID": "d", "NodeID": "", "Status": {"State": "pending"}},
        ]
        client = unittest.mock.MagicMock()
        client.api.nodes.return_value = nodes
        client.api.tasks.return_value = tasks

        with patch.object(sc.docker_ops.docker, "from_env", return_value=client):
            self.assertEqual(sc.docker_ops.live_tasks("edge"), ["edge_imu-106.1@RPIIMUJ1"])

        client.api.tasks.assert_called_once_with(filters={"label": "com.docker.stack.namespace=edge"})


class StackStatusTests(unittest.TestCase):

    OLD_ENV = {"Image": "smart-mfg-imu:latest", "Env": ["IMU_PLC_TRIGGER=false"]}
    NEW_ENV = {"Image": "smart-mfg-imu:latest", "Env": ["IMU_PLC_TRIGGER=true"]}

    @staticmethod
    def task(spec, desired, state, ts="2026-11-02T19:54:14.123456789Z"):
        return {"DesiredState": desired, "Spec": {"ContainerSpec": spec},
                "Status": {"State": state, "Timestamp": ts}}

    def status(self, tasks, spec=NEW_ENV):
        service = unittest.mock.MagicMock()
        service.name = "edge_imu-106"
        service.attrs = {"Spec": {"Mode": {"Replicated": {"Replicas": 1}}, "TaskTemplate": {"ContainerSpec": spec}}}
        service.tasks.return_value = tasks
        client = unittest.mock.MagicMock()
        client.services.list.return_value = [service]
        with patch.object(sc.docker_ops.docker, "from_env", return_value=client):
            return sc.docker_ops.get_stack_status("edge")["services"][0]

    def test_old_task_still_running_during_a_redeploy_is_not_ready(self):
        # Swarm hasn't told the old task to stop yet, and the new one is starting
        svc = self.status([self.task(self.OLD_ENV, "running", "running"),
                           self.task(self.NEW_ENV, "running", "starting")])
        self.assertEqual((svc["state"], svc["running"], svc["since"]), ("deploying", 0, None))

    def test_old_task_shutting_down_is_not_ready(self):
        svc = self.status([self.task(self.NEW_ENV, "shutdown", "running")])
        self.assertEqual(svc["state"], "deploying")

    def test_healthy_current_task_is_running_since_its_timestamp(self):
        svc = self.status([self.task(self.OLD_ENV, "shutdown", "shutdown", "2026-11-02T19:50:00Z"),
                           self.task(self.NEW_ENV, "running", "running", "2026-11-02T19:54:14.123456789Z")])
        self.assertEqual((svc["state"], svc["running"]), ("running", 1))
        self.assertAlmostEqual(svc["since"], 1793649254.123456, places=5)

    def test_failed_task_with_nothing_running_is_an_error(self):
        svc = self.status([self.task(self.NEW_ENV, "shutdown", "failed"),
                           self.task(self.NEW_ENV, "running", "starting")])
        self.assertEqual(svc["state"], "error")


if __name__ == "__main__":
    unittest.main()
