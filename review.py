"""每日复习的逐题进度与按词统计。"""
import json
import random
import secrets
from collections import Counter
from datetime import date, timedelta

from study import normalize_answer


def review_activity(connection, user_id, word_ids):
    """每个日期和词条最多计一次，兼容早期整份提交的答卷。"""
    activity = {
        (row['reviewed_on'], row['word_id'])
        for row in connection.execute(
            'SELECT reviewed_on, word_id FROM review_word_days WHERE user_id=?', (user_id,)
        )
        if row['word_id'] in word_ids
    }
    legacy = connection.execute('''
        SELECT r.result, r.created_at FROM reviews r
        LEFT JOIN review_sessions s ON s.review_id=r.id
        WHERE r.user_id=? AND r.result IS NOT NULL AND s.review_id IS NULL
    ''', (user_id,))
    required = {'zh_en', 'en_zh', 'spelling'}
    for row in legacy:
        result = json.loads(row['result'])
        reviewed_on = result.get('reviewed_on', row['created_at'][:10])
        correct = {}
        for item in result.get('details', []):
            word_id = item.get('word_id')
            if item.get('correct') and word_id in word_ids:
                correct.setdefault(word_id, set()).add(item['category'])
        activity.update((reviewed_on, word_id) for word_id, stages in correct.items() if required <= stages)
    return activity


def review_stats(activity, today, word_count):
    daily = Counter(day for day, _ in activity)
    covered = len({word_id for _, word_id in activity})
    first = date.fromisoformat(min(daily)) if daily else today
    days = max(1, (today - first).days + 1)
    week = [(today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]
    return {
        'today': daily[today.isoformat()], 'total': len(activity),
        'average': len(activity) / days, 'covered': covered, 'waiting': word_count - covered,
        'week': [(day[5:].replace('-', '/'), daily[day]) for day in week],
        'peak': max(1, *(daily[day] for day in week)),
    }


def choose_words(words, count, activity):
    latest = {}
    for day, word_id in activity:
        latest[word_id] = max(day, latest.get(word_id, ''))
    candidates = list(words)
    random.shuffle(candidates)
    candidates.sort(key=lambda word: latest.get(word['id'], ''))
    return candidates[:count]


def new_review_state(questions):
    return {
        'queue': list(range(len(questions))), 'feedback': None,
        'first_attempts': {}, 'mistakes': 0, 'nonce': secrets.token_hex(16),
    }


def advance_review(state, questions, action, submitted):
    """返回本次刚通过三轮的词 ID，以及操作是否有效。"""
    queue = state['queue']
    index = queue[0]
    question = questions[index]
    category = question['category']
    completed_word = None
    if action == 'answer' and state['feedback'] is None:
        answer = submitted.strip()
        if not answer or (question['options'] and answer not in question['options']):
            return None, False
        correct = normalize_answer(answer) == normalize_answer(question['answer'])
        feedback = {'submitted': answer, 'correct': correct}
        state['first_attempts'].setdefault(str(index), feedback)
        state['feedback'] = feedback
        if not correct:
            state['mistakes'] += 1
        elif category == 'spelling':
            completed_word = question['word_id']
        if correct and len(queue) == 1:
            queue.clear()
            state['feedback'] = None
    elif action == 'continue' and state['feedback'] is not None:
        queue.pop(0)
        if not state['feedback']['correct']:
            next_round = next(
                (position for position, item in enumerate(queue) if questions[item]['category'] != category),
                len(queue),
            )
            queue.insert(next_round, index)
        state['feedback'] = None
    else:
        return None, False
    state['nonce'] = secrets.token_hex(16)
    return completed_word, True


def review_result(state, questions, categories, finished_at):
    scores = {key: {'correct': 0, 'total': 0} for key in categories}
    details = []
    for index, question in enumerate(questions):
        answer = state['first_attempts'][str(index)]
        score = scores[question['category']]
        score['correct'] += int(answer['correct'])
        score['total'] += 1
        if not answer['correct']:
            details.append({**question, **answer})
    return {
        'scores': scores, 'details': details, 'correct': sum(score['correct'] for score in scores.values()),
        'total': len(questions), 'word_count': len(questions) // len(categories),
        'mistakes': state['mistakes'], 'finished_at': finished_at,
    }


def current_review(connection, user_id):
    return connection.execute('''
        SELECT r.id, r.questions, s.state FROM reviews r
        JOIN review_sessions s ON s.review_id=r.id
        WHERE r.user_id=? AND r.result IS NULL ORDER BY r.id DESC LIMIT 1
    ''', (user_id,)).fetchone()


def review_word_count(questions, state, round_count):
    queue = state['queue']
    if state['feedback'] and state['feedback']['correct']:
        queue = queue[1:]
    pending_spelling = sum(questions[index]['category'] == 'spelling' for index in queue)
    return len(questions) // round_count - pending_spelling
