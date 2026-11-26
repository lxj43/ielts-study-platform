import json
import os
import random
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from library import install_vocabulary, read_vocabulary
from review import (
    advance_review, choose_words, current_review, new_review_state, review_activity,
    review_result, review_stats, review_word_count,
)
from study import begin_session, migrate_sessions, normalize_answer, register_study_routes


ROOT = Path(__file__).resolve().parent
CATEGORIES = {'zh_en': '中译英', 'en_zh': '英译中', 'spelling': '单词拼写'}
USERS = [(1, '学员 A'), (2, '学员 B')]


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(DATABASE=str(ROOT / 'instance' / 'ielts.sqlite3'),
                      VOCABULARY_FILE=os.environ.get('IELTS_VOCABULARY_FILE', str(ROOT / 'data' / 'sample_words.json')),
                      MAX_CONTENT_LENGTH=2 * 1024 * 1024)
    if test_config:
        app.config.update(test_config)
    vocabulary = read_vocabulary(app.config['VOCABULARY_FILE'])
    library_key = vocabulary['key']
    materials = json.loads((ROOT / 'data' / 'study_materials.json').read_text(encoding='utf-8'))
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    secret_path = Path(app.instance_path) / 'secret.key'
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32))
    app.secret_key = os.environ.get('SECRET_KEY') or secret_path.read_text().strip()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=15)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys = ON')
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        connection = g.pop('db', None)
        if connection is not None:
            connection.close()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                destination = 'review' if request.endpoint == 'review' else None
                return redirect(url_for('login', next=destination))
            return view(*args, **kwargs)
        return wrapped

    @app.before_request
    def load_user():
        if request.endpoint == 'desktop_health':
            return
        g.user = db().execute('SELECT * FROM users WHERE id=?', (session.get('user_id'),)).fetchone()
        session.setdefault('csrf', secrets.token_hex(24))
        if request.method == 'POST' and not secrets.compare_digest(request.form.get('csrf', ''), session['csrf']):
            abort(400, description='页面已过期，请刷新后再试。')

    @app.context_processor
    def common():
        unread = db().execute('SELECT COUNT(*) FROM notifications WHERE user_id=? AND seen=0', (g.user['id'],)).fetchone()[0] if g.user else 0
        return dict(categories=CATEGORIES, unread=unread, library=vocabulary)

    def integer(value, default=10, maximum=100):
        try:
            return max(1, min(maximum, int(value)))
        except (TypeError, ValueError):
            return default

    def notify(user_id, message, battle_id):
        db().execute('INSERT INTO notifications(user_id,message,battle_id,created_at) VALUES(?,?,?,?)', (user_id, message, battle_id, now()))

    def learned_words(user_id):
        return db().execute("""SELECT w.* FROM words w JOIN pages p ON p.id=w.page_id
            WHERE p.library_key=? AND (EXISTS(SELECT 1 FROM progress pr WHERE pr.page_id=w.page_id AND pr.user_id=?)
            OR EXISTS(SELECT 1 FROM word_progress wp WHERE wp.word_id=w.id AND wp.user_id=?))""",
            (library_key, user_id, user_id)).fetchall()

    def make_questions(words, count=None, *, chosen=None):
        if chosen is None:
            chosen = random.sample(list(words), min(count, len(words)))
        questions = []
        # 每个单词测试三项，确保每一场都有可比较的分项成绩。
        for category in CATEGORIES:
            for word in chosen:
                correct = word['english'] if category != 'en_zh' else word['chinese']
                options = []
                if category != 'spelling':
                    field = 'english' if category == 'zh_en' else 'chinese'
                    pool = list({w[field] for w in words if w[field] != correct})
                    options = random.sample(pool, min(3, len(pool))) + [correct]
                    random.shuffle(options)
                questions.append(dict(word_id=word['id'], category=category, english=word['english'], chinese=word['chinese'], phonetic=word['phonetic'], answer=correct, options=options))
        return questions

    def grade(questions):
        details = []
        scores = {key: {'correct': 0, 'total': 0} for key in CATEGORIES}
        for index, question in enumerate(questions):
            answer = request.form.get(f'answer_{index}', '').strip()
            if not answer or (question['options'] and answer not in question['options']):
                abort(400, description='请完成所有题目，并使用试卷提供的选项。返回上一页后继续填写。')
            correct = normalize_answer(answer) == normalize_answer(question['answer'])
            scores[question['category']]['total'] += 1
            scores[question['category']]['correct'] += int(correct)
            details.append(dict(**question, submitted=answer, correct=correct))
        return dict(scores=scores, details=details, correct=sum(s['correct'] for s in scores.values()), total=len(questions))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            if request.form.get('user_id') not in ('1', '2'):
                abort(400)
            uid = int(request.form['user_id'])
            session.clear()
            session.update(user_id=uid, csrf=secrets.token_hex(24))
            destination = 'review' if request.args.get('next') == 'review' else 'dashboard'
            return redirect(url_for(destination))
        return render_template('login.html', users=USERS)

    @app.get('/_desktop/health')
    def desktop_health():
        token = os.environ.get('IELTS_DESKTOP_SESSION')
        if not token or not secrets.compare_digest(request.headers.get('X-IELTS-Desktop', '').encode(), token.encode()):
            abort(404)
        return '', 204

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @login_required
    def dashboard():
        total_pages = vocabulary['page_count']
        done_pages = db().execute('''SELECT COUNT(*) FROM progress pr JOIN pages p ON p.id=pr.page_id
                                    WHERE pr.user_id=? AND p.library_key=?''', (g.user['id'], library_key)).fetchone()[0]
        total_words = vocabulary['word_count']
        word_ids = {word['id'] for word in learned_words(g.user['id'])}
        done_words = len(word_ids)
        activity = review_activity(db(), g.user['id'], word_ids)
        today = now()[:10]
        reviews = sum(day == today for day, _ in activity)
        scores = db().execute('SELECT * FROM users ORDER BY points DESC,id').fetchall()
        return render_template('dashboard.html', total_pages=total_pages, done_pages=done_pages, total_words=total_words, done_words=done_words, reviews=reviews, scores=scores)

    @app.get('/learn')
    @login_required
    def learn():
        status = request.args.get('status', 'all')
        query = request.args.get('q', '').strip()[:100]
        conditions, params = ['p.library_key=?'], [g.user['id'], library_key]
        if status in ['done', 'todo']:
            conditions.append('pr.learned_at IS ' + ('NOT NULL' if status == 'done' else 'NULL'))
        if query:
            conditions.append('''(p.title LIKE ? OR CAST(p.number AS TEXT)=?
                OR EXISTS(SELECT 1 FROM words sw WHERE sw.page_id=p.id AND (sw.english LIKE ? OR sw.chinese LIKE ?)))''')
            params.extend([f'%{query}%', query, f'%{query}%', f'%{query}%'])
        pages = db().execute('''SELECT p.*,COUNT(w.id) word_count,pr.learned_at,
            (SELECT state FROM study_sessions ss WHERE ss.user_id=pr_user.id AND ss.page_id=p.id) study_state FROM pages p
            JOIN users pr_user ON pr_user.id=?
            LEFT JOIN words w ON w.page_id=p.id LEFT JOIN progress pr ON pr.page_id=p.id AND pr.user_id=?
            WHERE ''' + ' AND '.join(conditions) + ' GROUP BY p.id ORDER BY p.number', [g.user['id']] + params).fetchall()
        return render_template('learn.html', pages=pages, status=status, query=query)

    @app.route('/learn/<int:page_id>', methods=['GET', 'POST'])
    @login_required
    def learn_page(page_id):
        page = db().execute('SELECT * FROM pages WHERE id=? AND library_key=?', (page_id, library_key)).fetchone()
        if not page:
            abort(404)
        words = db().execute('SELECT * FROM words WHERE page_id=? ORDER BY id', (page_id,)).fetchall()
        if request.method == 'POST':
            try:
                count = int(request.form.get('count', len(words)))
            except ValueError:
                abort(400, description='请输入有效词数。')
            if not 1 <= count <= len(words):
                abort(400, description='词数应在 1 到本页词数之间。')
            begin_session(db(), g.user['id'], page_id, words, now(), restart=request.form.get('restart') == '1', count=count)
            return redirect(url_for('study_session', page_id=page_id))
        learned = db().execute('SELECT 1 FROM progress WHERE user_id=? AND page_id=?', (g.user['id'], page_id)).fetchone()
        previous = db().execute('SELECT id FROM pages WHERE library_key=? AND number<? ORDER BY number DESC LIMIT 1', (library_key, page['number'])).fetchone()
        following = db().execute('SELECT id FROM pages WHERE library_key=? AND number>? ORDER BY number LIMIT 1', (library_key, page['number'])).fetchone()
        study = db().execute('SELECT state FROM study_sessions WHERE user_id=? AND page_id=?', (g.user['id'], page_id)).fetchone()
        study = json.loads(study['state']) if study else None
        return render_template('page.html', page=page, words=words, learned=learned, previous=previous, following=following, study=study)

    @app.route('/review', methods=['GET', 'POST'])
    @login_required
    def review():
        connection = db()
        user_id = g.user['id']
        if request.method == 'POST':
            connection.execute('BEGIN IMMEDIATE')
        words = learned_words(user_id)
        active = current_review(connection, user_id)
        if request.method == 'POST' and active:
            connection.rollback()
            return redirect(url_for('review_quiz', review_id=active['id']))
        activity = review_activity(connection, user_id, {word['id'] for word in words})
        if request.method == 'POST':
            if not words:
                connection.rollback()
                flash('先完成一批背诵，再来开启复习。', 'info')
                return redirect(url_for('learn'))
            chosen = choose_words(words, integer(request.form.get('count')), activity)
            options_pool = words
            if len(words) < 4:
                options_pool = connection.execute(
                    'SELECT w.* FROM words w JOIN pages p ON p.id=w.page_id WHERE p.library_key=?',
                    (library_key,),
                ).fetchall()
            questions = make_questions(options_pool, chosen=chosen)
            cursor = connection.execute('INSERT INTO reviews(user_id,questions,created_at) VALUES(?,?,?)',
                                        (user_id, json.dumps(questions, ensure_ascii=False), now()))
            connection.execute('INSERT INTO review_sessions(review_id,state) VALUES(?,?)',
                               (cursor.lastrowid, json.dumps(new_review_state(questions))))
            connection.commit()
            return redirect(url_for('review_quiz', review_id=cursor.lastrowid))

        today = date.fromisoformat(now()[:10])
        stats = review_stats(activity, today, len(words))
        active_progress = None
        if active:
            questions = json.loads(active['questions'])
            state = json.loads(active['state'])
            active_progress = {
                'id': active['id'], 'total': len(questions) // len(CATEGORIES),
                'completed': review_word_count(questions, state, len(CATEGORIES)),
                'round': CATEGORIES[questions[state['queue'][0]]['category']],
            }
        rows = connection.execute("""
            SELECT r.*, s.review_id AS guided FROM reviews r
            LEFT JOIN review_sessions s ON s.review_id=r.id
            WHERE r.user_id=? ORDER BY r.id DESC LIMIT 20
        """, (user_id,)).fetchall()
        history = []
        for row in rows:
            result = json.loads(row['result']) if row['result'] else {}
            history.append({
                'id': row['id'], 'finished': bool(result), 'guided': row['guided'],
                'timestamp': result.get('finished_at', row['created_at']),
                'word_count': len({q['word_id'] for q in json.loads(row['questions'])}),
            })
        return render_template('review.html', word_count=len(words), history=history, stats=stats,
                               active=active_progress, today=today_label(today))

    def today_label(today):
        return f'{today.month}月{today.day}日 · 周{"一二三四五六日"[today.weekday()]}'

    @app.route('/review/<int:review_id>', methods=['GET', 'POST'])
    @login_required
    def review_quiz(review_id):
        connection = db()
        user_id = g.user['id']
        if request.method == 'POST':
            connection.execute('BEGIN IMMEDIATE')
        row = connection.execute("""
            SELECT r.*, s.state FROM reviews r LEFT JOIN review_sessions s ON s.review_id=r.id
            WHERE r.id=? AND r.user_id=?
        """, (review_id, user_id)).fetchone()
        if not row:
            abort(404)
        if row['result']:
            result = json.loads(row['result'])
            if row['state']:
                return render_template('review_complete.html', result=result)
            return render_template('result.html', result=result, title='复习成绩', battle=None)
        questions = json.loads(row['questions'])
        if not row['state']:
            if request.method == 'POST':
                result = grade(questions)
                result['finished_at'] = now()
                result['reviewed_on'] = result['finished_at'][:10]
                connection.execute('UPDATE reviews SET result=? WHERE id=?',
                                   (json.dumps(result, ensure_ascii=False), review_id))
                connection.commit()
                return redirect(url_for('review_quiz', review_id=review_id))
            return render_template('quiz.html', questions=questions, title='复习答卷', subtitle='完成答卷后查看成绩与解析。')

        state = json.loads(row['state'])
        if request.method == 'POST':
            if secrets.compare_digest(request.form.get('nonce', ''), state['nonce']):
                word_id, changed = advance_review(
                    state, questions, request.form.get('action'), request.form.get('answer', ''),
                )
                if not changed:
                    abort(400, description='请使用当前题目提供的选项或输入有效拼写。')
                timestamp = now()
                if word_id is not None:
                    connection.execute('INSERT OR IGNORE INTO review_word_days VALUES(?,?,?)',
                                       (user_id, word_id, timestamp[:10]))
                connection.execute('UPDATE review_sessions SET state=? WHERE review_id=?',
                                   (json.dumps(state, ensure_ascii=False), review_id))
                if not state['queue']:
                    result = review_result(state, questions, CATEGORIES, timestamp)
                    connection.execute('UPDATE reviews SET result=? WHERE id=?',
                                       (json.dumps(result, ensure_ascii=False), review_id))
                connection.commit()
            return redirect(url_for('review_quiz', review_id=review_id))

        queue = state['queue']
        question = questions[queue[0]]
        stages = list(CATEGORIES)
        round_index = stages.index(question['category'])
        total = len(questions) // len(stages)
        round_pending = sum(questions[index]['category'] == question['category'] for index in queue)
        round_passed = total - round_pending + int(bool(state['feedback'] and state['feedback']['correct']))
        completed = review_word_count(questions, state, len(stages))
        return render_template('review_practice.html', state=state, q=question, stages=stages,
                               round_index=round_index, total=total, round_passed=round_passed,
                               completed=completed)

    def battle_data(battle_id):
        battle = db().execute('SELECT b.*,u.name creator_name FROM battles b JOIN users u ON u.id=b.creator_id WHERE b.id=?', (battle_id,)).fetchone()
        if not battle:
            abort(404)
        attempts = db().execute('SELECT a.*,u.name FROM attempts a JOIN users u ON u.id=a.user_id WHERE battle_id=? ORDER BY a.user_id', (battle_id,)).fetchall()
        return battle, attempts

    @app.route('/battles', methods=['GET', 'POST'])
    @login_required
    def battles():
        words = db().execute('''SELECT w.* FROM words w JOIN pages p ON p.id=w.page_id WHERE p.library_key=?
            AND (EXISTS(SELECT 1 FROM progress WHERE page_id=w.page_id AND user_id=1) OR EXISTS(SELECT 1 FROM word_progress WHERE word_id=w.id AND user_id=1))
            AND (EXISTS(SELECT 1 FROM progress WHERE page_id=w.page_id AND user_id=2) OR EXISTS(SELECT 1 FROM word_progress WHERE word_id=w.id AND user_id=2))''', (library_key,)).fetchall()
        if request.method == 'POST':
            if not words:
                flash('还没有双方都学过的页面，请两位同学先完成至少一页相同内容。', 'info')
            else:
                questions = make_questions(words, integer(request.form.get('count')))
                cursor = db().execute('INSERT INTO battles(creator_id,questions,created_at) VALUES(?,?,?)', (g.user['id'], json.dumps(questions, ensure_ascii=False), now()))
                bid = cursor.lastrowid
                notify(3-g.user['id'], f'{g.user["name"]} 发起了对战 #{bid:04d}，邀请你迎战。', bid)
                db().commit()
                return redirect(url_for('battle_detail', battle_id=bid))
            return redirect(url_for('battles'))
        rows = db().execute('SELECT b.*,u.name creator_name,(SELECT COUNT(*) FROM attempts a WHERE a.battle_id=b.id) submitted,(SELECT COUNT(*) FROM attempts a WHERE a.battle_id=b.id AND a.user_id=?) mine FROM battles b JOIN users u ON u.id=b.creator_id ORDER BY b.id DESC', (g.user['id'],)).fetchall()
        return render_template('battles.html', battles=rows, word_count=len(words))

    @app.get('/battles/<int:battle_id>')
    @login_required
    def battle_detail(battle_id):
        battle, attempts = battle_data(battle_id)
        mine = next((a for a in attempts if a['user_id'] == g.user['id']), None)
        results = [dict(name=a['name'], user_id=a['user_id'], result=json.loads(a['result'])) for a in attempts]
        winner = db().execute('SELECT name FROM users WHERE id=?', (battle['winner_id'],)).fetchone()
        return render_template('battle.html', battle=battle, attempts=results, mine=mine, winner=winner)

    @app.route('/battles/<int:battle_id>/quiz', methods=['GET', 'POST'])
    @login_required
    def battle_quiz(battle_id):
        battle, attempts = battle_data(battle_id)
        if any(a['user_id'] == g.user['id'] for a in attempts):
            return redirect(url_for('battle_detail', battle_id=battle_id))
        questions = json.loads(battle['questions'])
        if request.method == 'POST':
            result = grade(questions)
            # 写锁内检查并结算，防止重复交卷、并发交卷重复加分。
            connection = db()
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('SELECT 1 FROM attempts WHERE battle_id=? AND user_id=?', (battle_id, g.user['id'])).fetchone():
                connection.rollback()
                return redirect(url_for('battle_detail', battle_id=battle_id))
            connection.execute('INSERT INTO attempts(battle_id,user_id,result,created_at) VALUES(?,?,?,?)', (battle_id, g.user['id'], json.dumps(result, ensure_ascii=False), now()))
            summary = '、'.join(f'{CATEGORIES[k]} {s["correct"]}/{s["total"]}' for k, s in result['scores'].items())
            notify(3-g.user['id'], f'{g.user["name"]} 已完成对战 #{battle_id:04d}：{summary}。', battle_id)
            all_attempts = connection.execute('SELECT * FROM attempts WHERE battle_id=?', (battle_id,)).fetchall()
            if len(all_attempts) == 2 and not connection.execute('SELECT settled FROM battles WHERE id=?', (battle_id,)).fetchone()['settled']:
                totals = {a['user_id']: json.loads(a['result'])['correct'] for a in all_attempts}
                winner_id = max(totals, key=totals.get) if len(set(totals.values())) > 1 else None
                connection.execute('UPDATE battles SET settled=1,winner_id=? WHERE id=?', (winner_id, battle_id))
                if winner_id:
                    connection.execute('UPDATE users SET points=points+1 WHERE id=?', (winner_id,))
                winner_name = dict(USERS).get(winner_id)
                for uid, _ in USERS:
                    notify(uid, f'对战 #{battle_id:04d} 已结算：' + (f'{winner_name} 获胜，积分 +1。' if winner_id else '双方平局，不加分。'), battle_id)
            connection.commit()
            return redirect(url_for('battle_detail', battle_id=battle_id))
        return render_template('quiz.html', questions=questions, title=f'考试对战 #{battle_id:04d}', subtitle='双方使用相同试卷 · 三项等权 · 正确题数高者获胜')

    @app.get('/battles/<int:battle_id>/result')
    @login_required
    def battle_result(battle_id):
        battle, attempts = battle_data(battle_id)
        mine = next((a for a in attempts if a['user_id'] == g.user['id']), None)
        if not mine or not battle['settled']:
            flash('双方交卷后开放答案解析。', 'info')
            return redirect(url_for('battle_detail', battle_id=battle_id))
        return render_template('result.html', result=json.loads(mine['result']), title=f'对战 #{battle_id:04d} · 我的答卷', battle=battle)

    @app.route('/messages', methods=['GET', 'POST'])
    @login_required
    def messages():
        if request.method == 'POST':
            db().execute('UPDATE notifications SET seen=1 WHERE user_id=?', (g.user['id'],))
            db().commit()
            return redirect(url_for('messages'))
        rows = db().execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100', (g.user['id'],)).fetchall()
        return render_template('messages.html', messages=rows)

    register_study_routes(app, db, login_required, library_key, materials, now)

    with app.app_context():
        db().executescript((ROOT / 'schema.sql').read_text())
        migrate_sessions(db())
        for uid, name in USERS:
            db().execute('INSERT OR IGNORE INTO users(id,name) VALUES(?,?)', (uid, name))
        db().commit()
        install_vocabulary(db(), vocabulary, app.config['DATABASE'])
    return app


if __name__ == '__main__':
    create_app().run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', 5000)), debug=False)
