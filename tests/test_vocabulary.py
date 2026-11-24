import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import ROOT, create_app
from study_helpers import complete_page
from library import read_vocabulary


class VocabularyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / 'test.sqlite3')

    def tearDown(self):
        self.temp.cleanup()

    def connection(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        return db

    def login(self, client, uid):
        client.get('/login')
        return self.post(client, '/login', {'user_id': str(uid)})

    def post(self, client, path, data=None):
        with client.session_transaction() as session:
            csrf = session['csrf']
        return client.post(path, data={'csrf': csrf, **(data or {})}, follow_redirects=True)

    def test_public_vocabulary_fixture(self):
        data = read_vocabulary(ROOT / 'data' / 'sample_words.json')
        self.assertEqual((data['page_count'], data['word_count']), (4, 24))
        self.assertEqual([page['number'] for page in data['pages']], [1, 2, 3, 4])
        self.assertTrue(all(word['phonetic'] for page in data['pages'] for word in page['words']))

    def test_formal_library_pages_filters_and_review(self):
        app = create_app({'TESTING': True, 'DATABASE': self.database})
        client = app.test_client()
        response = self.login(client, 1)
        self.assertIn('24', response.get_data(as_text=True))
        self.assertIn('词库总页数', response.get_data(as_text=True))
        for url in ['/learn', '/learn?q=academic', '/learn?q=奖学金', '/learn?status=todo', '/learn?status=done']:
            self.assertEqual(client.get(url).status_code, 200)
        filtered = client.get('/learn?q=academic').get_data(as_text=True)
        self.assertIn('显示 1 / 4 页', filtered)
        self.assertIn('显示 0 / 4 页', client.get('/learn?status=done').get_data(as_text=True))
        complete_page(self, client, 1)
        self.assertIn('显示 1 / 4 页', client.get('/learn?status=done').get_data(as_text=True))
        self.post(client, '/review', {'count': '100'})
        with self.connection() as db:
            review = db.execute('SELECT questions FROM reviews').fetchone()
            questions = json.loads(review['questions'])
            self.assertEqual(len(questions), 18)
            self.assertEqual(len({q['word_id'] for q in questions}), 6)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM words').fetchone()[0], 24)
        self.assertIn('第 4 页', client.get('/learn/4').get_data(as_text=True))
        create_app({'TESTING': True, 'DATABASE': self.database})
        with self.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pages').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM progress').fetchone()[0], 1)

    def test_legacy_migration_preserves_history_and_isolates_progress(self):
        # 模拟第一版真实 schema，包含已有进度、答卷、消息和积分。
        schema = (ROOT / 'schema.sql').read_text()
        schema = schema.replace("number INTEGER NOT NULL, title TEXT NOT NULL,\n    library_key TEXT NOT NULL DEFAULT 'demo', UNIQUE(library_key,number)",
                                'number INTEGER NOT NULL UNIQUE, title TEXT NOT NULL')
        schema = schema.replace(",\n    source_list INTEGER, source_no INTEGER", '')
        with self.connection() as db:
            db.executescript(schema)
            db.executescript("""
                INSERT INTO users(id,name,points) VALUES(1,'学员 A',3),(2,'学员 B',2);
                INSERT INTO pages(id,number,title) VALUES(1,1,'校园与学习');
                INSERT INTO words(id,page_id,english,chinese) VALUES(1,1,'academic','学术的');
                INSERT INTO progress VALUES(1,1,'2026-10-18'),(2,1,'2026-10-18');
                INSERT INTO reviews(id,user_id,questions,created_at) VALUES(1,1,'[]','2026-10-18');
                INSERT INTO battles(id,creator_id,questions,created_at) VALUES(1,1,'[]','2026-10-18');
                INSERT INTO notifications(user_id,message,battle_id,created_at) VALUES(2,'旧邀请',1,'2026-10-18');
            """)
        app = create_app({'TESTING': True, 'DATABASE': self.database})
        client = app.test_client()
        self.login(client, 1)
        with self.connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pages').fetchone()[0], 5)
            self.assertEqual(db.execute('SELECT library_key FROM pages WHERE id=1').fetchone()[0], 'demo')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM progress').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT points FROM users WHERE id=1').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], 1)
        self.assertIn('显示 0 / 4 页', client.get('/learn?status=done').get_data(as_text=True))
        self.assertEqual(client.get('/learn/1').status_code, 404)
        self.post(client, '/battles', {'count': '5'})
        self.post(client, '/review', {'count': '5'})
        with self.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM battles').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0], 1)
        backups = list((Path(self.database).parent / 'backups').glob('*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as backup:
            self.assertEqual(backup.execute('SELECT COUNT(*) FROM words').fetchone()[0], 1)
        create_app({'TESTING': True, 'DATABASE': self.database})
        self.assertEqual(len(list(backups[0].parent.glob('*.sqlite3'))), 1)


if __name__ == '__main__':
    unittest.main()
