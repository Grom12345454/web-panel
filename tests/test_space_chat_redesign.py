"""Checks the direction-only event flow, three-bot chat fan-out and chat privacy."""
import ast
from pathlib import Path
import unittest
from sqlalchemy import Boolean, Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base

ROOT = Path(__file__).resolve().parents[1]
WEB_SOURCE = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
WEB_AST = ast.parse(WEB_SOURCE)


def routine(name):
    return next(node for node in WEB_AST.body
                if isinstance(node, ast.FunctionDef) and node.name == name)


class SpaceRedesignStaticTests(unittest.TestCase):
    def test_only_directions_in_create_event(self):
        form = (ROOT / "frontend/templates/events/form.html").read_text(encoding="utf-8")
        self.assertIn('name="direction_ids"', form)
        self.assertNotIn('name="chat_targets"', form)
        self.assertNotIn('d.chats', form)
        fn = ast.get_source_segment(WEB_SOURCE, routine('create_quota'))
        self.assertIn('_resolve_event_chat_selection(', fn)
        self.assertIn('set_quota_chat_targets(q.id, selected_targets)', fn)
        self.assertNotIn('request.form.getlist("chat_targets")', fn)

    def test_three_messenger_announcement_flows(self):
        message = ast.get_source_segment(WEB_SOURCE, routine('chat_message'))
        competition = ast.get_source_segment(WEB_SOURCE, routine('publish_competition_announcement'))
        for implementation in (message, competition):
            self.assertIn('queue_social_chat_announcement(', implementation)
        self.assertIn('queue_other_messenger_event(quota, text)', WEB_SOURCE)
        self.assertIn('enqueue_calendar_announcement', (ROOT/'backend/app/services/delivery_outbox.py').read_text('utf-8'))
        self.assertIn('queue_other_messenger_event(quota, text)', WEB_SOURCE)
        transport = (ROOT/'backend/app/services/messenger_transports.py').read_text(encoding='utf-8')
        self.assertIn("if platform == 'vk'", transport)
        self.assertIn("if platform == 'max'", transport)

    def test_direction_chat_composer_is_available_only_to_chat_managers(self):
        chat = routine('chat_message')
        self.assertIn('login_required', [n.id for n in chat.decorator_list if isinstance(n, ast.Name)])
        chat_source = ast.get_source_segment(WEB_SOURCE, chat)
        self.assertIn("staff_allowed(current_user, did, 'chats', 'manage')", chat_source)
        self.assertIn('telegram_targets_for_directions([did])', chat_source)
        self.assertNotIn('request.form.get(\'chat_id\')', chat_source)
        for name in ('connect_chat_candidate', 'connect_social_chat', 'remove_social_chat',
                     'add_chat', 'chat_audience', 'delete_chat', 'test_chat'):
            self.assertIn('login_required',
                [n.id for n in routine(name).decorator_list if isinstance(n, ast.Name)], name)
            self.assertIn('_require_direction_chat_management',
                ast.get_source_segment(WEB_SOURCE, routine(name)), name)
        for name in ('messenger_chat_create', 'messenger_chat_remove'):
            self.assertIn('super_admin_required',
                [n.id for n in routine(name).decorator_list if isinstance(n, ast.Name)], name)
        detail = (ROOT/'frontend/templates/directions/detail.html').read_text(encoding='utf-8')
        self.assertIn('data-open-direction-broadcast', detail)
        self.assertIn("url_for('directions.chat_message', did=direction.id)", detail)
        self.assertIn('{% if can_manage_direction_chats %}', detail)
        self.assertIn('url_for(\'directions.connect_social_chat\'', detail)
        fn = ast.get_source_segment(WEB_SOURCE, routine('direction_detail'))
        self.assertIn("staff_allowed(current_user, did, section", fn)
        self.assertIn('can_send_direction_chat=can_send_direction_chat', fn)
        self.assertIn('can_manage_direction_chats=can_manage_direction_chats', fn)

    def test_assets_have_reduced_motion_and_space_scenes(self):
        staff = (ROOT/'static/css/site.bundle.css').read_text(encoding='utf-8')
        student = (ROOT/'static/css/student-app.bundle.css').read_text(encoding='utf-8')
        self.assertIn('.space-visual-scene', staff)
        self.assertIn('.student-orbit-scene', student)
        self.assertIn('prefers-reduced-motion:reduce', staff)
        self.assertIn('prefers-reduced-motion:reduce', student)


Base = declarative_base()


class DirectionChat(Base):
    __tablename__ = "chat_test"
    id = Column(Integer, primary_key=True)
    direction_id = Column(Integer, nullable=False)
    chat_id = Column(String(120))
    is_active = Column(Boolean, default=True)


class TargetRoutingTests(unittest.TestCase):
    def test_deduplicates_and_excludes_other_directions_and_disabled_chats(self):
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add_all([
                DirectionChat(direction_id=1, chat_id='-1001', is_active=True),
                DirectionChat(direction_id=2, chat_id='-1001', is_active=True),
                DirectionChat(direction_id=2, chat_id='-1002', is_active=True),
                DirectionChat(direction_id=1, chat_id='-1003', is_active=False),
                DirectionChat(direction_id=3, chat_id='-1004', is_active=True),
            ])
            session.commit()
            DirectionChat.query = session.query(DirectionChat)
            code = ast.Module(body=[routine('telegram_targets_for_directions')],type_ignores=[])
            namespace = {'DirectionChat':DirectionChat}
            exec(compile(code,'<isolated-web-helper>','exec'),namespace)
            fn=namespace['telegram_targets_for_directions']
            self.assertEqual([cid for _,cid in fn([1,2])],['-1001','-1002'])
            self.assertEqual([cid for _,cid in fn([2])],['-1001','-1002'])
            self.assertEqual(fn([]),[])
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
