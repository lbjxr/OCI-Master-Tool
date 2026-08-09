import unittest

from oci_master.telegram_bot import TelegramBotRunner


class UsageFeeKeyboardTests(unittest.TestCase):
    def test_usage_fee_keyboard_always_has_home_button(self):
        bot = TelegramBotRunner({"telegram": {"enabled": False}})

        keyboard = bot.build_usage_fee_keyboard(show_all=False, unique_dates_count=1, display_days=1)

        self.assertIsNotNone(keyboard)
        buttons = [button for row in keyboard["inline_keyboard"] for button in row]
        self.assertIn(
            {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            buttons,
        )


if __name__ == "__main__":
    unittest.main()
