CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY CHECK(id IN (1,2)), name TEXT NOT NULL, points INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY, number INTEGER NOT NULL, title TEXT NOT NULL,
    library_key TEXT NOT NULL DEFAULT 'demo', UNIQUE(library_key,number)
);
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY, page_id INTEGER NOT NULL REFERENCES pages(id),
    english TEXT NOT NULL, chinese TEXT NOT NULL, phonetic TEXT NOT NULL DEFAULT '',
    source_list INTEGER, source_no INTEGER
);
CREATE TABLE IF NOT EXISTS progress (
    user_id INTEGER NOT NULL REFERENCES users(id), page_id INTEGER NOT NULL REFERENCES pages(id),
    learned_at TEXT NOT NULL, PRIMARY KEY(user_id,page_id)
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    questions TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS battles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER NOT NULL REFERENCES users(id),
    questions TEXT NOT NULL, created_at TEXT NOT NULL, settled INTEGER NOT NULL DEFAULT 0,
    winner_id INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS attempts (
    battle_id INTEGER NOT NULL REFERENCES battles(id), user_id INTEGER NOT NULL REFERENCES users(id),
    result TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(battle_id,user_id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), message TEXT NOT NULL,
    battle_id INTEGER NOT NULL REFERENCES battles(id), seen INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS study_sessions (
    user_id INTEGER NOT NULL REFERENCES users(id), page_id INTEGER NOT NULL REFERENCES pages(id),
    state TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(user_id,page_id)
);

CREATE TABLE IF NOT EXISTS word_progress (
 user_id INTEGER NOT NULL REFERENCES users(id), word_id INTEGER NOT NULL REFERENCES words(id),
 learned_at TEXT NOT NULL, PRIMARY KEY(user_id,word_id)
);

CREATE TABLE IF NOT EXISTS review_sessions (
    review_id INTEGER PRIMARY KEY REFERENCES reviews(id), state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_word_days (
    user_id INTEGER NOT NULL REFERENCES users(id), word_id INTEGER NOT NULL REFERENCES words(id),
    reviewed_on TEXT NOT NULL, PRIMARY KEY(user_id, reviewed_on, word_id)
);
