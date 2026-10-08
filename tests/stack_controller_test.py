import os
import subprocess
import tempfile
import unittest
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
        (root / ".env").write_text("IMU_106_DEVICE_ID=106\n")
        (root / "stacks.yml").write_text(yaml.safe_dump({"stacks": {"edge": {
            "compose_file": str(root / "edge.yml"),
            "env_file": str(root / ".env"),
            "stack_name": "edge",
            "deploy_flags": ["--resolve-image", "never"],
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


if __name__ == "__main__":
    unittest.main()
