import json
import sqlite3


def complete_page(test, client, page=1):
    test.post(client, f'/learn/{page}')
    with client.session_transaction() as session:
        uid = session['user_id']
    for _ in range(2000):
        with sqlite3.connect(test.database) as db:
            state = json.loads(db.execute('SELECT state FROM study_sessions WHERE user_id=? AND page_id=?', (uid, page)).fetchone()[0])
        if state['phase'] == 4:
            return
        action = 'remember' if state['phase'] == 0 else ('continue' if state['feedback'] else 'answer')
        response = test.post(client, f'/learn/{page}/study', {'nonce': state['nonce'], 'action': action, 'answer': state['question']['answer'] if state['question'] else ''})
        test.assertEqual(response.status_code, 200)
    raise AssertionError('Study did not complete')
