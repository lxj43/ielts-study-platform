"""词库加载与无损升级。旧示例记录保留在独立词库中。"""
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path


def read_vocabulary(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if isinstance(data, list):
        data = {'key': 'demo', 'title': '示例词库', 'page_basis': '示例页面', 'pages': [
            dict(page, words=[dict(zip(('english', 'chinese', 'phonetic'), word)) for word in page['words']])
            for page in data]}
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', data['key']):
        raise ValueError('词库编号不合法')
    pages = data['pages']
    numbers, words = set(), set()
    for page in pages:
        if not isinstance(page['number'], int) or page['number'] < 1 or page['number'] in numbers or not page['words']:
            raise ValueError('词库存在重复页码、非法页码或空页')
        numbers.add(page['number'])
        for word in page['words']:
            if not all(isinstance(word[k], str) and word[k].strip() for k in ['english', 'chinese']):
                raise ValueError('词条缺少英文或中文')
            key = word['english'].strip().casefold()
            if key in words:
                raise ValueError(f'重复词条：{word["english"]}')
            words.add(key)
    if data.get('page_count', len(pages)) != len(pages) or data.get('word_count', len(words)) != len(words):
        raise ValueError('词库声明的数量与实际内容不一致')
    data.update(page_count=len(pages), word_count=len(words))
    return data


def install_vocabulary(connection, vocabulary, database):
    """按版本只安装一次；升级旧 schema 前备份，页 ID 和全部历史记录不变。"""
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(pages)')}
    needs_migration = 'library_key' not in columns
    exists = not needs_migration and connection.execute(
        'SELECT 1 FROM pages WHERE library_key=? LIMIT 1', (vocabulary['key'],)).fetchone()
    if exists:
        page_count = connection.execute('SELECT COUNT(*) FROM pages WHERE library_key=?', (vocabulary['key'],)).fetchone()[0]
        word_count = connection.execute('SELECT COUNT(*) FROM words w JOIN pages p ON p.id=w.page_id WHERE p.library_key=?', (vocabulary['key'],)).fetchone()[0]
        if (page_count, word_count) != (vocabulary['page_count'], vocabulary['word_count']):
            raise ValueError('已安装词库的数量异常，请从备份恢复或使用新的词库版本号')
        return
    if connection.execute('SELECT 1 FROM words LIMIT 1').fetchone() and database != ':memory:':
        folder = Path(database).resolve().parent / 'backups'
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f'before-{vocabulary["key"]}-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3'
        connection.commit()
        with sqlite3.connect(destination) as backup:
            connection.backup(backup)
    if needs_migration:
        connection.commit()
        connection.execute('PRAGMA foreign_keys=OFF')
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('''CREATE TABLE pages_v2 (
                id INTEGER PRIMARY KEY, number INTEGER NOT NULL, title TEXT NOT NULL,
                library_key TEXT NOT NULL DEFAULT 'demo', UNIQUE(library_key,number))''')
            connection.execute("INSERT INTO pages_v2(id,number,title,library_key) SELECT id,number,title,'demo' FROM pages")
            connection.execute('DROP TABLE pages')
            connection.execute('ALTER TABLE pages_v2 RENAME TO pages')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute('PRAGMA foreign_keys=ON')
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('数据库升级后关联检查失败，请从自动备份恢复')
    word_columns = {row['name'] for row in connection.execute('PRAGMA table_info(words)')}
    for name in ['source_list', 'source_no']:
        if name not in word_columns:
            connection.execute(f'ALTER TABLE words ADD COLUMN {name} INTEGER')
    # 旧版示例库升级后已经存在，不能再插入一套相同页码。
    if needs_migration and vocabulary['key'] == 'demo':
        connection.commit()
        return
    with connection:
        for page in vocabulary['pages']:
            cursor = connection.execute('INSERT INTO pages(number,title,library_key) VALUES(?,?,?)',
                                        (page['number'], page['title'], vocabulary['key']))
            connection.executemany('''INSERT INTO words(page_id,english,chinese,phonetic,source_list,source_no)
                                     VALUES(?,?,?,?,?,?)''', [
                (cursor.lastrowid, w['english'], w['chinese'], w.get('phonetic', ''), w.get('source_list'), w.get('source_no'))
                for w in page['words']])
