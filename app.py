"""Run with python app.py, then open http://127.0.0.1:5001."""
import atexit
import os
import secrets
import time
from pathlib import Path
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for
import database as db
from vision import Camera, find_match, scan_barcode

BASE = Path(__file__).resolve().parent
(BASE / '.yolo').mkdir(exist_ok=True)
os.environ.setdefault('YOLO_CONFIG_DIR', str(BASE / '.yolo'))


app = Flask(__name__, template_folder=str(BASE), static_folder=None)
app.secret_key = secrets.token_hex(32)
app.config.update(SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=64 * 1024)
path = BASE / 'library.db'
db.init_db(path)
camera = Camera(0)
atexit.register(camera.stop)

@app.before_request
def check_form():
    session.setdefault('csrf', secrets.token_hex(32))
    if request.method == 'POST':
        token = request.form.get('csrf', '')
        if not secrets.compare_digest(token, session['csrf']):
            abort(400, 'Form expired. Reload the page and try again.')

@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Frame-Options'] = 'DENY'
    return response

@app.errorhandler(ValueError)
def invalid_input(error):
    return render_template('page.html', page='error', message=str(error)), 400

@app.errorhandler(400)
def bad_request(error):
    return render_template('page.html', page='error', message=error.description), 400

def selected_student():
    selected = session.get('selected')
    if selected and time.time() - selected['time'] < 120:
        student = db.get_student(path, selected['id'])
        if student and student['school_id'] == selected.get('school_id'):
            selected['name'] = student['name']
            return selected
    session.pop('selected', None)
    return None

def current_histogram():
    histogram = camera.snapshot()[2]
    if histogram is None:
        raise ValueError('No fresh person sample. Start the camera and stand inside the box.')
    return histogram

def read_camera_barcode():
    frame = camera.snapshot()[0]
    if frame is None:
        raise ValueError('Start the camera first, then hold the barcode in view.')
    isbn = scan_barcode(frame)
    import cv2
    ok, encoded = cv2.imencode('.jpg', frame)
    if ok:
        camera.show_preview(encoded.tobytes())
    return isbn

@app.post('/scan-isbn')
def scan_isbn():
    destination = 'home'
    if request.form.get('next') == '/return':
        destination = 'returns'
    try:
        isbn = db.resolve_barcode(path, read_camera_barcode())
        return redirect(url_for(destination, isbn=isbn))
    except ValueError as error:
        flash(str(error))
        return redirect(url_for(destination))

@app.get('/')
def home():
    isbn = request.args.get('isbn', '')
    book = None
    if isbn:
        try:
            isbn = db.clean_isbn(isbn)
            book = db.get_book_by_isbn(path, isbn)
            if book is None:
                flash('Book not found. Add it in Admin first.')
        except ValueError as error:
            flash(str(error))
    return render_template('page.html', page='checkout', selected=selected_student(), book=book, isbn=isbn)

@app.post('/identify')
def identify():
    session.pop('selected', None)
    student, score = find_match(current_histogram(), db.students(path))
    if student is None:
        raise ValueError('No match found. Register the student or capture a new sample.')
    session['selected'] = {'id': student['id'], 'name': student['name'], 'school_id': student['school_id'], 'score': score, 'time': time.time()}
    return redirect(url_for('home', isbn=request.form.get('isbn', '')))

@app.post('/checkout')
def checkout():
    student = selected_student()
    if student is None:
        raise ValueError('Identify the student again. Selections expire after two minutes.')
    if request.form.get('student_id') != str(student['id']):
        raise ValueError('The selected student changed. Reload and confirm the current student.')
    if request.form.get('confirmed') != 'yes':
        raise ValueError('Confirm the displayed student before checkout.')
    db.checkout(path, student['id'], request.form.get('isbn', ''))
    session.pop('selected', None)
    flash('Checkout saved.')
    return redirect(url_for('home'))

@app.route('/return', methods=['GET', 'POST'])
def returns():
    if request.method == 'POST':
        db.return_book(path, request.form.get('isbn', ''))
        flash('Return saved.')
        return redirect(url_for('returns'))
    return render_template('page.html', page='return', loans=db.active_loans(path), isbn=request.args.get('isbn', ''))

@app.route('/register', methods=['GET', 'POST'])
@app.route('/student/<int:student_id>', methods=['GET', 'POST'])
def register(student_id=None):
    student = db.get_student(path, student_id)
    if student_id is not None and student is None:
        abort(404)
    if request.method == 'POST':
        histogram = None
        if student_id is None or request.form.get('recapture'):
            values = []
            for number in current_histogram():
                values.append(str(number))
            histogram = ','.join(values)
        db.save_student(path, student_id, request.form.get('school_id', ''), request.form.get('name', ''), histogram)
        flash('Student saved.')
        return redirect(url_for('admin'))
    return render_template('page.html', page='register', student=student)

@app.get('/admin')
def admin():
    return render_template('page.html', page='admin', students=db.students(path), books=db.books(path), editing=None)

@app.route('/book', methods=['POST'])
@app.route('/book/<int:book_id>', methods=['GET', 'POST'])
def book_edit(book_id=None):
    book = db.get_book(path, book_id)
    if book_id is not None and book is None:
        abort(404)
    if request.method == 'POST':
        db.save_book(path, book_id, request.form.get('isbn', ''), request.form.get('title', ''), request.form.get('author', ''), request.form.get('barcode', ''))
        flash('Book saved.')
        return redirect(url_for('admin'))
    return render_template('page.html', page='admin', students=db.students(path), books=db.books(path), editing=book)

@app.post('/student/<int:student_id>/delete')
def student_delete(student_id):
    db.delete_student(path, student_id)
    flash('Student deleted. Historical loans kept.')
    return redirect(url_for('admin'))

@app.post('/book/<int:book_id>/delete')
def book_delete(book_id):
    db.delete_book(path, book_id)
    flash('Book deleted. Historical loans kept.')
    return redirect(url_for('admin'))

@app.get('/loans')
def loans():
    query = request.args.get('q', '')
    event = request.args.get('event', 'all')
    return render_template('page.html', page='loans', events=db.loan_log(path, query, event), query=query, event=event)

@app.route('/scan-add', methods=['GET', 'POST'])
def scan_add():
    book = {'isbn': request.form.get('isbn', ''), 'title': request.form.get('title', ''), 'author': request.form.get('author', ''), 'barcode': request.form.get('barcode', '')}
    if request.method == 'POST':
        try:
            action = request.form.get('action')
            if action == 'scan':
                book['barcode'] = read_camera_barcode()
                try:
                    book['isbn'] = db.resolve_barcode(path, book['barcode'])
                except ValueError:
                    flash('Barcode read. Enter the printed ISBN to link this barcode to the book.')
            elif action == 'lookup':
                book.update(db.lookup_book(book['isbn']))
            elif action == 'save':
                isbn = db.clean_isbn(book['isbn'])
                existing = db.get_book_by_isbn(path, isbn)
                if existing:
                    db.save_book(path, existing['id'], existing['isbn'], existing['title'], existing['author'], book['barcode'].strip() or None)
                else:
                    db.save_book(path, None, book['isbn'], book['title'], book['author'], book['barcode'])
                flash('Book saved.')
                return redirect(url_for('admin'))
            else:
                raise ValueError('Choose scan, lookup, or save.')
        except ValueError as error:
            flash(str(error))
    return render_template('page.html', page='scan_add', book=book)

@app.post('/camera/<action>')
def camera_action(action):
    if action == 'start':
        camera.start()
    elif action == 'stop':
        camera.stop()
        session.pop('selected', None)
    else:
        abort(404)
    destination = request.form.get('next', '/')
    editing_student = destination.startswith('/student/') and destination[9:].isdigit()
    if not editing_student and destination not in ['/', '/register', '/scan-add', '/return']:
        destination = '/'
    return redirect(destination)

@app.get('/api/detect')
def detect():
    frame, jpeg, histogram, message = camera.snapshot()
    name = None
    school_id = None
    score = None
    if histogram is not None:
        student, score = find_match(histogram, db.students(path))
        if student is None:
            message = 'No match found. Register the student or capture a new sample.'
        else:
            name = student['name']
            school_id = student['school_id']
        if score == float('inf'):
            score = None
        else:
            score = round(score, 4)
    return jsonify(has_frame=frame is not None, name=name, school_id=school_id,
                   score=score, message=message)


@app.get('/video_feed')
def video_feed():
    def frames():
        while True:
            jpeg = camera.snapshot()[1]
            if jpeg:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
            time.sleep(0.15)
    return Response(frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False, threaded=True)
