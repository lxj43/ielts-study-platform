import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from study_helpers import complete_page

DEMO_FILE = str(Path(__file__).resolve().parents[1] / 'data' / 'demo_words.json')


class PlatformTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.database, 'SECRET_KEY': 'test-only', 'VOCABULARY_FILE': DEMO_FILE})
        self.a, self.b = self.app.test_client(), self.app.test_client()
        self.login(self.a, 1)
        self.login(self.b, 2)

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, query, args=()):
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(query, args).fetchall()

    def post(self, client, path, data=None, follow=True):
        with client.session_transaction() as session:
            csrf = session['csrf']
        return client.post(path, data={'csrf': csrf, **(data or {})}, follow_redirects=follow)

    def login(self, client, uid):
        client.get('/login')
        response = self.post(client, '/login', {'user_id': str(uid)})
        self.assertEqual(response.status_code, 200)

    def learn(self, client, page=1):
        complete_page(self, client, page)

    def battle(self, count=2):
        self.learn(self.a)
        self.learn(self.b)
        response = self.post(self.a, '/battles', {'count': str(count)}, follow=False)
        self.assertEqual(response.status_code, 302)
        return self.sql('SELECT * FROM battles ORDER BY id DESC')[0]

    def answers(self, row, correct=True):
        questions = json.loads(row['questions'])
        answers = {}
        for i, q in enumerate(questions):
            if correct:
                answer = q['answer']
            elif q['options']:
                answer = next(o for o in q['options'] if o != q['answer'])
            else:
                answer = 'incorrect'
            answers[f'answer_{i}'] = answer
        return answers

    def test_desktop_review_link_and_health(self):
        client = self.app.test_client()
        self.assertEqual(client.get('/review').location, '/login?next=review')
        client.get('/login?next=review')
        response = self.post(client, '/login?next=review', {'user_id': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request.path, '/review')
        with patch.dict('os.environ', {'IELTS_DESKTOP_SESSION': 'test-launch-token'}):
            headers = {'X-IELTS-Desktop': 'test-launch-token'}
            self.assertEqual(client.get('/_desktop/health').status_code, 404)
            self.assertEqual(client.get('/_desktop/health', headers=headers).status_code, 204)

    def test_pages_render_and_auth(self):
        self.assertEqual(self.app.test_client().get('/').status_code, 302)
        for path in ['/', '/learn', '/learn/1', '/review', '/battles', '/messages']:
            self.assertEqual(self.a.get(path).status_code, 200, path)
        self.assertEqual(self.a.get('/learn/999').status_code, 404)
        self.assertEqual(self.post(self.a, '/login', {'user_id': '999'}).status_code, 400)

    def test_independent_progress_and_common_pool(self):
        self.learn(self.a, 1)
        self.learn(self.a, 2)
        self.learn(self.a, 1)
        self.assertEqual(len(self.sql('SELECT * FROM progress WHERE user_id=1')), 2)
        self.assertEqual(len(self.sql('SELECT * FROM progress WHERE user_id=2')), 0)
        self.post(self.a, '/battles', {'count': '100'})
        self.assertEqual(len(self.sql('SELECT * FROM battles')), 0)
        self.learn(self.b, 1)
        self.post(self.b, '/battles', {'count': '100'})
        questions = json.loads(self.sql('SELECT * FROM battles')[0]['questions'])
        self.assertEqual(len(questions), 18)
        self.assertEqual(len({q['word_id'] for q in questions}), 6)
        self.assertTrue(all(q['word_id'] <= 6 for q in questions))

    def review_state(self):
        return json.loads(self.sql('SELECT state FROM review_sessions ORDER BY review_id DESC')[0]['state'])

    def review_answer(self, path, action, answer='', nonce=None):
        data = {'action': action, 'answer': answer, 'nonce': nonce or self.review_state()['nonce']}
        return self.post(self.a, path, data)

    def test_review_ownership_and_immutable_results(self):
        self.post(self.a, '/review', {'count': '4'})
        self.assertEqual(len(self.sql('SELECT * FROM reviews')), 0)
        self.learn(self.a)
        self.post(self.a, '/review', {'count': '2'})
        row = self.sql('SELECT * FROM reviews')[0]
        path = f'/review/{row["id"]}'
        questions = json.loads(row['questions'])
        self.assertEqual(self.b.get(path).status_code, 404)
        self.assertEqual(self.post(self.b, path, {'action': 'answer'}).status_code, 404)
        self.assertEqual(self.a.get(path).status_code, 200)
        self.assertEqual(self.post(self.a, '/review', {'count': '1'}, follow=False).location, path)
        self.assertEqual(len(self.sql('SELECT * FROM reviews')), 1)

        nonce = self.review_state()['nonce']
        wrong = next(option for option in questions[0]['options'] if option != questions[0]['answer'])
        self.assertEqual(self.review_answer(path, 'answer', 'invalid').status_code, 400)
        self.assertIn('本轮稍后重练', self.review_answer(path, 'answer', wrong).get_data(as_text=True))
        self.review_answer(path, 'answer', questions[0]['answer'], nonce)
        self.assertFalse(self.review_state()['feedback']['correct'])
        self.assertIn('继续本次复习', self.a.get('/review').get_data(as_text=True))
        self.review_answer(path, 'continue')
        self.assertEqual(self.review_state()['queue'], [1, 0, 2, 3, 4, 5])

        for index in [1, 0, 2, 3, 4, 5]:
            answer = questions[index]['answer']
            if index >= 4:
                answer = ' ' + answer.upper() + ' '
            response = self.review_answer(path, 'answer', answer)
            self.assertEqual(response.status_code, 200)
            if index == 4:
                self.assertEqual(len(self.sql('SELECT * FROM review_word_days')), 1)
                self.assertIn('本组已复习 1 / 2 词', response.get_data(as_text=True))
            if index != 5:
                self.review_answer(path, 'continue')
        self.assertIn('本组复习完成', response.get_data(as_text=True))
        self.review_answer(path, 'answer', 'incorrect', nonce)
        result = json.loads(self.sql('SELECT result FROM reviews')[0]['result'])
        self.assertEqual((result['correct'], result['total'], result['mistakes']), (5, 6, 1))
        self.assertEqual(len(self.sql('SELECT * FROM review_word_days')), 2)
        self.assertNotIn('复习练习 · 2 词', self.b.get('/review').get_data(as_text=True))

    def test_review_daily_counts_and_legacy_results(self):
        self.learn(self.a)
        with patch('app.now', return_value='2026-10-21T12:00:00+08:00'):
            self.sql('INSERT INTO review_word_days VALUES(1,1,?), (1,1,?), (1,2,?)',
                     ('2026-10-18', '2026-10-21', '2026-10-21'))
            legacy = dict(details=[
                dict(word_id=word_id, category=category, correct=word_id != 4 or category != 'spelling')
                for word_id in (1, 3, 4) for category in ('zh_en', 'en_zh', 'spelling')
            ])
            self.sql('INSERT INTO reviews(user_id,questions,result,created_at) VALUES(1,?,?,?)',
                     ('[]', json.dumps(legacy), '2026-10-18T12:00:00+08:00'))
            page = self.a.get('/review').get_data(as_text=True)
            for text in ('今日已复习</dt><dd>2', '累计复习</dt><dd>4', '日均复习</dt><dd>1.0',
                         '已复习</dt><dd>3', '待复习</dt><dd>3'):
                self.assertIn(text, page)
            self.post(self.a, '/review', {'count': '3'})
            questions = json.loads(self.sql('SELECT questions FROM reviews ORDER BY id DESC')[0]['questions'])
            self.assertEqual({q['word_id'] for q in questions}, {4, 5, 6})

    def test_legacy_review_can_still_be_submitted(self):
        self.learn(self.a)
        self.post(self.a, '/review', {'count': '2'})
        self.sql('DELETE FROM review_sessions')
        row = self.sql('SELECT * FROM reviews')[0]
        path = f'/review/{row["id"]}'
        response = self.post(self.a, path, self.answers(row))
        self.assertEqual(response.status_code, 200)
        self.assertIn('100.0%', response.get_data(as_text=True))
        self.assertIn('今日已复习</dt><dd>2', self.a.get('/review').get_data(as_text=True))

    def test_battle_scoring_messages_and_no_double_points(self):
        row = self.battle()
        bid = row['id']
        path = f'/battles/{bid}/quiz'
        self.assertEqual(self.b.get(path).status_code, 200)
        self.assertEqual(self.post(self.a, path, self.answers(row)).status_code, 200)
        self.assertEqual(self.a.get(f'/battles/{bid}/result').status_code, 302)
        self.assertEqual(self.sql('SELECT points FROM users WHERE id=1')[0]['points'], 0)
        messages = self.sql('SELECT * FROM notifications WHERE user_id=2')
        self.assertEqual(len(messages), 2)
        self.assertIn('中译英 2/2', messages[-1]['message'])
        self.post(self.b, path, self.answers(row, False))
        self.assertEqual(self.sql('SELECT winner_id FROM battles')[0]['winner_id'], 1)
        self.assertEqual(self.sql('SELECT points FROM users WHERE id=1')[0]['points'], 1)
        self.assertEqual(self.a.get(f'/battles/{bid}/result').status_code, 200)
        for client in [self.a, self.b]:
            self.post(client, path, self.answers(row))
        self.assertEqual(len(self.sql('SELECT * FROM attempts')), 2)
        self.assertEqual(self.sql('SELECT points FROM users WHERE id=1')[0]['points'], 1)
        self.post(self.b, '/messages')
        self.assertEqual(len(self.sql('SELECT * FROM notifications WHERE user_id=2 AND seen=0')), 0)

    def test_tie_and_multiple_battles(self):
        for _ in range(2):
            row = self.battle(1)
            path = f'/battles/{row["id"]}/quiz'
            self.post(self.a, path, self.answers(row))
            self.post(self.b, path, self.answers(row))
        self.assertEqual(len(self.sql('SELECT * FROM battles WHERE settled=1 AND winner_id IS NULL')), 2)
        self.assertEqual(sum(r['points'] for r in self.sql('SELECT * FROM users')), 0)

    def test_missing_answers_csrf_and_answer_hiding(self):
        row = self.battle(1)
        path = f'/battles/{row["id"]}/quiz'
        response = self.a.get(path)
        self.assertNotIn('"answer":', response.get_data(as_text=True))
        self.assertEqual(self.post(self.a, path, {}).status_code, 400)
        self.assertEqual(len(self.sql('SELECT * FROM attempts')), 0)
        self.assertEqual(self.a.post(path, data=self.answers(row)).status_code, 400)

    def test_data_survives_app_restart(self):
        self.learn(self.a)
        create_app({'TESTING': True, 'DATABASE': self.database, 'VOCABULARY_FILE': DEMO_FILE})
        self.assertEqual(len(self.sql('SELECT * FROM progress')), 1)
        self.assertEqual(len(self.sql('SELECT * FROM words')), 24)


if __name__ == '__main__':
    unittest.main()
