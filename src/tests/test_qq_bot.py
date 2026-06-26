from __future__ import annotations

import asyncio
import unittest

from daemon.qq_bot import QQBotClient, QQBotService, parse_qq_message


class RecordingQQBotClient(QQBotClient):
    def __init__(self) -> None:
        super().__init__("102012345", "secret")
        self.calls: list[dict] = []

    async def get_access_token(self) -> str:
        return "access-token"

    async def _request_json(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return {"id": "sent-message"}


class QQBotTests(unittest.TestCase):
    def test_parse_c2c_message_event(self) -> None:
        message = parse_qq_message(
            "C2C_MESSAGE_CREATE",
            {
                "id": "msg-1",
                "content": "  hello  ",
                "author": {"user_openid": "user-openid"},
            },
        )

        self.assertIsNotNone(message)
        self.assertEqual(message.message_id, "msg-1")
        self.assertEqual(message.content, "hello")
        self.assertEqual(message.user_openid, "user-openid")
        self.assertFalse(message.is_group)

    def test_parse_group_at_message_event(self) -> None:
        message = parse_qq_message(
            "GROUP_AT_MESSAGE_CREATE",
            {
                "id": "msg-2",
                "content": "<@!12345> 生成一份计划",
                "group_openid": "group-openid",
                "author": {"member_openid": "member-openid"},
            },
        )

        self.assertIsNotNone(message)
        self.assertEqual(message.content, "生成一份计划")
        self.assertEqual(message.group_openid, "group-openid")
        self.assertEqual(message.user_openid, "member-openid")
        self.assertTrue(message.is_group)

    def test_send_c2c_text_reply_uses_passive_message_id(self) -> None:
        async def run():
            client = RecordingQQBotClient()
            message = parse_qq_message(
                "C2C_MESSAGE_CREATE",
                {"id": "msg-1", "content": "hello", "author": {"user_openid": "user-openid"}},
            )
            await client.send_text_reply(message, "hi", msg_seq=2)
            return client.calls[0]

        call = asyncio.run(run())
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/v2/users/user-openid/messages"))
        self.assertEqual(call["kwargs"]["json"]["content"], "hi")
        self.assertEqual(call["kwargs"]["json"]["msg_type"], 0)
        self.assertEqual(call["kwargs"]["json"]["msg_id"], "msg-1")
        self.assertEqual(call["kwargs"]["json"]["msg_seq"], 2)

    def test_send_group_text_reply_uses_group_openid(self) -> None:
        async def run():
            client = RecordingQQBotClient()
            message = parse_qq_message(
                "GROUP_AT_MESSAGE_CREATE",
                {
                    "id": "msg-2",
                    "content": "hello",
                    "group_openid": "group-openid",
                    "author": {"member_openid": "member-openid"},
                },
            )
            await client.send_text_reply(message, "hi")
            return client.calls[0]

        call = asyncio.run(run())
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/v2/groups/group-openid/messages"))
        self.assertEqual(call["kwargs"]["json"]["msg_id"], "msg-2")

    def test_service_reports_missing_credentials_without_starting_thread(self) -> None:
        service = QQBotService()
        status = service.configure({"qq_bot_enabled": True, "app_id": "", "app_secret": ""})

        self.assertTrue(status["enabled"])
        self.assertFalse(status["running"])
        self.assertEqual(status["state"], "missing_credentials")


if __name__ == "__main__":
    unittest.main()
