import unittest
from unittest.mock import patch

from oci_master.telegram_bot import TelegramBotRunner


class TelegramRoutingTests(unittest.TestCase):
    def make_bot(self):
        return TelegramBotRunner({
            "telegram": {
                "enabled": True,
                "bot_token": "test-token",
                "allowed_chat_ids": ["chat-1"],
                "allowed_user_ids": ["user-1"],
            }
        })

    def callback(self, data):
        return {
            "id": "callback-1",
            "data": data,
            "from": {"id": "user-1"},
            "message": {"chat": {"id": "chat-1"}, "message_id": 10},
        }

    def test_menu_callback_is_delegated_to_menu_handler(self):
        bot = self.make_bot()
        with patch.object(bot, "_handle_menu_callback", return_value=True) as handler:
            bot.handle_callback_query(self.callback("menu:home"))
        handler.assert_called_once()

    def test_usage_callback_is_delegated_to_usage_handler(self):
        bot = self.make_bot()
        with patch.object(bot, "_handle_usage_fee_callback", return_value=True) as handler:
            bot.handle_callback_query(self.callback("usage_fee:expand"))
        handler.assert_called_once()

    def test_process_update_delegates_message_routing(self):
        bot = self.make_bot()
        update = {
            "update_id": 9,
            "message": {
                "chat": {"id": "chat-1"},
                "from": {"id": "user-1"},
                "text": "/menu",
            },
        }
        with patch.object(bot, "_handle_message_update", return_value=True) as handler:
            bot.process_update(update)
        handler.assert_called_once()

    def test_process_update_advances_offset_only_after_success(self):
        bot = self.make_bot()
        update = {"update_id": 9, "message": {"chat": {"id": "chat-1"}, "from": {"id": "user-1"}, "text": "/menu"}}
        with patch.object(bot, "_handle_message_update", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                bot.process_update(update)
        self.assertEqual(bot.last_update_id, 0)

    def test_instance_detail_update_reuses_lookup_result(self):
        bot = self.make_bot()
        update = {"update_id": 10, "message": {"chat": {"id": "chat-1"}, "from": {"id": "user-1"}, "text": "/instance_detail vm-1"}}
        with patch("oci_master.telegram_bot.get_instance_detail_data", return_value={"id": "vm-1", "display_name": "VM 1"}) as lookup, patch.object(bot, "send_message"):
            bot.process_update(update)
        self.assertEqual(lookup.call_count, 1)


if __name__ == "__main__":
    unittest.main()
