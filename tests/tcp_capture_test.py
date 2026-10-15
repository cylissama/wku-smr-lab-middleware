import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from db.database import SessionNotStarted
from fast_server.capture import CaptureMode, CaptureState
from tcp_server import tcp_server as t

ROBOT_LINE = b"1, 1700779200.5, 11/23/2023 12:00, 1, 2, 3, 4, 5, 6, 10, 20, 30, 0.1, 0.2, 0.3\n"


def drain(queue: asyncio.Queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


class FakeRequest:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


class TcpCaptureTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        drain(t.robot_queue)
        self.loggers = patch.object(t.loggers, "cur_robot_logger", MagicMock())
        self.loggers.start()
        self.send = patch("tcp_server.tcp_server.send_to_fastapi", new_callable=AsyncMock)
        self.send.start()
        self.fake_db = MagicMock()
        self.fake_db.get_time = MagicMock(return_value=123.0)
        self.get_db = patch("tcp_server.tcp_server.DatabaseSingleton.get_instance",
                            new_callable=AsyncMock, return_value=self.fake_db)
        self.get_db.start()
        # Fresh copy per test, as tcp_server has at boot (version 0, idle)
        self.capture = patch.object(t, "capture", CaptureState())
        self.capture.start()
        self.nowait = patch("tcp_server.tcp_server.send_to_fastapi_nowait")
        self.mock_nowait = self.nowait.start()
        t.live_sampler.reset()

    async def asyncTearDown(self):
        self.loggers.stop()
        self.send.stop()
        self.get_db.stop()
        self.capture.stop()
        self.nowait.stop()

    async def feed(self, *lines):
        reader = asyncio.StreamReader()
        for line in lines:
            reader.feed_data(line)
        reader.feed_eof()
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        await t.handle_robot(reader, writer)

    async def test_idle_drops_lines(self):
        await self.feed(ROBOT_LINE, ROBOT_LINE)
        self.assertTrue(t.robot_queue.empty())

    async def test_record_queues_tagged_lines(self):
        t.capture.set(CaptureMode.RECORD, session_id=8)

        await self.feed(ROBOT_LINE, ROBOT_LINE)

        items = drain(t.robot_queue)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i["session_id"] == 8 for i in items))
        self.assertEqual(items[0]["joint1"], 1.0)

    async def test_monitor_sends_one_live_sample_and_queues_nothing(self):
        t.capture.set(CaptureMode.MONITOR)

        await self.feed(ROBOT_LINE, ROBOT_LINE, ROBOT_LINE)

        self.assertTrue(t.robot_queue.empty())
        self.mock_nowait.assert_called_once()
        text, msg_type = self.mock_nowait.call_args.args
        self.assertEqual(msg_type, "live")
        self.assertIn("[live] robot/main", text)
        self.assertIn("joints (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)", text)

    async def test_idle_sends_no_live_samples(self):
        await self.feed(ROBOT_LINE)
        self.mock_nowait.assert_not_called()

    async def test_queue_status_counts_robot_connections(self):
        reader = asyncio.StreamReader()
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        handler = asyncio.create_task(t.handle_robot(reader, writer))
        await asyncio.sleep(0)

        during = json.loads((await t.queue_status(None)).text)["connections"]
        reader.feed_eof()
        await handler
        after = json.loads((await t.queue_status(None)).text)["connections"]

        self.assertEqual((during, after), (1, 0))

    async def test_queue_status_reports_robot_activity(self):
        t.capture.set(CaptureMode.MONITOR)

        await self.feed(ROBOT_LINE)

        activity = json.loads((await t.queue_status(None)).text)["activity"]
        self.assertTrue(activity["receiving"])

    async def test_robot_not_selected_is_dropped(self):
        t.capture.set(CaptureMode.RECORD, session_id=8, devices={"imu/106"})

        await self.feed(ROBOT_LINE)

        self.assertTrue(t.robot_queue.empty())

    async def test_flush_drops_stale_and_no_session(self):
        t.capture.set(CaptureMode.RECORD, session_id=8)

        self.fake_db.insert_robot_batch = AsyncMock()
        self.assertTrue(await t.flush_robot_batch(self.fake_db, [{"session_id": 7}, {"session_id": 8}]))
        self.fake_db.insert_robot_batch.assert_awaited_once_with([{"session_id": 8}])

        self.fake_db.insert_robot_batch = AsyncMock(side_effect=SessionNotStarted("none"))
        self.assertTrue(await t.flush_robot_batch(self.fake_db, [{"session_id": 8}]))

        self.fake_db.insert_robot_batch = AsyncMock(side_effect=ConnectionError("db down"))
        self.assertFalse(await t.flush_robot_batch(self.fake_db, [{"session_id": 8}]))

    async def test_put_capture_applies_newer_state_only(self):
        source = CaptureState()
        source.set(CaptureMode.RECORD, session_id=8)
        older = source.to_dict()
        source.set(CaptureMode.STOPPING, session_id=8)
        newer = source.to_dict()

        await t.put_capture(FakeRequest(newer))
        self.assertEqual(t.capture.mode, CaptureMode.STOPPING)

        await t.put_capture(FakeRequest(older))
        self.assertEqual(t.capture.mode, CaptureMode.STOPPING)

    async def test_put_capture_rejects_bad_body(self):
        resp = await t.put_capture(FakeRequest({"mode": "nonsense", "version": 10 ** 15}))
        self.assertEqual(resp.status, 400)
        self.assertEqual(t.capture.mode, CaptureMode.IDLE)


if __name__ == "__main__":
    unittest.main()
