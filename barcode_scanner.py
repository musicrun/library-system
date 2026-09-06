"""Optional barcode reading and Open Library lookup for adding books."""
import json
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from database import clean_isbn, clean_barcode


def scan_barcode(frame):
    import cv2
    import zxingcpp
    formats = zxingcpp.BarcodeFormat.EAN13 | zxingcpp.BarcodeFormat.EAN8 | zxingcpp.BarcodeFormat.UPCA
    results = zxingcpp.read_barcodes(frame, formats=formats)
    for result in results:
        code = clean_barcode(result.text)
        position = result.position
        points = [position.top_left, position.top_right, position.bottom_left, position.bottom_right]
        left = min(point.x for point in points)
        right = max(point.x for point in points)
        top = min(point.y for point in points)
        bottom = max(point.y for point in points)
        cv2.rectangle(frame, (left, top), (right, bottom), (255, 0, 0), 2)
        return code
    raise ValueError('No book barcode detected. Hold it closer, keep it sharp, and try again.')


def lookup_book(isbn):
    isbn = clean_isbn(isbn)
    key = 'ISBN:' + isbn
    url = 'https://openlibrary.org/api/books?' + urlencode({'bibkeys': key, 'format': 'json', 'jscmd': 'data'})
    request = Request(url, headers={'User-Agent': 'SchoolLibraryPrototype/1.0'})
    try:
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read(1_000_000))
        book = result.get(key)
        if not isinstance(book, dict) or not book.get('title'):
            raise ValueError('Book not found online. Enter its details manually.')
        return {'isbn': isbn, 'title': book['title'],
                'author': ', '.join(author['name'] for author in book.get('authors', []))}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        raise ValueError('Online lookup unavailable. Enter the book details manually.') from None
