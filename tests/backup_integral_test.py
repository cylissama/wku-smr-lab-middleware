import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from fastapi.testclient import TestClient
from fast_server.main import app

class BackupIntegrationTests(unittest.TestCase):

    def setUp(self):
        app.router.on_startup.clear()
        app.router.on_shutdown.clear()

        self.client = TestClient(app)

    def test_backup_success(self):
        fake_db = MagicMock()
        fake_db.create_backup.return_value = "/db_backups/test.sql"
        app.state.db = fake_db

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast, patch(
            "fast_server.main.log_system_logger"
        ) as mock_log:

            resp = self.client.get("/backup")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {"success": True, "path": "/db_backups/test.sql"},
        )

        mock_log.assert_not_called()

        messages = [call.args[1] for call in mock_broadcast.call_args_list]
        self.assertIn("DB Backup Started", messages)
        self.assertIn("DB Backup Completed", messages)

    def test_backup_failure(self):
        fake_db = MagicMock()

        def boom():
            raise Exception("boom")

        fake_db.create_backup.side_effect = boom
        app.state.db = fake_db

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast, patch(
            "fast_server.main.log_system_logger"
        ) as mock_log:
            resp = self.client.get("/backup")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertIn("boom", body["error"])

        mock_log.assert_called()

        error_texts = [call.args[1] for call in mock_broadcast.call_args_list]
        self.assertTrue(any("Failed to backup DB" in msg for msg in error_texts))

    def test_restore_backup_success(self):
        fake_db = MagicMock()
        fake_db.restore_backup = AsyncMock()
        app.state.db = fake_db

        filename = "test.sql"

        with patch(
            "fast_server.main.broadcast_message",
            new_callable=AsyncMock,
        ) as mock_broadcast, patch(
            "fast_server.main.log_system_logger"
        ) as mock_log:
            resp = self.client.post(f"/backup/restore/{filename}")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"success": True})

        fake_db.restore_backup.assert_awaited_once_with("/db_backups/test.sql")

        messages = [call.args[1] for call in mock_broadcast.call_args_list]
        self.assertIn("DB Restore Completed", messages)

        mock_log.assert_not_called()

    def test_restore_backup_failure(self):
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
            resp = self.client.post(f"/backup/restore/{filename}")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertIn("boom", body["error"])

        mock_log.assert_called()

        messages = [call.args[1] for call in mock_broadcast.call_args_list]
        self.assertTrue(any("Restore failed" in msg for msg in messages))


if __name__ == "__main__":
    unittest.main()
