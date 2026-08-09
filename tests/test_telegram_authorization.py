import unittest

from oci_master.telegram_bot import TelegramBotRunner


class TelegramAuthorizationTests(unittest.TestCase):
    def make_bot(self, **telegram_overrides):
        telegram = {
            "enabled": True,
            "bot_token": "test-token",
            "allowed_chat_ids": ["chat-1"],
            "allowed_user_ids": ["user-1"],
        }
        telegram.update(telegram_overrides)
        return TelegramBotRunner({"telegram": telegram})

    def test_validate_rejects_empty_chat_whitelist(self):
        bot = self.make_bot(allowed_chat_ids=[])
        with self.assertRaisesRegex(ValueError, "allowed_chat_ids"):
            bot.validate()

    def test_validate_rejects_empty_user_whitelist(self):
        bot = self.make_bot(allowed_user_ids=[])
        with self.assertRaisesRegex(ValueError, "allowed_user_ids"):
            bot.validate()

    def test_authorization_requires_both_chat_and_user_match(self):
        bot = self.make_bot()

        self.assertTrue(
            bot.is_authorized({"chat": {"id": "chat-1"}, "from": {"id": "user-1"}})
        )
        self.assertFalse(
            bot.is_authorized({"chat": {"id": "other-chat"}, "from": {"id": "user-1"}})
        )
        self.assertFalse(
            bot.is_authorized({"chat": {"id": "chat-1"}, "from": {"id": "other-user"}})
        )

    def test_empty_whitelists_never_authorize(self):
        bot = self.make_bot(allowed_chat_ids=[], allowed_user_ids=[])
        message = {"chat": {"id": "chat-1"}, "from": {"id": "user-1"}}
        self.assertFalse(bot.is_authorized(message))


if __name__ == "__main__":
    unittest.main()
