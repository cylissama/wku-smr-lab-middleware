import unittest
import asyncio
from unittest.mock import AsyncMock, patch

from fast_server import main as m


class ParserIntegralTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        while not m.imu_queue.empty():
            try:
                m.imu_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def test_imu_success(self):
        topic = "imu/device123"
        payload = (
            b"1700779200.123, 0.1, 0.2, 0.3,"
            b" 7, 2.0, 3.0,"
            b" 0.01, 0.02, 0.03,"
            b" 10.0, 20.0, 30.0"
        )

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await m.handle_sensors(None, topic, payload, None, None)

        item = await asyncio.wait_for(m.imu_queue.get(), timeout=1)

        self.assertEqual(item["device_label"], "device123")
        self.assertAlmostEqual(item["recorded_at"], 1700779200.123, places=6)
        self.assertEqual(item["accel_x"], 0.1)
        self.assertEqual(item["gyro_x"], 7)

        mock_broadcast.assert_not_called()

    async def test_imu_failure(self):
        topic = "imu/device123"
        payload = b"bad,not,enough,fields"

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast, patch(
            "fast_server.main.cur_imu_logger"
        ) as mock_logger:

            await m.handle_sensors(None, topic, payload, None, None)

        self.assertTrue(m.imu_queue.empty())

        mock_logger.error.assert_called()

        error_texts = [call.args[1] for call in mock_broadcast.call_args_list]
        self.assertTrue(any("IMU parse error" in msg for msg in error_texts))

    async def test_camera_success(self):
        topic = "camera/device123"
        payload = b"34234234234, 1, 2, 33, 44, 55, 66, 77, 88, image.py"

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await m.handle_camera(None, topic, payload, None, None)

        item = await asyncio.wait_for(m.camera_queue.get(), timeout=1)

        self.assertEqual(item["device_label"], "device123")
        self.assertAlmostEqual(item["recorded_at"], 34234234234, places=6)
        self.assertEqual(item["frame_idx"], 1)
        self.assertEqual(item["rvec_z"], 55)

        mock_broadcast.assert_not_called()

    async def test_camera_failure(self):
        topic = "camera/device123"
        payload = b"bad,not,enough,fields"

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast, patch(
            "fast_server.main.cur_camera_logger"
        ) as mock_logger:

            await m.handle_camera(None, topic, payload, None, None)

        self.assertTrue(m.camera_queue.empty())

        mock_logger.error.assert_called()

        error_texts = [call.args[1] for call in mock_broadcast.call_args_list]
        self.assertTrue(any("Camera parse error" in msg for msg in error_texts))


if __name__ == "__main__":
    unittest.main()
