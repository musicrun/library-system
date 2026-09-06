PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY,
    school_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    histogram TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    isbn TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    barcode TEXT
);
CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY,
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
    book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    student_name TEXT NOT NULL,
    book_title TEXT NOT NULL,
    isbn TEXT NOT NULL,
    checkout_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    returned_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_loan
ON loans(book_id) WHERE returned_at IS NULL;
