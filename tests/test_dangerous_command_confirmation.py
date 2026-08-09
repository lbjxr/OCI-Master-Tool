import unittest
from unittest.mock import patch

from oci_master.telegram_bot import TelegramBotRunner


class DangerousCommandConfirmationTests(unittest.TestCase):
    def make_bot(self):
        bot = TelegramBotRunner(
            {
                "telegram": {
                    "enabled": True,
                    "bot_token": "test-token",
                    "allowed_chat_ids": ["chat-1"],
                    "allowed_user_ids": ["user-1"],
                }
            }
        )
        bot.send_message = lambda *args, **kwargs: kwargs
        return bot

    def update(self, text):
        return {
            "update_id": 1,
            "message": {
                "chat": {"id": "chat-1"},
                "from": {"id": "user-1"},
                "text": text,
            },
        }

    def test_stop_command_only_creates_confirmation(self):
        bot = self.make_bot()
        with patch("oci_master.telegram_bot.execute_instance_action_data") as execute:
            bot.process_update(self.update("/instance_stop vm-1"))
        execute.assert_not_called()
        self.assertEqual(len(bot.dangerous_action_refs), 1)
        state = next(iter(bot.dangerous_action_refs.values()))
        self.assertEqual(state["action"], "instance_stop")
        self.assertEqual(state["target"], "vm-1")

    def test_delete_policy_command_only_creates_confirmation(self):
        bot = self.make_bot()
        with patch("oci_master.telegram_bot.delete_policy_data") as delete:
            bot.process_update(self.update("/delete_policy PolicyA"))
        delete.assert_not_called()
        self.assertEqual(len(bot.dangerous_action_refs), 1)
        state = next(iter(bot.dangerous_action_refs.values()))
        self.assertEqual(state["action"], "delete_policy")
        self.assertEqual(state["target"], "PolicyA")

    def test_confirmation_executes_once_for_owner(self):
        bot = self.make_bot()
        bot._active_callback_owner = ("chat-1", "user-1")
        token = bot._register_dangerous_action("instance_restart", "vm-1")
        callback = {
            "id": "callback-1",
            "data": f"danger:confirm:{token}",
            "from": {"id": "user-1"},
            "message": {"chat": {"id": "chat-1"}, "message_id": 10},
        }
        with patch.object(bot, "edit_message_text"), patch.object(bot, "answer_callback_query"), patch(
            "oci_master.telegram_bot.execute_instance_action_data",
            return_value={"id": "vm-1", "display_name": "vm-1"},
        ) as execute:
            bot.handle_callback_query(callback)
            bot.handle_callback_query(callback)
        execute.assert_called_once_with("restart", "vm-1", bot.app_config)


if __name__ == "__main__":
    unittest.main()
