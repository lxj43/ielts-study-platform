import json
from test_app import PlatformTest
from study import STAGES, advance, new_state


class StudyTest(PlatformTest):
    # Keep integration coverage inherited; these cases exercise the new gate.
    def state(self, uid=1):
        return json.loads(self.sql('SELECT state FROM study_sessions WHERE user_id=? AND page_id=1', (uid,))[0]['state'])

    def step(self, action, answer='', nonce=None):
        return self.post(self.a, '/learn/1/study', {'action': action, 'answer': answer, 'nonce': nonce or self.state()['nonce']})

    def test_gate_resume_wrong_retry_and_duplicate(self):
        self.post(self.a, '/learn/1')
        self.assertEqual(len(self.sql('SELECT * FROM progress')), 0)
        first = self.state()
        self.assertEqual(self.step('continue').status_code, 400)
        self.step('remember', nonce=first['nonce'])
        self.step('remember', nonce=first['nonce'])
        self.assertEqual(self.state()['memory_index'], 1)
        self.assertEqual(self.b.get('/learn/1/study').status_code, 302)
        self.post(self.a, '/learn/1')
        self.assertEqual(self.state()['memory_index'], 1)
        while self.state()['phase'] == 0:
            self.step('remember')
        before = self.state()
        q = before['question']
        self.step('answer', next(o for o in q['options'] if o != q['answer']))
        self.step('continue')
        self.assertEqual(self.state()['queue'][-1], q['word_id'])
        self.assertEqual(len(self.state()['passed']['zh_en']), 0)
        self.assertEqual(self.state()['mistakes'], 1)
        self.assertEqual(len(self.sql('SELECT * FROM progress')), 0)
        self.learn(self.a)
        self.assertEqual(self.state()['phase'], len(STAGES))
        self.assertEqual(len(self.sql('SELECT * FROM progress')), 1)
        self.assertTrue(all(len(ids) == 6 for ids in self.state()['passed'].values()))
        self.post(self.a, '/learn/1', {'restart': '1'})
        self.assertEqual(self.state()['phase'], 0)
        self.assertEqual(len(self.sql('SELECT * FROM progress')), 1)

    def test_spelling_and_material_coverage(self):
        from app import ROOT
        materials = json.loads((ROOT / 'data/study_materials.json').read_text())
        words = json.loads((ROOT / 'data/sample_words.json').read_text())
        vocabulary = {word['english'] for page in words['pages'] for word in page['words']}
        self.assertTrue(materials.keys() <= vocabulary)
        self.assertTrue(all(entry.get('example') for entry in materials.values()))
        word = dict(id=1, english='Ice cream', chinese='n. 冰淇淋', phonetic='')
        state = new_state([word])
        from study import start_round
        start_round(state, 3, {1: word}, {})
        advance(state, 'answer', ' ICE   CREAM ', {1: word}, {})
        self.assertTrue(state['feedback']['correct'])
        advance(state, 'continue', '', {1: word}, {})
        self.assertEqual(state['phase'], 4)

    def test_batches_and_memory_arrows(self):
        self.assertEqual(self.post(self.a, '/learn/1', {'count': '0'}).status_code, 400)
        self.post(self.a, '/learn/1', {'count': '2'})
        first_ids = self.state()['word_ids']
        self.assertEqual(len(first_ids), 2)
        self.step('previous')
        self.assertEqual(self.state()['memory_index'], 0)
        self.step('remember')
        self.step('previous')
        self.assertEqual(self.state()['memory_index'], 0)
        self.learn(self.a)
        self.assertEqual(len(self.sql('SELECT * FROM word_progress WHERE user_id=1')), 2)
        self.assertEqual(len(self.sql('SELECT * FROM progress')), 0)
        self.post(self.a, '/review', {'count': '10'})
        questions = json.loads(self.sql('SELECT questions FROM reviews')[0]['questions'])
        self.assertEqual({q['word_id'] for q in questions}, set(first_ids))
        self.post(self.a, '/learn/1', {'restart': '1', 'count': '4'})
        self.assertFalse(set(first_ids) & set(self.state()['word_ids']))
        self.learn(self.a)
        self.assertEqual(len(self.sql('SELECT * FROM progress')), 1)
        self.assertEqual(len(self.sql('SELECT * FROM word_progress WHERE user_id=2')), 0)

    def test_skip_spelling_and_legacy_migration(self):
        from study import start_round, migrate_sessions
        word = dict(id=1, english='test', chinese='n. 测试', phonetic='')
        state = new_state([word])
        start_round(state, 3, {1: word}, {})
        advance(state, 'skip', '', {1: word}, {})
        self.assertEqual(state['phase'], 4)
        self.assertEqual(state['skipped'], [1])
        self.assertEqual(state['passed']['spelling'], [])
        self.post(self.a, '/learn/1')
        old = self.state()
        old.pop('version')
        old['phase'] = 3
        old['passed'].update(usage=[], context=[])
        import sqlite3
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            db.execute('UPDATE study_sessions SET state=?', (json.dumps(old),))
            db.commit()
            migrate_sessions(db)
        migrated = self.state()
        self.assertEqual(migrated['phase'], 3)
        self.assertEqual(migrated['question']['stage'], 'spelling')
        self.assertNotIn('usage', migrated['passed'])
