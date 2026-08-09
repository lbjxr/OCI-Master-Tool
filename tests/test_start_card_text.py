import unittest

from oci_master.telegram_bot import TelegramBotRunner


class StartCardTextTests(unittest.TestCase):
    def test_start_card_omits_legacy_project_phrase(self):
        bot = TelegramBotRunner({"telegram": {"enabled": False}})
        text = bot.build_start_card_text()
        self.assertNotIn("老项目那种一屏一块的操作感，我给它搬回来了。", text)
        self.assertIn("欢迎使用 OCI Master Telegram Bot", text)
        self.assertIn("快速入口", text)


if __name__ == "__main__":
    unittest.main()
