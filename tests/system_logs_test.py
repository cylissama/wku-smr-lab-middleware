import json
import logging
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from stack_controller import containers as ct
from stack_controller import main as sc
from stack_controller.log_normalize import normalize_lines, redact


def docker_lines(*texts, start="2026-10-09T14:38:39", step=0):
    return [f"{start}.{100000000 + i * step:09d}Z {t}" for i, t in enumerate(texts)]


class NormalizeTests(unittest.TestCase):

    def test_json_log_record_passes_through(self):
        rec = {"id": "fastapi-app:x:1", "ts": "2026-10-09T14:38:39.100Z", "source": "fastapi-app",
               "logger": "system", "level": 40, "level_name": "ERROR", "priority": None,
               "category": "health", "important": True, "message": "db down: refused", "context": {}}
        [out] = normalize_lines("fastapi-app", docker_lines(json.dumps(rec)))
        self.assertEqual(out, rec)

    def test_json_record_source_is_the_compose_service(self):
        rec = {"id": "x", "ts": "2026-10-09T14:38:39.100Z", "source": "c35e051e86fd", "level": 20,
               "level_name": "INFO", "message": "Watchdog started"}
        [out] = normalize_lines("stack-controller", docker_lines(json.dumps(rec)))
        self.assertEqual(out["source"], "stack-controller")

    def test_third_party_levels(self):
        cases = {
            "2026/10/09 13:45:28 [emerg] 1#1: host not found in upstream \"fastapi-app\"": logging.CRITICAL,
            "ERROR:    Application startup failed. Exiting.": logging.ERROR,
            "INFO:     Uvicorn running on http://0.0.0.0:8000": logging.INFO,
            "[2026-10-09 14:38:39 +0000] [1] [WARNING] Worker timeout": logging.WARNING,
            "1791556719: mosquitto version 2.0.18 running": logging.INFO,
            "1791556719: Error: Address in use": logging.ERROR,
            '172.21.0.1 - - [09/Oct/2026:14:38:39 +0000] "GET /api/x HTTP/1.1" 502 157 "-" "curl"': logging.ERROR,
            "2026-10-09 14:38:39 [WARNING] robot_logger_x: Dropped 3 robot rows": logging.WARNING,
            "something happened": logging.INFO,
        }
        for text, level in cases.items():
            [out] = normalize_lines("svc", docker_lines(text))
            self.assertEqual(out["level"], level, text)
            self.assertIsNone(out["priority"])

    def test_traceback_is_folded_into_its_record(self):
        lines = docker_lines(
            "ERROR:    Exception in 'lifespan' protocol",
            "Traceback (most recent call last):",
            '  File "/x.py", line 1, in <module>',
            "    await pool()",
            "OSError: [Errno 111] Connection refused",
            "ERROR:    Application startup failed. Exiting.",
        )
        out = normalize_lines("fastapi-app", lines)
        self.assertEqual(len(out), 2)
        self.assertIn("Connection refused", out[0]["message"])
        self.assertIn("Traceback", out[0]["message"])
        self.assertEqual(out[1]["message"], "Application startup failed. Exiting.")

    def test_traceback_not_folded_into_an_old_record(self):
        lines = ["2026-10-09T14:00:00.000000000Z INFO:     started",
                 "2026-10-09T14:05:00.000000000Z Traceback (most recent call last):",
                 '2026-10-09T14:05:00.000000001Z   File "/x.py", line 1',
                 "2026-10-09T14:05:00.000000002Z ValueError: bad"]
        out = normalize_lines("svc", lines)
        self.assertEqual(len(out), 2)
        self.assertTrue(out[1]["message"].startswith("Traceback"))
        self.assertIn("ValueError: bad", out[1]["message"])
        self.assertEqual(out[1]["level"], logging.ERROR)

    def test_ids_are_stable_across_reads(self):
        lines = docker_lines("a", "b", step=1)
        self.assertEqual([r["id"] for r in normalize_lines("s", lines)],
                         [r["id"] for r in normalize_lines("s", lines)])

    def test_redaction(self):
        self.assertEqual(redact("PGPASSWORD=hunter2 next"), "PGPASSWORD=*** next")
        self.assertEqual(redact('{"password": "hunter2"}'), '{"password": "***"}')
        self.assertEqual(redact("Authorization: Bearer abc.def"), "Authorization: Bearer ***")
        self.assertEqual(redact("postgres://smr:s3cret@db:5432/x"), "postgres://smr:***@db:5432/x")
        [out] = normalize_lines("svc", docker_lines("connect failed password=hunter2"))
        self.assertNotIn("hunter2", out["message"])


def fake_container(name, service, status="running", health=None, labels=None, logs=b"", restart_count=0):
    c = MagicMock()
    c.name = name
    c.labels = {"com.docker.compose.service": service, "smr.monitor": "true", **(labels or {})}
    state = {"Status": status, "Running": status == "running", "ExitCode": 0 if status == "running" else 3,
             "StartedAt": "2026-10-09T14:00:00.000000000Z", "FinishedAt": "0001-01-01T00:00:00Z"}
    if health:
        state["Health"] = health
    c.attrs = {"State": state, "RestartCount": restart_count, "Config": {"Image": f"{service}:latest"}}
    c.logs = MagicMock(return_value=logs)
    return c


def unhealthy(streak=3, output="not answering"):
    return {"Status": "unhealthy", "FailingStreak": streak,
            "Log": [{"Start": "2026-10-09T14:00:00Z", "ExitCode": 1, "Output": output}]}


class DockerTimeTests(unittest.TestCase):

    def test_utc_and_offset_times_agree(self):
        utc = ct._parse_time("2026-10-09T13:57:36.391292706Z")
        local = ct._parse_time("2026-10-09T08:57:36.391292706-05:00")
        self.assertAlmostEqual(utc, local, places=3)
        self.assertIsNone(ct._parse_time("0001-01-01T00:00:00Z"))
        self.assertIsNone(ct._parse_time(""))


class WatchdogTests(unittest.TestCase):

    def setUp(self):
        self.log_event = patch.object(ct, "log_event")
        self.log_event.start()

    def tearDown(self):
        self.log_event.stop()

    def client_with(self, *containers):
        client = MagicMock()
        client.containers.list = MagicMock(return_value=list(containers))
        return client

    def test_restarts_unhealthy_and_gives_up_after_limit(self):
        bad = fake_container("AMS-tcp-listener", "tcp", health=unhealthy(), labels={"smr.autoheal": "true"})
        dog = ct.Watchdog()

        with patch.object(ct, "WATCHDOG_MAX_RESTARTS", 2):
            for _ in range(4):
                dog.check_once(self.client_with(bad))

        self.assertEqual(bad.restart.call_count, 2)
        actions = [e["action"] for e in dog.history]
        self.assertEqual(actions, ["restarted", "restarted", "gave_up"])
        self.assertTrue(dog.status_for("AMS-tcp-listener")["gave_up"])

    def test_leaves_healthy_and_starting_alone(self):
        ok = fake_container("AMS-web", "web", health={"Status": "healthy", "Log": []}, labels={"smr.autoheal": "true"})
        starting = fake_container("AMS-x", "x", health={"Status": "starting", "Log": []}, labels={"smr.autoheal": "true"})
        dog = ct.Watchdog()
        dog.check_once(self.client_with(ok, starting))
        ok.restart.assert_not_called()
        starting.restart.assert_not_called()

    def test_only_autoheal_containers_are_listed_for_restart(self):
        client = self.client_with()
        ct.Watchdog().check_once(client)
        client.containers.list.assert_called_once_with(filters={"label": "smr.autoheal=true"})


class SystemEndpointTests(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(sc.app)
        self.docker = MagicMock()
        self.patch = patch.object(ct, "_client", return_value=self.docker)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_containers_reports_health_and_crash_logs(self):
        crash_logs = "\n".join(docker_lines("ERROR:    Application startup failed. Exiting.")).encode()
        self.docker.containers.list = MagicMock(return_value=[
            fake_container("AMS-fastapi", "fastapi-app", status="restarting", logs=crash_logs, restart_count=4),
            fake_container("AMS-tcp-listener", "tcp", health=unhealthy(output="alive; db down")),
        ])

        body = self.client.get("/containers").json()
        by_service = {c["service"]: c for c in body["containers"]}

        self.docker.containers.list.assert_called_with(all=True, filters={"label": "smr.monitor=true"})
        api = by_service["fastapi-app"]
        self.assertTrue(api["crashed"])
        self.assertEqual(api["restart_count"], 4)
        self.assertEqual(api["logs"][0]["message"], "Application startup failed. Exiting.")
        tcp = by_service["tcp"]
        self.assertEqual(tcp["health"]["status"], "unhealthy")
        self.assertEqual(tcp["health"]["probes"][-1]["output"], "alive; db down")
        self.assertIsNone(tcp["logs"])

    def test_logs_merges_sources_in_time_order_and_filters(self):
        a = fake_container("AMS-a", "a", logs="\n".join(
            docker_lines("INFO:     one", "ERROR:    three", start="2026-10-09T14:00:01", step=0)).encode())
        b = fake_container("AMS-b", "b", logs="\n".join(
            docker_lines("WARNING:  two", start="2026-10-09T14:00:02")).encode())
        self.docker.containers.list = MagicMock(return_value=[a, b])

        body = self.client.get("/logs").json()
        self.assertEqual([r["source"] for r in body["records"]], ["a", "a", "b"])
        self.assertEqual(body["sources"], ["a", "b"])

        important = self.client.get("/logs?important_only=true").json()["records"]
        self.assertEqual([r["level_name"] for r in important], ["ERROR", "WARNING"])

        only_b = self.client.get("/logs?source=b").json()["records"]
        self.assertEqual([r["source"] for r in only_b], ["b"])
        a.logs.assert_called()

    def test_logs_passes_since_to_docker(self):
        c = fake_container("AMS-a", "a")
        self.docker.containers.list = MagicMock(return_value=[c])
        self.client.get("/logs?since=2026-10-09T14:00:00Z&tail=5000")
        kwargs = c.logs.call_args.kwargs
        self.assertEqual(kwargs["tail"], 1000)
        self.assertAlmostEqual(kwargs["since"], 1791554400.0)

    def test_docker_unavailable_is_a_clear_503(self):
        self.patch.stop()
        with patch.object(ct, "_client", side_effect=RuntimeError("socket missing")):
            resp = self.client.get("/containers")
        self.patch.start()
        self.assertEqual(resp.status_code, 503)
        self.assertIn("socket missing", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
