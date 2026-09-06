import unittest
from pathlib import Path
import cv2
import numpy as np
from barcode_scanner import scan_barcode


class BarcodeTests(unittest.TestCase):
    def test_real_ean13_decodes(self):
        frame = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'isbn.png'))
        self.assertEqual(scan_barcode(frame), '9780140328721')

    def test_blank_frame_reports_no_barcode(self):
        with self.assertRaisesRegex(ValueError, 'No book barcode'):
            scan_barcode(np.full((200, 400, 3), 255, dtype=np.uint8))

    def test_ean8_returns_product_code(self):
        frame = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'non_isbn_ean8.png'))
        self.assertEqual(scan_barcode(frame), '96385074')

    def test_non_isbn_ean13_returns_product_code(self):
        frame = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'non_isbn_ean13.png'))
        self.assertEqual(scan_barcode(frame), '4006381333931')

    def test_reported_book_isbn_decodes(self):
        frame = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'user_isbn.png'))
        self.assertEqual(scan_barcode(frame), '9780671004545')

    def test_reported_upc_is_accepted_as_product_barcode(self):
        frame = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'user_upc.png'))
        self.assertEqual(scan_barcode(frame), '0076714007994')
