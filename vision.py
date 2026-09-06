"""Experimental histogram matching, not secure facial recognition."""
import threading
import time
from pathlib import Path
from database import clean_barcode

THRESHOLD = 0.30


def make_histogram(crop):
    import cv2
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (64, 64))
    histogram = cv2.calcHist([gray], [0], None, [32], [0, 256]).flatten()
    # Peak normalization gives bins in [0, 1]; similar brightness does not prove identity.
    histogram = histogram / histogram.max()
    return histogram.tolist()


def find_match(histogram, students, threshold=THRESHOLD):
    best_student = None
    best_score = float('inf')
    for student in students:
        stored = student['histogram'].split(',')
        total = 0
        for i in range(32):
            total += abs(histogram[i] - float(stored[i]))
        score = total / 32
        if score < best_score:
            best_score = score
            best_student = student
    if best_score >= threshold:
        best_student = None
    return best_student, best_score


class Camera:
    """One background worker shares the latest frame with Flask requests."""
    def __init__(self, index=0):
        self.index = index
        self.lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()
        self.frame = None
        self.jpeg = None
        self.histogram = None
        self.updated_at = 0
        self.overlay = None
        self.overlay_until = 0
        self.message = 'Camera is off. Click Start camera.'

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.message = 'Starting camera and loading YOLO…'
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        with self.lock:
            self.frame = self.jpeg = self.histogram = None
            self.overlay = None
            self.message = 'Camera is off. Click Start camera.'

    def show_preview(self, jpeg):
        with self.lock:
            self.overlay = jpeg
            self.overlay_until = time.monotonic() + 2

    def snapshot(self):
        with self.lock:
            fresh = time.monotonic() - self.updated_at < 3 and not self.stop_event.is_set()
            if not fresh:
                message = self.message
                if self.frame is not None and not self.stop_event.is_set():
                    message = 'Waiting for a fresh camera frame.'
                return None, None, None, message
            frame = self.frame.copy() if self.frame is not None else None
            histogram = self.histogram[:] if self.histogram is not None else None
            jpeg = self.jpeg
            if time.monotonic() < self.overlay_until:
                jpeg = self.overlay
            return frame, jpeg, histogram, self.message


    def run(self):
        capture = None
        try:
            import cv2
            from ultralytics import YOLO
            weights = Path(__file__).with_name('yolov8n.pt')
            model = YOLO(str(weights))
            capture = cv2.VideoCapture(self.index)
            if not capture.isOpened():
                raise RuntimeError('Cannot open webcam. Check camera permission and close other camera apps.')
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError('Webcam disconnected. Stop and restart the camera.')
                result = model.predict(frame, classes=[0], conf=0.5, verbose=False)[0]
                boxes = result.boxes.xyxy.cpu().tolist()
                histogram = None
                message = 'No person detected. Stand in front of the camera.'
                preview = frame.copy()
                if boxes:
                    largest = boxes[0]
                    largest_area = 0
                    for box in boxes:
                        area = (box[2] - box[0]) * (box[3] - box[1])
                        if area > largest_area:
                            largest = box
                            largest_area = area
                    x1 = int(largest[0])
                    y1 = int(largest[1])
                    x2 = int(largest[2])
                    y2 = int(largest[3])
                    height, width = frame.shape[:2]
                    x1, x2 = max(0, x1), min(width, x2)
                    y1, y2 = max(0, y1), min(height, y2)
                    head_bottom = y1 + max(1, int((y2-y1) * 0.25))
                    crop = frame[y1:head_bottom, x1:x2]
                    if crop.size:
                        histogram = make_histogram(crop)
                        message = 'Person detected. Keep your head inside the small box.'
                        cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 180, 0), 2)
                        cv2.rectangle(preview, (x1, y1), (x2, head_bottom), (0, 180, 255), 2)
                ok, encoded = cv2.imencode('.jpg', preview)
                if not ok:
                    raise RuntimeError('Could not encode camera frame.')
                with self.lock:
                    self.frame = frame
                    self.jpeg = encoded.tobytes()
                    self.histogram = histogram
                    self.updated_at = time.monotonic()
                    self.message = message
                self.stop_event.wait(0.1)
        except Exception as error:
            with self.lock:
                self.message = f'Camera unavailable: {error}'
                self.frame = self.jpeg = self.histogram = None
        finally:
            if capture is not None:
                capture.release()


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


