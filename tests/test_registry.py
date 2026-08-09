import unittest

from oci_master import registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        registry.clear_registries()

    def test_register_and_dispatch_cli(self):
        called = {}
        def handler(app_config, args):
            called['app_config'] = app_config
            called['args'] = args
            return 'ok'
        registry.register_cli('test_action', handler, help_text='do a thing')
        result = registry.dispatch_cli('test_action:arg1:arg2', {'x': 1})
        self.assertEqual(result, 'ok')
        self.assertEqual(called['app_config'], {'x': 1})
        self.assertEqual(called['args'], ('arg1', 'arg2'))

    def test_cli_unknown_action_raises(self):
        with self.assertRaisesRegex(ValueError, '不支持的 action'):
            registry.dispatch_cli('unknown', {})

    def test_register_and_dispatch_telegram_message(self):
        called = {}
        def handler(runner, text, chat_id, user_id, message_id):
            called['text'] = text
        registry.register_telegram_message('/test', handler)
        handled = registry.dispatch_telegram_message(None, '/test hello', '1', '2', '3')
        self.assertTrue(handled)
        self.assertEqual(called['text'], '/test hello')

    def test_telegram_message_unhandled_returns_false(self):
        handled = registry.dispatch_telegram_message(None, '/unknown', '1', '2', '3')
        self.assertFalse(handled)

    def test_register_and_dispatch_telegram_callback(self):
        called = {}
        def handler(runner, callback_data, chat_id, user_id, message_id, callback_query_id):
            called['data'] = callback_data
        registry.register_telegram_callback('menu', handler)
        handled = registry.dispatch_telegram_callback(None, 'menu:home', '1', '2', '3')
        self.assertTrue(handled)
        self.assertEqual(called['data'], 'menu:home')

    def test_telegram_callback_unhandled_returns_false(self):
        handled = registry.dispatch_telegram_callback(None, 'unknown:x', '1', '2', '3')
        self.assertFalse(handled)

    def test_menu_entries(self):
        registry.register_menu('1. 👤 User', 'user_info', '查看用户信息')
        entries = registry.get_menu_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0], ('1. 👤 User', 'user_info', '查看用户信息'))

    def test_list_cli_actions(self):
        registry.register_cli('a', lambda c, a: None, 'help a')
        registry.register_cli('b', lambda c, a: None, 'help b')
        actions = registry.list_cli_actions()
        self.assertEqual(actions, [('a', 'help a'), ('b', 'help b')])

    def test_clear_registries(self):
        registry.register_cli('x', lambda c, a: None)
        registry.register_telegram_message('/x', lambda *a: None)
        registry.register_telegram_callback('x', lambda *a: None)
        registry.register_menu('X', 'x')
        registry.clear_registries()
        self.assertEqual(registry.list_cli_actions(), [])
        self.assertEqual(registry.get_menu_entries(), [])
        self.assertFalse(registry.dispatch_telegram_message(None, '/x', '1', '2', '3'))
        self.assertFalse(registry.dispatch_telegram_callback(None, 'x:y', '1', '2', '3'))


if __name__ == '__main__':
    unittest.main()
