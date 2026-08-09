import time
import unittest

from oci_master.telegram_bot import TelegramBotRunner


class CallbackStateSecurityTests(unittest.TestCase):
    def make_bot(self):
        return TelegramBotRunner(
            {
                "telegram": {
                    "enabled": True,
                    "bot_token": "test-token",
                    "allowed_chat_ids": ["chat-1"],
                    "allowed_user_ids": ["user-1", "user-2"],
                }
            }
        )

    def test_callback_ref_is_random_and_owner_bound(self):
        bot = self.make_bot()
        bot._active_callback_owner = ("chat-1", "user-1")
        token = bot._register_callback_ref("instance-1", "i")
        self.assertNotEqual(token, bot._register_callback_ref("instance-1", "i"))
        self.assertEqual(bot._resolve_callback_ref(token), "instance-1")

        bot._active_callback_owner = ("chat-1", "user-2")
        with self.assertRaisesRegex(ValueError, "不属于当前用户"):
            bot._resolve_callback_ref(token)

    def test_callback_ref_expires(self):
        bot = self.make_bot()
        bot._active_callback_owner = ("chat-1", "user-1")
        token = bot._register_callback_ref("value")
        bot.callback_ttl_seconds = 0
        with self.assertRaisesRegex(ValueError, "已失效"):
            bot._resolve_callback_ref(token)

    def test_dangerous_flow_is_consumed_once(self):
        bot = self.make_bot()
        bot._active_callback_owner = ("chat-1", "user-1")
        token = bot._register_netsec_flow("open", "instance-1", "22", "192.0.2.10/32")
        state = bot._consume_callback_state(bot.netsec_flow_refs, token, "已失效")
        self.assertEqual(state["action"], "open")
        with self.assertRaisesRegex(ValueError, "已失效"):
            bot._consume_callback_state(bot.netsec_flow_refs, token, "已失效")

    def test_callback_store_is_bounded(self):
        bot = self.make_bot()
        bot._active_callback_owner = ("chat-1", "user-1")
        bot.callback_capacity = 2
        for index in range(3):
            bot._register_callback_ref(str(index))
        self.assertLessEqual(len(bot.callback_refs), 2)


if __name__ == "__main__":
    unittest.main()
