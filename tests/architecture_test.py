import unittest
from pathlib import Path

import yaml

from architecture import sync

ROOT = Path(__file__).resolve().parent.parent


class GeneratedInventoryTest(unittest.TestCase):

    def test_generated_files_are_current(self):
        for name, text in sync.render().items():
            path = sync.OUT / name
            with self.subTest(file=name):
                self.assertTrue(path.exists(), f"{path} is missing: run python architecture/sync.py")
                self.assertEqual(path.read_text(), text,
                                 f"{path.relative_to(ROOT)} is out of date: run python architecture/sync.py")

    def test_local_compose_services_are_described(self):
        # docker-compose.yml and the edge stack are checked by render() above
        services = yaml.safe_load((ROOT / "docker-compose.local.yml").read_text())["services"]
        for name, svc in services.items():
            with self.subTest(service=name):
                self.assertTrue(sync.label_dict(svc.get("labels")).get("smr.description"),
                                f"docker-compose.local.yml: {name} has no smr.description label")


class HelpersTest(unittest.TestCase):

    def test_missing_description_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "no smr.description"):
            sync.describe("x", {"smr.monitor": "true"}, "f.yml")

    def test_list_labels(self):
        self.assertEqual(sync.label_dict(["smr.description=a=b", "smr.monitor=true"]),
                         {"smr.description": "a=b", "smr.monitor": "true"})

    def test_port(self):
        self.assertEqual(sync.port("${MQTT_PORT}:1883"), "MQTT_PORT→1883")
        self.assertEqual(sync.port("9001:9001"), "9001")
        self.assertEqual(sync.port("${PGADMIN_PORT:-5050}:80"), "5050→80")
        self.assertEqual(sync.port("${NTP_PORT}:123/udp"), "NTP_PORT→123/udp")

    def test_c4str_escapes_quotes(self):
        self.assertEqual(sync.c4str("the Pi's IMU"), "'the Pi\\'s IMU'")


if __name__ == "__main__":
    unittest.main()
