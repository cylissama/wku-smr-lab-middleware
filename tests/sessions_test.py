import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from fast_server.main import app, get_sessions

class GetSessionsTests(unittest.IsolatedAsyncioTestCase):

    async def test_get_sessions_success(self):
        fake_db = MagicMock()
        fake_db.retrieve_sessions = AsyncMock(
            return_value=[{"id": 1}, {"id": 2}]
        )
        app.state.db = fake_db

        with patch(
            "fast_server.main.log_system_logger"
        ) as mock_log, patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            result = await get_sessions()

        self.assertEqual(
            result,
            {"data": [{"id": 1}, {"id": 2}], "success": True},
        )

        mock_log.assert_not_called()
        mock_broadcast.assert_not_called()

    async def test_get_sessions_failure(self):
        fake_db = MagicMock()

        async def boom():
            raise Exception("boom")

        fake_db.retrieve_sessions = AsyncMock(side_effect=boom)
        app.state.db = fake_db

        with patch(
            "fast_server.main.log_system_logger"
        ) as mock_log, patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            result = await get_sessions()

        self.assertFalse(result["success"])
        self.assertIn("boom", result["error"])

        mock_log.assert_called()

        error_args = [call.args[1] for call in mock_broadcast.call_args_list]
        self.assertTrue(any("Failed to pull sessions" in msg for msg in error_args))