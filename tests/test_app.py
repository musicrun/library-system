import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeCamera:
    histogram = None
    def snapshot(self):
        return None, None, self.histogram, 'No person detected.'
    def start(self):
        pass
    def stop(self):
        self.histogram = None


class AppTests(unittest.TestCase):
    def setUp(self):
        from app import create_app
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'library.db'
        self.camera = FakeCamera()
        self.app = create_app(self.path, self.camera)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.token = session['csrf']

    def tearDown(self):
        self.folder.cleanup()

    def post(self, path, **data):
        return self.client.post(path, data={**data, 'csrf': self.token}, follow_redirects=True)

    def test_pages_and_csrf(self):
        for page in ['/', '/return', '/register', '/admin', '/loans', '/scan-add']:
            self.assertEqual(self.client.get(page).status_code, 200, page)
        self.assertEqual(self.client.post('/checkout').status_code, 400)

    def test_complete_flow(self):
        import database
        self.camera.histogram = [1] + [0] * 31
        self.assertEqual(self.post('/register', school_id='S1', name='Saif').status_code, 200)
        self.post('/book', isbn='9780140328721', title='Matilda', author='Roald Dahl')
        self.assertIn(b'Matilda', self.client.get('/?isbn=9780140328721').data)
        self.assertEqual(self.client.get('/api/detect').json['name'], 'Saif')
        self.post('/identify')
        self.assertEqual(self.post('/checkout', isbn='9780140328721', confirmed='yes', student_id='1').status_code, 200)
        self.assertEqual(len(database.active_loans(self.path)), 1)
        self.assertEqual(self.post('/checkout', isbn='9780140328721', confirmed='yes', student_id='1').status_code, 400)
        self.post('/return', isbn='9780140328721')
        self.assertEqual(len(database.loan_log(self.path)), 2)
        self.assertIn(b'Matilda', self.client.get('/loans?q=Saif').data)

    def test_registration_without_camera_and_expired_selection(self):
        import database
        self.assertEqual(self.post('/register', school_id='S1', name='Saif').status_code, 400)
        self.assertEqual(database.students(self.path), [])
        self.assertIsNone(self.client.get('/api/detect').json['name'])
        with self.client.session_transaction() as session:
            session['selected'] = {'id': 1, 'name': 'Saif', 'time': 0, 'score': 0}
        self.assertEqual(self.post('/checkout', isbn='9780140328721', confirmed='yes', student_id='1').status_code, 400)

    def test_online_failure_preserves_manual_entry(self):
        with patch('barcode_scanner.lookup_book', side_effect=ValueError('Offline. Enter manually.')):
            response = self.post('/scan-add', action='lookup', isbn='9780140328721')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'9780140328721', response.data)
        self.assertIn(b'Enter manually', response.data)

    def test_admin_routes_escape_names_and_preserve_history(self):
        import database
        self.camera.histogram = [1] + [0] * 31
        self.post('/register', school_id='S1', name='<script>alert(1)</script>')
        self.post('/book', isbn='9780140328721', title='Matilda', author='Dahl')
        student = database.students(self.path)[0]['id']
        book = database.books(self.path)[0]['id']
        self.assertIn(b'&lt;script&gt;', self.client.get('/admin').data)
        self.post(f'/student/{student}', school_id='S1', name='Updated')
        self.post(f'/book/{book}', isbn='9780140328721', title='Updated title', author='Dahl')
        self.assertEqual(database.students(self.path)[0]['name'], 'Updated')
        self.assertEqual(database.books(self.path)[0]['title'], 'Updated title')
        self.post(f'/student/{student}/delete')
        self.post(f'/book/{book}/delete')
        self.assertEqual(database.students(self.path), [])
        self.assertEqual(database.books(self.path), [])

    def test_confirmation_required_and_unknown_book(self):
        self.camera.histogram = [1] + [0] * 31
        self.post('/register', school_id='S1', name='Saif')
        self.post('/identify')
        self.assertEqual(self.post('/checkout', isbn='9780140328721').status_code, 400)
        self.assertEqual(self.post('/checkout', isbn='9780140328721', confirmed='yes', student_id='1').status_code, 400)

    def test_scan_for_checkout_return_and_add(self):
        import cv2
        import database
        frame = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'isbn.png'))
        self.camera.snapshot = lambda: (frame.copy(), None, None, 'Ready')
        self.camera.show_preview = lambda jpeg: None
        database.save_book(self.path, None, '9780140328721', 'Matilda', 'Dahl')
        checkout = self.post('/scan-isbn', next='/')
        self.assertEqual(checkout.status_code, 200)
        self.assertIn(b'Matilda', checkout.data)
        returned = self.post('/scan-isbn', next='/return')
        self.assertIn(b'value="9780140328721"', returned.data)
        added = self.post('/scan-add', action='scan')
        self.assertIn(b'value="9780140328721"', added.data)
        self.assertEqual(database.loan_log(self.path), [])

    def test_upc_scan_links_existing_book_then_resolves_for_checkout_and_return(self):
        import database
        database.save_book(self.path, None, '9780671004545', 'Existing title', 'Author')
        with patch('barcode_scanner.scan_barcode', return_value='0076714007994'):
            import numpy as np
            self.camera.snapshot = lambda: (np.zeros((20,20,3), dtype=np.uint8), None, None, 'Ready')
            self.camera.show_preview = lambda jpeg: None
            unlinked = self.post('/scan-isbn', next='/')
            self.assertIn(b'not linked', unlinked.data)
            scan = self.post('/scan-add', action='scan')
            self.assertIn(b'value="0076714007994"', scan.data)
            saved = self.post('/scan-add', action='save', isbn='9780671004545', barcode='0076714007994')
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(len(database.books(self.path)), 1)
            self.assertEqual(database.books(self.path)[0]['title'], 'Existing title')
            self.assertIn(b'Existing title', self.post('/scan-isbn', next='/').data)
            self.assertIn(b'value="9780671004545"', self.post('/scan-isbn', next='/return').data)

    def test_checkout_rejects_student_changed_in_another_tab(self):
        import database
        self.camera.histogram = [1] + [0] * 31
        self.post('/register', school_id='S1', name='Alice')
        self.post('/book', isbn='9780140328721', title='Matilda', author='Dahl')
        self.post('/identify')
        database.save_student(self.path, None, 'S2', 'Bob', ','.join(['0', '1'] + ['0'] * 30))
        self.camera.histogram = [0, 1] + [0] * 30
        self.post('/identify')
        response = self.post('/checkout', isbn='9780140328721', confirmed='yes', student_id='1')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(database.active_loans(self.path), [])

    def test_camera_start_returns_to_edit_student_page(self):
        self.camera.histogram = [1] + [0] * 31
        self.post('/register', school_id='S1', name='Alice')
        response = self.client.post('/camera/start', data={'csrf': self.token, 'next':'/student/1'})
        self.assertEqual(response.location, '/student/1')

    def test_scan_add_blank_barcode_keeps_existing_link(self):
        import database
        database.save_book(self.path, None, '9780671004545', 'Existing', '', '0076714007994')
        self.post('/scan-add', action='save', isbn='9780671004545', barcode='   ')
        self.assertEqual(database.resolve_barcode(self.path, '0076714007994'), '9780671004545')

    def test_deleted_student_selection_cannot_identify_reused_id(self):
        import database
        self.camera.histogram = [1] + [0] * 31
        self.post('/register', school_id='S1', name='Alice')
        self.post('/identify')
        database.delete_student(self.path, 1)
        database.save_student(self.path, None, 'S2', 'Bob', ','.join(['1'] + ['0'] * 31))
        response = self.client.get('/')
        self.assertNotIn(b'Selected:', response.data)
