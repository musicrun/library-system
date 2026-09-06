"""Run once with an internet connection before using the camera."""
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)
Path('.yolo').mkdir(exist_ok=True)
os.environ.setdefault('YOLO_CONFIG_DIR', str(Path('.yolo').resolve()))
from ultralytics import YOLO

YOLO('yolov8n.pt')
print('YOLOv8n model is ready.')
