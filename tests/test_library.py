import sqlite3
import tempfile
import unittest
from pathlib import Path


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        import database
        self.db = database
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'test.db'
        self.db.init_db(self.path)
        self.hist = ','.join(['1'] + ['0'] * 31)
        self.student = self.db.save_student(self.path, None, 'S1', 'Saif', self.hist)
        self.book = self.db.save_book(self.path, None, '9780140328721', 'Matilda', 'Roald Dahl')

    def tearDown(self):
        self.folder.cleanup()

    def test_checkout_return_and_search_persist(self):
        loan = self.db.checkout(self.path, self.student, '978-0-14-032872-1')
        with self.assertRaises(ValueError):
            self.db.checkout(self.path, self.student, '9780140328721')
        with self.assertRaises(ValueError):
            self.db.delete_student(self.path, self.student)
        with self.assertRaises(ValueError):
            self.db.delete_book(self.path, self.book)
        self.db.return_book(self.path, '9780140328721')
        with self.assertRaises(ValueError):
            self.db.return_book(self.path, '9780140328721')
        self.db.init_db(self.path)
        events = self.db.loan_log(self.path, 'Matilda')
        self.assertEqual({r['event'] for r in events}, {'Checkout', 'Return'})
        self.assertEqual(events[0]['loan_id'], loan)
        self.db.delete_student(self.path, self.student)
        self.db.delete_book(self.path, self.book)
        self.assertEqual(len(self.db.loan_log(self.path, 'Saif')), 2)
        self.assertEqual(self.db.students(self.path), [])
        self.assertEqual(self.db.books(self.path), [])

    def test_edits_and_duplicates(self):
        self.db.save_student(self.path, self.student, 'S2', 'New name', None)
        self.assertEqual(self.db.students(self.path)[0]['histogram'], self.hist)
        self.db.save_book(self.path, self.book, '9780140328721', 'New title', 'Author')
        self.assertEqual(self.db.books(self.path)[0]['title'], 'New title')
        with self.assertRaises(ValueError):
            self.db.save_student(self.path, None, 'S2', 'Duplicate', self.hist)
        with self.assertRaises(ValueError):
            self.db.save_book(self.path, None, '9780140328721', 'Duplicate', '')

    def test_invalid_inputs_do_not_write(self):
        for isbn in ['', '123', "' OR 1=1--", '9780140328722']:
            with self.assertRaises(ValueError):
                self.db.save_book(self.path, None, isbn, 'Bad', '')
        with self.assertRaises(ValueError):
            self.db.save_student(self.path, None, 'S3', ' ', self.hist)
        with self.assertRaises(ValueError):
            self.db.save_student(self.path, None, 'S3', 'Test', 'nan')
        with self.assertRaises(ValueError):
            self.db.checkout(self.path, 999, '9780140328721')
        self.assertEqual(len(self.db.books(self.path)), 1)
        self.assertEqual(self.db.loan_log(self.path), [])


class MatchingTests(unittest.TestCase):
    def test_threshold_and_no_students(self):
        from vision import find_match
        student = {'id': 1, 'name': 'Saif', 'histogram': ','.join(['0'] * 32)}
        self.assertIsNone(find_match([0] * 32, [])[0])
        self.assertEqual(find_match([0.29] * 32, [student])[0]['id'], 1)
        self.assertIsNone(find_match([0.30] * 32, [student])[0])
        self.assertIsNone(find_match([1] * 32, [student])[0])

    def test_grayscale_histogram_pipeline(self):
        import numpy as np
        from vision import make_histogram
        frame = np.zeros((80, 80, 3), dtype=np.uint8)
        result = make_histogram(frame)
        self.assertEqual(len(result), 32)
        self.assertEqual(result[0], 1)
        self.assertEqual(sum(result), 1)


if __name__ == '__main__':
    unittest.main()

class CameraStateTests(unittest.TestCase):
    def test_stale_sample_cannot_be_used(self):
        import numpy as np
        import time
        from vision import Camera
        camera = Camera()
        camera.frame = np.zeros((3, 3, 3), dtype=np.uint8)
        camera.jpeg = b'jpeg'
        camera.histogram = [1] + [0] * 31
        camera.updated_at = time.monotonic()
        self.assertIsNotNone(camera.snapshot()[2])
        camera.updated_at -= 4
        self.assertIsNone(camera.snapshot()[2])
        self.assertIsNone(camera.snapshot()[1])
        camera.stop()
        self.assertIsNone(camera.snapshot()[0])

    def test_isbn10_and_isbn13_are_same_book(self):
        from database import clean_isbn
        self.assertEqual(clean_isbn('0-14-032872-6'), '9780140328721')

class BarcodeLinkTests(unittest.TestCase):
    def test_upc_link_persists_and_resolves_without_weakening_isbn(self):
        import database as db
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.db'
            db.init_db(path)
            book = db.save_book(path, None, '9780671004545', 'Test book', 'Author', '076714007994')
            db.init_db(path)
            self.assertEqual(db.resolve_barcode(path, '0076714007994'), '9780671004545')
            self.assertEqual(db.resolve_barcode(path, '076714007994'), '9780671004545')
            with self.assertRaises(ValueError):
                db.clean_isbn('0076714007994')
            with self.assertRaises(ValueError):
                db.save_book(path, None, '9780140328721', 'Other', '', '0076714007994')
            with self.assertRaises(ValueError):
                db.resolve_barcode(path, '4006381333931')
            db.save_book(path, book, '9780671004545', 'Edited', 'Author')
            self.assertEqual(db.resolve_barcode(path, '0076714007994'), '9780671004545')

    def test_existing_database_migration_preserves_books(self):
        import database as db
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.db'
            with sqlite3.connect(path) as connection:
                connection.execute('CREATE TABLE books (id INTEGER PRIMARY KEY, isbn TEXT UNIQUE NOT NULL, title TEXT NOT NULL, author TEXT NOT NULL)')
                connection.execute("INSERT INTO books VALUES (1,'9780140328721','Matilda','Dahl')")
            db.init_db(path)
            self.assertEqual(db.books(path)[0]['title'], 'Matilda')
            self.assertIsNone(db.books(path)[0]['barcode'])
