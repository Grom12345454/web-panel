"""Pure adapter contract tests; no tokens, Flask, aiogram or network calls."""
import json
import unittest
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
import ast
import re

ROOT = Path(__file__).resolve().parents[1]
from services.bot_ui import (HOME_ROWS, WELCOME_ROWS, COMMANDS,
    action_to_command, rows_for_screen, welcome_text)


class UnifiedBotScreens(unittest.TestCase):
    def test_new_user_must_choose_existing_account_or_new_registration(self):
        actions = [b.key for row in WELCOME_ROWS for b in row]
        self.assertEqual(actions, ['onboarding_existing','onboarding_new'])
        self.assertEqual(action_to_command('onboarding_existing'), '/link')
        self.assertEqual(action_to_command('onboarding_new'), '/register')
        self.assertIn('уже есть аккаунт', welcome_text().lower())
        self.assertNotIn('подтверждает владелец', welcome_text().lower())
        self.assertNotIn('простое указание id другого человека', welcome_text().lower())

    def test_main_menu_and_dynamic_directions_are_common(self):
        keys = [b.key for row in HOME_ROWS for b in row]
        self.assertGreaterEqual(len(keys), 8)
        for key in ('menu_apply','menu_status','menu_events','menu_profile',
                    'menu_accounts','menu_leadership','menu_inbox','menu_app'):
            self.assertIn(key, keys)
        rows = rows_for_screen('directions', directions=[(5, '✦', 'Медиа')])
        self.assertEqual(rows[0][0].key, 'direction_5')
        self.assertEqual(action_to_command('direction_5'), '/apply 5')
        self.assertIsNone(action_to_command('direction_5;DROP'))
        self.assertIsNone(action_to_command('pair:approve:bad'))

    def test_events_route_to_same_application_features(self):
        self.assertEqual(action_to_command('event_detail_6'), '/event 6')
        self.assertEqual(action_to_command('event_join_6_2026-12-12'), '/join 6 2026-12-12')
        self.assertEqual(action_to_command('event_decline_6'), '/decline 6')
        self.assertEqual(action_to_command('event_return_6'), '/return 6')

    def test_telegram_uses_shared_menu_and_onboarding(self):
        tg = (ROOT/'backend/app/handlers/menu.py').read_text(encoding='utf8')
        self.assertIn("rows_for_screen('home')", tg)
        self.assertIn("rows_for_screen('welcome')", tg)
        self.assertIn('onboarding_existing', tg)
        self.assertIn('onboarding_new', tg)
        self.assertIn("'/inbox'", tg)


class NativeButtons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ast.parse((ROOT/'backend/app/services/messenger_transports.py').read_text('utf8'))
        needed = {'_vk_buttons','_max_buttons'}
        nodes = [node for node in source.body if isinstance(node,ast.FunctionDef) and node.name in needed]
        cls.ctx = {
            'json':json, 're':re,
            'settings':SimpleNamespace(MAX_BOT_USERNAME='studentcouncil'),
            'vk_app_url':lambda:'https://vk.com/app12345',
            'max_app_url':lambda:'https://max.ru/studentcouncil?startapp',
        }
        exec(compile(ast.Module(body=nodes,type_ignores=[]), '<native>', 'exec'), cls.ctx)

    def test_vk_payload_and_app_link(self):
        markup = json.loads(self.ctx['_vk_buttons'](HOME_ROWS))
        self.assertFalse(markup['inline'])
        self.assertFalse(markup['one_time'])
        buttons = markup['buttons']
        actions = [b['action'] for row in buttons for b in row]
        self.assertTrue(all(b['type']=='text' for b in actions))
        self.assertTrue(any(json.loads(b['payload']).get('ui')=='menu_apply'
                            for b in actions))
        self.assertTrue(any(json.loads(b['payload']).get('ui')=='menu_app' for b in actions))

    def test_max_uses_persistent_reply_keyboard_messages(self):
        attachment = self.ctx['_max_buttons'](HOME_ROWS)[0]
        self.assertEqual(attachment['type'], 'reply_keyboard')
        actions = [b for row in attachment['buttons'] for b in row]
        self.assertTrue(all(b['type']=='message' for b in actions))
        self.assertTrue(any(b.get('payload')=='ui:menu_apply' for b in actions))
        self.assertTrue(any(b.get('payload')=='ui:menu_app' for b in actions))

    def test_vkontakte_keeps_under_keyboard_limit(self):
        rows = rows_for_screen('directions',directions=[(i,'✦',str(i)) for i in range(100)])
        self.assertLessEqual(sum(len(row) for row in rows),10)
        rows = rows_for_screen('event',event=(3,['2026-12-01']*60,False))
        self.assertLessEqual(sum(len(row) for row in rows),10)


class MaxCallbackIdentity(unittest.TestCase):
    def test_max_takes_clicking_user_not_sender_bot(self):
        source = ast.parse((ROOT/'backend/app/services/messenger_transports.py').read_text('utf8'))
        fun = next(node for node in source.body if isinstance(node,ast.FunctionDef) and node.name=='handle_max_event')
        sends=[]
        ctx = {'re':re,'logger':SimpleNamespace(warning=lambda *a:None,exception=lambda *a:None),
               '_deliver_private':lambda platform, uid, text, **kwargs: (('Reply for '+uid),{'rows':(),'app':False}),
               'max_request':lambda *args,**kwargs:{},
               'send_message':lambda *args,**kwargs:sends.append((args,kwargs)),
               'record_bot_event':lambda *args, **kwargs:None,
               'requests':SimpleNamespace(RequestException=Exception)}
        exec(compile(ast.Module(body=[fun],type_ignores=[]),'<max-event>','exec'),ctx)
        payload = {'update_type':'message_callback',
                   'user':{'user_id':777,'username':'verified-user'},
                   'message':{'sender':{'user_id':999,'is_bot':True}},
                   'callback':{'payload':'ui:menu_status','callback_id':'cb123'}}
        ctx['handle_max_event'](payload,SimpleNamespace(app_context=nullcontext))
        self.assertEqual(sends[0][0][1],777)
        self.assertIn('777', sends[0][0][2])


if __name__=='__main__':
    unittest.main()

class BottomKeyboardRegistrationRegression(unittest.TestCase):
    def test_registration_uses_persistent_reply_keyboard_not_inline_markup(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / 'backend' / 'app' / 'handlers' / 'registration.py').read_text(encoding='utf-8')
        self.assertIn('ReplyKeyboardMarkup', source)
        self.assertIn("KeyboardButton(text='🏫 Колледж')", source)
        self.assertIn("KeyboardButton(text='🎓 Институт')", source)
        self.assertIn("KeyboardButton(text='✕ Отменить')", source)
        self.assertIn('home_reply_keyboard(True)', source)
        self.assertIn('ReplyKeyboardMarkup is attached to the chat composer', source)
