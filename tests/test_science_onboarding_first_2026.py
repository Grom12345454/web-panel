"""No-network regression suite for pre-council science registration."""
import ast
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ScienceFirstTests(unittest.TestCase):
    def test_bot_first_choice_and_independent_callback(self):
        src = (ROOT / 'backend/app/services/bot_ui.py').read_text('utf-8')
        ns = {'__name__': '_test_bot_ui'}
        exec(compile(src, 'bot_ui', 'exec'), ns)
        welcome = ns['rows_for_screen']('welcome')
        self.assertEqual(welcome[0][0].key, 'menu_science')
        self.assertEqual(ns['action_to_command']('menu_science'), '/science')
        self.assertEqual(ns['action_to_command']('science_read_12'), '/science_apply 12')
        self.assertEqual(ns['rows_for_screen']('science', readings=[(12, 'Чтения')])[0][0].key, 'science_read_12')

    def test_schema_migration_is_additive_and_does_not_change_legacy_profiles(self):
        core = (ROOT / 'backend/app/database/core.py').read_text('utf-8')
        helper = (ROOT / 'backend/app/database/helpers.py').read_text('utf-8')
        self.assertIn('council_registered = db.Column(db.Boolean, nullable=False, default=True)', core)
        self.assertIn('"council_registered","BOOLEAN NOT NULL DEFAULT 1"', helper)
        with tempfile.TemporaryDirectory() as path:
            db_path = Path(path) / 'people.sqlite'
            with sqlite3.connect(db_path) as conn:
                conn.execute('CREATE TABLE students(id INTEGER PRIMARY KEY, full_name TEXT)')
                conn.execute("INSERT INTO students(id,full_name) VALUES(1,'Старый участник')")
                conn.commit()
            helpers_ast = ast.parse(helper)
            funcs = [n for n in helpers_ast.body if isinstance(n, ast.FunctionDef) and n.name in {'ensure_column','_sqlite_table_exists','_columns'}]
            context = {'sqlite3':sqlite3,'Path':Path}
            exec(compile(ast.Module(body=funcs, type_ignores=[]), '<migration>', 'exec'),context)
            ensure_column = context['ensure_column']
            ensure_column(db_path, 'students', 'council_registered', 'BOOLEAN NOT NULL DEFAULT 1')
            ensure_column(db_path, 'students', 'council_registered', 'BOOLEAN NOT NULL DEFAULT 1')
            with sqlite3.connect(db_path) as conn:
                self.assertEqual((1, 1), conn.execute('SELECT id,council_registered FROM students').fetchone())

    def test_signed_science_and_separate_council_permissions(self):
        science = (ROOT / 'backend/app/services/science_routes.py').read_text('utf-8')
        web = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
        logic = (ROOT / 'backend/app/services/applications.py').read_text('utf-8')
        self.assertIn("@science_bp.post('/api/register-author')", science)
        self.assertIn('_resolve_student_identity()', science)
        self.assertIn('_student_from_init_request(allow_science=True)', science)
        self.assertIn('not student.council_registered', web)
        self.assertIn('council_registered=False', logic)
        self.assertIn('student.council_registered = True', logic)
        self.assertIn('exclude_id=existing.id if existing else None', logic)

    def test_student_app_first_science_and_public_read_api(self):
        js = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text('utf-8')
        self.assertLess(js.index('data-action="science-entry"'), js.index('data-action="start-registration"'))
        self.assertIn("'/science/public/api/readings'", js)
        self.assertIn("'/science/api/register-author'", js)
        self.assertIn('data-submit="science-author-register"', js)
        self.assertIn('state.science_only', js)
        self.assertIn("case'science-author-register':scienceAuthorRegister(event)", js)

    def test_telegram_and_other_bots_use_verified_sender(self):
        tg = (ROOT / 'backend/app/handlers/science.py').read_text('utf-8')
        multi = (ROOT / 'backend/app/services/multi_messenger.py').read_text('utf-8')
        self.assertIn('message.from_user.id', tg)
        self.assertIn('register_science_participant(', tg)
        self.assertIn("if flow['kind'] == 'science':", multi)
        self.assertIn("if command == '/science_apply':", multi)
        self.assertIn('student_for(platform, user_id)', multi)
        self.assertIn('confirm_author_by_student', multi)


if __name__ == '__main__':
    unittest.main()
