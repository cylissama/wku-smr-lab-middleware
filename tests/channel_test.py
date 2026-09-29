import unittest
from fastapi import HTTPException
from fast_server.main import send_channel, MANAGERS

class FakeManager:

    def __init__(self):
        self.sent = []

    async def broadcast_json(self, data):
        self.sent.append(data)

class ChannelTest(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.fake = FakeManager()
        MANAGERS["test"] = self.fake

    async def test_unknown_channel_404(self):

        with self.assertRaises(HTTPException) as cm:
            await send_channel("nope", {"text": "hi"})

        self.assertEqual(cm.exception.status_code, 404)

    async def test_missing_text_400(self):

        with self.assertRaises(HTTPException) as cm:
            await send_channel("test", {"type": "info"})

        self.assertEqual(cm.exception.status_code, 400)

    async def test_missing_type_defaults_to_normal(self):

        result = await send_channel("test", {"text": "hello"})

        self.assertEqual(result, {"success": True})
        self.assertEqual(len(self.fake.sent), 1)
        self.assertEqual(self.fake.sent[0]["text"], "hello")
        self.assertEqual(self.fake.sent[0]["type"], "normal")
