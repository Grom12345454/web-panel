"""Offline regression checks for standalone science, modal and safe account removal."""
from pathlib import Path
import ast
import sqlite3
import tempfile
import types
import unittest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class PublicScienceUpgradeChecks(unittest.TestCase):
    def test_templates_are_parseable_and_modals_present(self):
        for filename in (ROOT / 'frontend/templates').rglob('*.html'):
            Environment().parse(filename.read_text(encoding='utf8'))
        admin = (ROOT/'frontend/templates/science/index.html').read_text(encoding='utf8')
        self.assertIn('<dialog id="science-create-dialog"', admin)
        self.assertIn('name="science_direction_options"', admin)
        self.assertIn('name="science_direction_custom"', admin)
        self.assertNotIn('name="direction_id"', admin)
        staff = (ROOT/'frontend/templates/staff/accounts.html').read_text(encoding='utf8')
        self.assertIn('staff-delete-dialog', staff)
        self.assertIn('name="confirm_login"', staff)
        self.assertIn('name="science_access"', staff)

    def test_public_route_keeps_personal_data_private(self):
        routes = (ROOT/'backend/app/services/science_routes.py').read_text(encoding='utf8')
        catalogue = routes.split('def public_catalogue():',1)[1].split('@science_bp.get',1)[0]
        self.assertNotIn('_student_from_init_request()',catalogue)
        fields = routes.split('def _public_reading(row):',1)[1].split('@science_bp.get',1)[0]
        self.assertNotIn('authors', fields)
        self.assertNotIn('telegram_username', fields)
        self.assertIn('science_allowed(current_user', routes)
        self.assertIn('can_read_science(current_user', routes)
        staff = (ROOT/'backend/app/services/staff_routes.py').read_text(encoding='utf8')
        self.assertIn("account.role != UserRole.STAFF.value", staff)
        self.assertIn("request.form.get('confirm_login') != account.email", staff)
        self.assertIn("db.session.delete(account)", staff)

    def test_nullable_direction_migration_is_transactional_idempotent(self):
        helper_source = (ROOT/'backend/app/database/helpers.py').read_text(encoding='utf8')
        tree = ast.parse(helper_source)
        node = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_make_science_direction_optional')
        code=compile(ast.Module(body=[node],type_ignores=[]),'migration','exec')
        with tempfile.TemporaryDirectory() as dirname:
            path=Path(dirname)/'people.db'
            with sqlite3.connect(path) as c:
                c.executescript('''
                PRAGMA foreign_keys=ON;
                CREATE TABLE directions (id INTEGER PRIMARY KEY);
                CREATE TABLE students (id INTEGER PRIMARY KEY);
                CREATE TABLE science_readings (
                    id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL,
                    category VARCHAR(80) NOT NULL, direction_id INTEGER NOT NULL REFERENCES directions(id),
                    description TEXT, held_at DATETIME, deadline DATETIME,
                    is_open BOOLEAN NOT NULL, created_at DATETIME NOT NULL);
                CREATE INDEX ix_science_readings_direction_id ON science_readings(direction_id);
                CREATE TABLE science_submissions (
                    id INTEGER PRIMARY KEY, reading_id INTEGER NOT NULL REFERENCES science_readings(id),
                    student_id INTEGER NOT NULL REFERENCES students(id),
                    direction_id INTEGER NOT NULL REFERENCES directions(id),
                    article_title VARCHAR(250) NOT NULL, author_count INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL);
                CREATE TABLE science_authors (id INTEGER PRIMARY KEY,
                    submission_id INTEGER NOT NULL REFERENCES science_submissions(id));
                INSERT INTO directions VALUES(1);INSERT INTO students VALUES(1);
                INSERT INTO science_readings VALUES(7, 'Historical reading', 'Section', 1, '', NULL, NULL, 1, '2026-10-01');
                INSERT INTO science_submissions VALUES(8,7,1,1,'Old article',1,'submitted','2026-10-01');
                INSERT INTO science_authors VALUES(9,8);
                ''')
            namespace={'sqlite3':sqlite3,'settings':types.SimpleNamespace(PEOPLE_DATABASE_PATH=path),
                       '_sqlite_table_exists':lambda p,table:sqlite3.connect(p).execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone() is not None}
            exec(code,namespace)
            migrate=namespace['_make_science_direction_optional']
            migrate()
            migrate()
            with sqlite3.connect(path) as c:
                c.execute('PRAGMA foreign_keys=ON')
                self.assertEqual([],c.execute('PRAGMA foreign_key_check').fetchall())
                self.assertEqual((7, 1),c.execute('SELECT id,direction_id FROM science_readings').fetchone())
                self.assertEqual((8, 1),c.execute('SELECT id,direction_id FROM science_submissions').fetchone())
                self.assertEqual((9, 8),c.execute('SELECT * FROM science_authors').fetchone())
                c.execute("INSERT INTO science_readings VALUES(10,'Global reading','Conference',NULL,'',NULL,NULL,1,'2026-10-26')")
                c.execute("INSERT INTO science_submissions VALUES(11,10,1,NULL,'Article',1,'submitted','2026-10-26')")
                self.assertEqual([],c.execute('PRAGMA foreign_key_check').fetchall())


if __name__=='__main__':unittest.main()
