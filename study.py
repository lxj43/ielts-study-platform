"""可续学的逐题背诵状态机；完成状态及已学标记只由服务端推进。"""
import json
import random
import re
import secrets

from flask import abort, g, redirect, render_template, request, url_for


STAGES = [('overview', '整体记忆'), ('zh_en', '中译英'), ('en_zh', '英译中'),
          ('spelling', '拼写过关')]
POS = {
    'n': ('名词', '常作主语或宾语，表示事物、人物或概念。'),
    'v': ('动词', '表示动作或状态；使用时注意时态、主谓一致及是否需要宾语。'),
    'adj': ('形容词', '通常修饰名词，或在系动词后作表语。'),
    'adv': ('副词', '通常修饰动词、形容词或其他副词。'),
    'phrase': ('短语', '作为完整表达学习，注意词序和固定组成。'),
    'num': ('数词', '表示数量或次序。'),
    'prep': ('介词', '通常与名词或代词构成介词短语。'),
    'int': ('感叹词', '表达感叹、呼唤等语气。'),
}


def normalize_answer(text):
    return re.sub(r'\s+', ' ', text.strip().casefold())


def usage(word):
    match = re.match(r'^\s*(n|v|adj|adv|phrase|num|prep|int)\.', word['chinese'])
    key = match[1] if match else 'phrase'
    name, explanation = POS[key]
    return name, explanation


def make_study_question(word, stage, words, materials):
    material = materials.get(word['english'].casefold(), {})
    question = {'word_id': word['id'], 'stage': stage, 'options': [],
                'english': word['english'], 'chinese': word['chinese'], 'phonetic': word['phonetic']}
    if stage == 'zh_en':
        question.update(prompt=word['chinese'], instruction='选择对应的英文单词或短语', answer=word['english'])
        pool = {w['english'] for w in words} - {question['answer']}
    elif stage == 'en_zh':
        question.update(prompt=word['english'], instruction='选择对应的中文释义', answer=word['chinese'])
        pool = {w['chinese'] for w in words} - {question['answer']}
    elif stage == 'usage':
        name, explanation = usage(word)
        question.update(prompt=word['english'], instruction='按原词表的首个义项，选择主要词性与基础用法',
                        answer=f'{name}：{explanation}', explanation=f'词表首个义项：{word["chinese"]}')
        pool = {f'{n}：{e}' for n, e in POS.values()} - {question['answer']}
    elif stage == 'context':
        example = material.get('example')
        if example:
            question.update(prompt=example, instruction=f'结合例句，选择 {word["english"]} 对应的词表释义',
                            answer=word['chinese'], kind='例句识义',
                            explanation=material.get('translation', ''), source=material.get('example_source', '教学补充'))
            pool = {w['chinese'] for w in words} - {question['answer']}
        else:
            # 无可靠例句时使用明确标注的英文释义，不伪装成自然例句。
            definition = material.get('definition')
            question.update(prompt=definition or word['chinese'], instruction='阅读释义语境，选择对应的英文词条',
                            answer=word['english'], kind='英文释义' if definition else '词义巩固',
                            source=material.get('definition_source', '原词表'), explanation=word['chinese'])
            pool = {w['english'] for w in words} - {question['answer']}
    else:
        question.update(prompt=word['chinese'], instruction='不看提示，完整拼写英文单词或短语', answer=word['english'])
        pool = set()
    if stage != 'spelling':
        question['options'] = random.sample(sorted(pool), min(3, len(pool))) + [question['answer']]
        random.shuffle(question['options'])
    return question


def new_state(words):
    return {'version': 2, 'skipped': [], 'phase': 0, 'memory_index': 0, 'word_ids': [w['id'] for w in words],
            'queue': [], 'passed': {k: [] for k, _ in STAGES[1:]}, 'mistakes': 0,
            'feedback': None, 'question': None, 'nonce': secrets.token_hex(16)}


def migrate_sessions(connection):
    """保留旧版记忆、互译和拼写进度，移除两轮额外考核。"""
    for row in connection.execute('SELECT user_id,page_id,state FROM study_sessions').fetchall():
        state = json.loads(row['state'])
        if state.get('version') == 2:
            continue
        old_phase = state['phase']
        state['passed'] = {k: state['passed'].get(k, []) for k, _ in STAGES[1:]}
        state.update(version=2, skipped=[])
        if old_phase in (3, 4):
            words = {w['id']: dict(w) for w in connection.execute('SELECT * FROM words WHERE page_id=?', (row['page_id'],))}
            state['feedback'] = None
            start_round(state, 3, words, {})
        elif old_phase >= 5:
            state['phase'] = old_phase - 2
        state['nonce'] = secrets.token_hex(16)
        connection.execute('UPDATE study_sessions SET state=? WHERE user_id=? AND page_id=?',
                           (json.dumps(state, ensure_ascii=False), row['user_id'], row['page_id']))
    connection.commit()


def begin_session(connection, user_id, page_id, words, timestamp, restart=False, count=None):
    connection.execute('BEGIN IMMEDIATE')
    try:
        row = connection.execute('SELECT state FROM study_sessions WHERE user_id=? AND page_id=?', (user_id, page_id)).fetchone()
        if not row or restart:
            completed = {r['word_id'] for r in connection.execute('SELECT word_id FROM word_progress WHERE user_id=?', (user_id,))}
            remaining = [w for w in words if w['id'] not in completed]
            selected = (remaining or list(words))[:count] if count else (remaining or list(words))
            state = json.dumps(new_state(selected), ensure_ascii=False)
            connection.execute('''INSERT INTO study_sessions(user_id,page_id,state,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(user_id,page_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at''',
                               (user_id, page_id, state, timestamp))
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def start_round(state, phase, words, materials):
    state['phase'] = phase
    state['queue'] = state['word_ids'].copy()
    random.shuffle(state['queue'])
    state['question'] = make_study_question(words[state['queue'][0]], STAGES[phase][0], list(words.values()), materials)


def advance(state, action, submitted, words, materials):
    """一次 POST 只允许推进一个状态；错误题在本轮队尾重新出现。"""
    phase = state['phase']
    if phase == len(STAGES):
        return
    if phase == 0:
        if action == 'previous':
            state['memory_index'] = max(0, state['memory_index'] - 1)
            state['nonce'] = secrets.token_hex(16)
            return
        if action != 'remember':
            abort(400, description='请先完成整体记忆。')
        state['memory_index'] += 1
        if state['memory_index'] == len(state['word_ids']):
            start_round(state, 1, words, materials)
    elif action == 'skip' and phase == 3:
        wid = state['queue'].pop(0)
        state.setdefault('skipped', []).append(wid)
        state['feedback'] = None
        if state['queue']:
            state['question'] = make_study_question(words[state['queue'][0]], 'spelling', list(words.values()), materials)
        else:
            state.update(phase=len(STAGES), question=None)
    elif state['feedback']:
        if action != 'continue':
            abort(400, description='请先阅读本题反馈。')
        wid = state['queue'].pop(0)
        if state['feedback']['correct']:
            state['passed'][STAGES[phase][0]].append(wid)
        else:
            state['queue'].append(wid)
        state['feedback'] = None
        if state['queue']:
            state['question'] = make_study_question(words[state['queue'][0]], STAGES[phase][0], list(words.values()), materials)
        elif phase < len(STAGES) - 1:
            start_round(state, phase + 1, words, materials)
        else:
            state.update(phase=len(STAGES), question=None)
    else:
        if action != 'answer':
            abort(400, description='请先作答本题。')
        question = state['question']
        if not submitted.strip() or len(submitted) > 1000 or (question['options'] and submitted not in question['options']):
            abort(400, description='请输入答案或选择有效选项。')
        correct = normalize_answer(submitted) == normalize_answer(question['answer'])
        state['mistakes'] += int(not correct)
        state['feedback'] = {'correct': correct, 'submitted': submitted}
    state['nonce'] = secrets.token_hex(16)


def register_study_routes(app, db, login_required, library_key, materials, now):
    @app.route('/learn/<int:page_id>/study', methods=['GET', 'POST'])
    @login_required
    def study_session(page_id):
        connection = db()
        if request.method == 'POST':
            connection.execute('BEGIN IMMEDIATE')
        try:
            page = connection.execute('SELECT * FROM pages WHERE id=? AND library_key=?', (page_id, library_key)).fetchone()
            if not page:
                abort(404)
            row = connection.execute('SELECT * FROM study_sessions WHERE user_id=? AND page_id=?', (g.user['id'], page_id)).fetchone()
            if not row:
                if request.method == 'POST':
                    connection.rollback()
                return redirect(url_for('learn_page', page_id=page_id))
            state = json.loads(row['state'])
            words = {w['id']: dict(w) for w in connection.execute('SELECT * FROM words WHERE page_id=? ORDER BY id', (page_id,))}
            if request.method == 'POST':
                if secrets.compare_digest(request.form.get('nonce', ''), state['nonce']):
                    advance(state, request.form.get('action'), request.form.get('answer', ''), words, materials)
                    connection.execute('UPDATE study_sessions SET state=?,updated_at=? WHERE user_id=? AND page_id=?',
                                       (json.dumps(state, ensure_ascii=False), now(), g.user['id'], page_id))
                    if state['phase'] == len(STAGES):
                        connection.executemany('INSERT OR IGNORE INTO word_progress(user_id,word_id,learned_at) VALUES(?,?,?)', [(g.user['id'], wid, now()) for wid in state['word_ids']])
                        completed = connection.execute('SELECT COUNT(*) FROM word_progress wp JOIN words w ON w.id=wp.word_id WHERE wp.user_id=? AND w.page_id=?', (g.user['id'], page_id)).fetchone()[0]
                        if completed == len(words):
                            connection.execute('INSERT OR IGNORE INTO progress(user_id,page_id,learned_at) VALUES(?,?,?)', (g.user['id'], page_id, now()))
                connection.commit()
                return redirect(url_for('study_session', page_id=page_id))
        except Exception:
            if request.method == 'POST':
                connection.rollback()
            raise
        memory_word = words[state['word_ids'][min(state['memory_index'], len(state['word_ids']) - 1)]]
        mastered = sum(len(ids) for ids in state['passed'].values())
        next_page = connection.execute('SELECT id FROM pages WHERE library_key=? AND number>? ORDER BY number LIMIT 1', (library_key, page['number'])).fetchone()
        return render_template('study.html', page=page, state=state, stages=STAGES, total=len(state['word_ids']),
                               memory_word=memory_word, material=materials.get(memory_word['english'].casefold(), {}),
                               word_usage=usage(memory_word), mastered=mastered, next_page=next_page)
