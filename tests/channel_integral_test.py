# Test created by GPT 5.1 and Edited by Michael
import unittest
from fastapi.testclient import TestClient

from fast_server.main import app, MANAGERS

class FakeManager:
    def __init__(self):
        self.sent = []

    async def broadcast_json(self, data):
        self.sent.append(data)

class ChannelIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.fake = FakeManager()
        MANAGERS["test"] = self.fake

    def test_send_channel_happy_path(self):
        
        resp = self.client.post(
            "/send/test",
            json={"text": "hello", "type": "info"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"success": True})

        self.assertEqual(len(self.fake.sent), 1)
        self.assertEqual(self.fake.sent[0]["text"], "hello")
        self.assertEqual(self.fake.sent[0]["type"], "info")

    def test_send_channel_defaults_type(self):

        resp = self.client.post(
            "/send/test",
            json={"text": "hello"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"success": True})
        self.assertEqual(len(self.fake.sent), 1)
        self.assertEqual(self.fake.sent[0]["type"], "normal")

    def test_send_channel_unknown_channel(self):

        resp = self.client.post(
            "/send/does-not-exist",
            json={"text": "hello"},
        )

        self.assertEqual(resp.status_code, 404)
