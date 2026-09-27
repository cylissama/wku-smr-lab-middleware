## These tests were created with ChatGPT and edited by Michael ##

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fast_server.main import try_backup, app, restore_backup


class BackupTests(unittest.IsolatedAsyncioTestCase):

    async def test_restore_backup_success(self):
        fake_db = MagicMock()
        fake_db.restore_backup = AsyncMock()
        app.state.db = fake_db

        filename = "test.sql"

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            result = await restore_backup(filename)

        self.assertEqual(result, {"success": True})

        fake_db.restore_backup.assert_awaited_once_with("/db_backups/test.sql")

        mock_broadcast.assert_any_call(
            unittest.mock.ANY,
            "DB Restore Completed",
        )

    async def test_restore_backup_failure(self):
        fake_db = MagicMock()

        async def boom(path: str):
            raise Exception("boom")

        fake_db.restore_backup = AsyncMock(side_effect=boom)
        app.state.db = fake_db

        filename = "test.sql"

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast, patch(
            "fast_server.main.log_system_logger"
        ) as mock_log:
            result = await restore_backup(filename)

        self.assertFalse(result["success"])
        self.assertIn("boom", result["error"])

        error_calls = [
            call for call in mock_broadcast.call_args_list
            if "Restore failed" in call.args[1]
        ]
        self.assertTrue(error_calls)

        mock_log.assert_called()

    async def test_try_backup_success(self):

        fake_db = MagicMock()
        fake_db.create_backup.return_value = "/db_backups/test.sql"
        app.state.db = fake_db

        with patch("fast_server.main.broadcast_message", new_callable=AsyncMock) as mock_broadcast:
            result = await try_backup()

        self.assertEqual(result, {
            "success": True,
            "path": "/db_backups/test.sql",
        })

        mock_broadcast.assert_any_call(
            unittest.mock.ANY,
            "DB Backup Started"
        )
        mock_broadcast.assert_any_call(
            unittest.mock.ANY,
            "DB Backup Completed"
        )

    async def test_try_backup_failure(self):

        fake_db = MagicMock()

        def boom():
            raise Exception("boom")

        fake_db.create_backup.side_effect = boom
        app.state.db = fake_db

        with patch("fast_server.main.broadcast_message", new_callable=AsyncMock) as mock_broadcast:
            result = await try_backup()

        self.assertEqual(result["success"], False)
        self.assertIn("boom", result["error"])

        error_calls = [
            call for call in mock_broadcast.call_args_list
            if "Failed to backup DB" in call.args[1]
        ]
        self.assertTrue(error_calls)
