"""SQLite storage and validation. Each book record represents one copy."""
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db(path):
    with connect(path) as db:
        db.executescript(Path(__file__).with_name('schema.sql').read_text())
        if 'barcode' not in [row['name'] for row in db.execute('PRAGMA table_info(books)')]:
            db.execute('ALTER TABLE books ADD COLUMN barcode TEXT')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS unique_book_barcode ON books(barcode)')


def rows(path, sql, values=()):
    with connect(path) as db:
        return [dict(row) for row in db.execute(sql, values).fetchall()]


def required(value, label, maximum=150):
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError(f'{label} must contain 1–{maximum} characters.')
    return value


def isbn_total(digits):
    total = 0
    for i in range(len(digits)):
        weight = 1
        if i % 2 == 1:
            weight = 3
        total += int(digits[i]) * weight
    return total


def clean_isbn(value):
    isbn = value.replace('-', '').replace(' ', '').upper()
    valid = False
    if len(isbn) == 13 and isbn.isascii() and isbn.isdigit():
        total = isbn_total(isbn)
        valid = isbn.startswith(('978', '979')) and total % 10 == 0
    elif len(isbn) == 10 and isbn[:9].isascii() and isbn[:9].isdigit():
        if isbn[-1] == 'X':
            last = 10
        elif isbn[-1].isascii() and isbn[-1].isdigit():
            last = int(isbn[-1])
        else:
            last = -1
        total = last
        for i in range(9):
            total += int(isbn[i]) * (10 - i)
        valid = last >= 0 and total % 11 == 0
        if valid:
            first = '978' + isbn[:9]
            total = isbn_total(first)
            isbn = first + str((-total) % 10)
    if not valid:
        raise ValueError('Enter a valid ISBN-10 or ISBN-13, including its check digit.')
    return isbn


def clean_barcode(value):
    code = value.strip().replace(' ', '').replace('-', '')
    if len(code) == 12:
        code = '0' + code  # UPC-A and its EAN-13 representation use the same key.
    if len(code) not in (8, 13) or not code.isascii() or not code.isdigit():
        raise ValueError('Enter an EAN-8, UPC-A or EAN-13 barcode.')
    total = 0
    weight = 1
    for digit in reversed(code):
        total += int(digit) * weight
        if weight == 1:
            weight = 3
        else:
            weight = 1
    if total % 10:
        raise ValueError('Barcode check digit is invalid.')
    return code


def resolve_barcode(path, value):
    code = clean_barcode(value)
    found = rows(path, 'SELECT isbn FROM books WHERE isbn=? OR barcode=?', (code, code))
    if len(found) == 1:
        return found[0]['isbn']
    if len(found) > 1:
        raise ValueError('This barcode matches multiple books. Enter the ISBN instead.')
    try:
        return clean_isbn(code)
    except ValueError:
        raise ValueError(f'Barcode {code} is not linked to a book. Use Scan / add to link it to the printed ISBN.') from None


def students(path):
    return rows(path, 'SELECT * FROM students ORDER BY name, school_id')


def books(path):
    return rows(path, '''SELECT books.*, NOT EXISTS (
        SELECT 1 FROM loans WHERE book_id = books.id AND returned_at IS NULL
        ) AS available FROM books ORDER BY title''')


def get_student(path, student_id):
    with connect(path) as db:
        return db.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()


def get_book(path, book_id):
    with connect(path) as db:
        return db.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()


def get_book_by_isbn(path, isbn):
    for book in books(path):
        if book['isbn'] == isbn:
            return book
    return None


def save_student(path, student_id, school_id, name, histogram):
    name = required(name, 'Name')
    school_id = required(school_id, 'School ID', 40)
    if histogram is not None:
        try:
            values = [float(n) for n in histogram.split(',')]
            if len(values) != 32 or any(not math.isfinite(n) or n < 0 or n > 1 for n in values):
                raise ValueError()
        except ValueError:
            raise ValueError('Capture a valid face sample before saving.') from None
    try:
        with connect(path) as db:
            if student_id is None:
                if histogram is None:
                    raise ValueError('Capture a face sample before saving.')
                return db.execute('INSERT INTO students(school_id, name, histogram) VALUES (?, ?, ?)',
                                  (school_id, name, histogram)).lastrowid
            result = db.execute('UPDATE students SET school_id=?, name=?, histogram=COALESCE(?, histogram) WHERE id=?',
                                (school_id, name, histogram, student_id))
            if result.rowcount == 0:
                raise ValueError('Student not found.')
            return student_id
    except sqlite3.IntegrityError:
        raise ValueError('That school ID is already registered.') from None


def save_book(path, book_id, isbn, title, author, barcode=None):
    isbn = clean_isbn(isbn)
    if barcode is not None:
        barcode = clean_barcode(barcode) if barcode.strip() else ''
        if barcode.startswith(('978', '979')) and barcode != isbn:
            raise ValueError('An ISBN barcode must match the book’s ISBN.')
    title = required(title, 'Title', 250)
    author = author.strip()
    if len(author) > 200:
        raise ValueError('Author must be at most 200 characters.')
    try:
        with connect(path) as db:
            if book_id is None:
                return db.execute('INSERT INTO books(isbn, title, author, barcode) VALUES (?, ?, ?, ?)',
                                  (isbn, title, author, barcode or None)).lastrowid
            if db.execute('SELECT 1 FROM loans WHERE book_id=? AND returned_at IS NULL', (book_id,)).fetchone():
                old = db.execute('SELECT isbn FROM books WHERE id=?', (book_id,)).fetchone()
                if old['isbn'] != isbn:
                    raise ValueError('Return this book before changing its ISBN.')
            if barcode is None:
                current = db.execute('SELECT barcode FROM books WHERE id=?', (book_id,)).fetchone()
                barcode = current['barcode'] if current else None
            result = db.execute('UPDATE books SET isbn=?, title=?, author=?, barcode=? WHERE id=?', (isbn, title, author, barcode or None, book_id))
            if result.rowcount == 0:
                raise ValueError('Book not found.')
            return book_id
    except sqlite3.IntegrityError:
        raise ValueError('That ISBN or barcode is already linked to a book.') from None


def delete_student(path, student_id):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM loans WHERE student_id=? AND returned_at IS NULL', (student_id,)).fetchone():
            raise ValueError('Return this student’s books before deleting their record.')
        if db.execute('DELETE FROM students WHERE id=?', (student_id,)).rowcount == 0:
            raise ValueError('Student not found.')


def delete_book(path, book_id):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM loans WHERE book_id=? AND returned_at IS NULL', (book_id,)).fetchone():
            raise ValueError('Return this book before deleting it.')
        if db.execute('DELETE FROM books WHERE id=?', (book_id,)).rowcount == 0:
            raise ValueError('Book not found.')


def checkout(path, student_id, isbn):
    isbn = clean_isbn(isbn)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        student = db.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()
        book = db.execute('SELECT * FROM books WHERE isbn=?', (isbn,)).fetchone()
        if student is None:
            raise ValueError('Student not found. Register the student first.')
        if book is None:
            raise ValueError('Book not found. Add it in Admin first.')
        if db.execute('SELECT 1 FROM loans WHERE book_id=? AND returned_at IS NULL', (book['id'],)).fetchone():
            raise ValueError('This book is already on loan.')
        return db.execute('''INSERT INTO loans(student_id, book_id, student_name, book_title, isbn)
            VALUES (?, ?, ?, ?, ?)''', (student_id, book['id'], student['name'], book['title'], isbn)).lastrowid


def return_book(path, isbn):
    isbn = clean_isbn(isbn)
    with connect(path) as db:
        result = db.execute('''UPDATE loans SET returned_at=strftime('%Y-%m-%d %H:%M:%f', 'now')
            WHERE book_id=(SELECT id FROM books WHERE isbn=?) AND returned_at IS NULL''', (isbn,))
        if result.rowcount == 0:
            raise ValueError('No active loan was found for that ISBN.')


def active_loans(path):
    return rows(path, 'SELECT * FROM loans WHERE returned_at IS NULL ORDER BY checkout_at DESC')


def loan_log(path, query='', event='all'):
    # Snapshots keep the original names readable after edits or deletion.
    return rows(path, '''SELECT * FROM (
        SELECT id AS loan_id, student_name, book_title, isbn, checkout_at AS time, 'Checkout' AS event FROM loans
        UNION ALL
        SELECT id, student_name, book_title, isbn, returned_at, 'Return' FROM loans WHERE returned_at IS NOT NULL
        ) WHERE (instr(lower(student_name), lower(?)) > 0 OR instr(lower(book_title), lower(?)) > 0)
        AND (? = 'all' OR event = ?) ORDER BY time DESC, loan_id DESC, event DESC''',
        (query, query, event, event))
