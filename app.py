import math
import shutil
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from detector import Detector, draw
from download_model import download, verify, SIZE, PATH

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'work'
WORK.mkdir(exist_ok=True)
app = FastAPI()
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
lock = threading.RLock()
operation = threading.Lock()
stop = threading.Event()
worker = None
model = None
model_state = {'status': 'Проверка модели…', 'ready': False, 'downloading': False, 'bytes': 0}
state = {'pending': False, 'status': 'Загрузите фото или видео.', 'running': False, 'frame': 0, 'total': 0, 'fps': 0, 'count': 0, 'maximum': 0, 'download': False}
video = None
latest = None


def load_model():
    global model
    with lock:
        model_state.update(status='Проверка и загрузка модели…', ready=False)
    try:
        detector = Detector()
        with lock:
            model = detector
            model_state.update(status=f'Модель готова к работе ({detector.device.type.upper()})', ready=True)
        maybe_start()
    except Exception as exc:
        with lock:
            model = None
            model_state.update(status='Модель недоступна: ' + str(exc), ready=False)


def download_task():
    try:
        def progress(n):
            with lock:
                model_state['bytes'] = n
        download(progress)
        load_model()
    except Exception as exc:
        with lock:
            model_state.update(status='Ошибка загрузки модели: ' + str(exc), ready=False)
    finally:
        with lock:
            model_state['downloading'] = False


@app.on_event('startup')
def startup():
    threading.Thread(target=load_model, daemon=True).start()

@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')

@app.get('/api/status')
def status():
    with lock:
        return {'model': dict(model_state), 'state': dict(state), 'video': video, 'model_size': SIZE}

@app.post('/api/model/check')
def check_model():
    with lock:
        if model_state['downloading'] or state['running']:
            raise HTTPException(409, 'Дождитесь окончания текущей операции.')
        model_state['downloading'] = True
    def check():
        try:
            load_model()
        finally:
            with lock:
                model_state['downloading'] = False
    threading.Thread(target=check, daemon=True).start()
    return {'ok': True}

@app.post('/api/model/download')
def download_model():
    with lock:
        if model_state['downloading'] or state['running']:
            raise HTTPException(409, 'Дождитесь окончания текущей операции.')
        model_state.update(downloading=True, bytes=0, status='Скачивание модели…')
    threading.Thread(target=download_task, daemon=True).start()
    return {'ok': True}


def stop_and_wait():
    global worker
    stop.set()
    if worker and worker.is_alive():
        worker.join()
    worker = None


def clean():
    global video, latest
    stop_and_wait()
    for p in WORK.iterdir():
        if p.is_file():
            p.unlink(missing_ok=True)
    with lock:
        video = None
        latest = None
        state.update(pending=False, status='Загрузите фото или видео.', running=False, frame=0, total=0, fps=0, count=0, maximum=0, download=False)

@app.post('/api/reset')
def reset():
    with operation:
        clean()
    return {'ok': True}

@app.post('/api/upload')
def upload(file: UploadFile = File(...)):
    global video, latest
    ext = Path(file.filename or '').suffix.lower()
    if ext not in ('.mp4', '.avi', '.mov', '.jpg', '.jpeg', '.png', '.webp'):
        raise HTTPException(400, 'Выберите фото JPG, PNG или WebP либо видео MP4, AVI или MOV.')
    with operation:
        clean()
        path = WORK / ('input' + ext)
        try:
            with path.open('wb') as out:
                shutil.copyfileobj(file.file, out, length=1024*1024)
            if not path.stat().st_size:
                raise ValueError('Файл пуст.')
            if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                try:
                    with Image.open(path) as image:
                        image = ImageOps.exif_transpose(image).convert('RGB')
                        frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                except Exception as exc:
                    raise ValueError('Не удалось прочитать фото. Возможно, файл повреждён.') from exc
                h, w = frame.shape[:2]
                info = {'kind': 'photo', 'name': Path(file.filename).name, 'width': w, 'height': h, 'fps': 0, 'total': 1, 'duration': None, 'path': str(path)}
            else:
                cap = cv2.VideoCapture(str(path))
                try:
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        raise ValueError('Не удалось прочитать видео. Файл повреждён или кодек не поддерживается.')
                    h, w = frame.shape[:2]
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    if not math.isfinite(fps) or fps <= 0 or fps > 1000:
                        fps = 25.0
                    raw_total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    total = int(raw_total) if math.isfinite(raw_total) and raw_total > 0 else 0
                    info = {'kind': 'video', 'name': Path(file.filename).name, 'width': w, 'height': h, 'fps': fps, 'total': total, 'duration': total/fps if total else None, 'path': str(path)}
                finally:
                    cap.release()
            ok, jpeg = cv2.imencode('.jpg', frame)
            with lock:
                video = info
                latest = jpeg.tobytes() if ok else None
                state.update(pending=True, status='Ожидание готовности модели…', total=info['total'])
        except (OSError, ValueError) as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(400, f'Не удалось загрузить видео: {exc}')
        finally:
            file.file.close()
    maybe_start()
    return {'ok': True}

class Options(BaseModel):
    confidence: float = .35
    skip: int = 1
    size: int = 600

def maybe_start():
    global worker
    with operation:
        with lock:
            if not state['pending'] or state['running'] or not video or not model_state['ready'] or model is None:
                return
            stop.clear()
            state.update(pending=False, running=True, status='Начинаем обработку…', frame=0, count=0, maximum=0, fps=0, download=False)
            target = process_photo if video['kind'] == 'photo' else process
            worker = threading.Thread(target=target, args=(dict(video), Options(), model), daemon=True)
            worker.start()


def process_photo(info, opts, detector):
    global latest
    try:
        started = time.monotonic()
        with Image.open(info['path']) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        boxes = detector.detect(frame, opts.size, opts.confidence)
        if stop.is_set():
            with lock:
                state.update(running=False, status='Обработка остановлена.')
            return
        result = draw(frame, boxes)
        ok, encoded = cv2.imencode('.png', result)
        if not ok:
            raise RuntimeError('Не удалось сохранить обработанное фото.')
        (WORK / 'result.png').write_bytes(encoded.tobytes())
        ok, preview = cv2.imencode('.jpg', result)
        with lock:
            if ok:
                latest = preview.tobytes()
            state.update(running=False, frame=1, count=len(boxes), maximum=len(boxes), fps=1/max(time.monotonic()-started, .001), download=True, status='Обработка завершена.')
    except Exception as exc:
        with lock:
            state.update(running=False, status='Ошибка обработки: ' + str(exc))

@app.post('/api/start')
def start(options: Options):
    global worker
    with operation:
        with lock:
            if state['running'] or not video or not model_state['ready'] or model_state['downloading']:
                raise HTTPException(409, 'Загрузите видео и дождитесь готовности модели.')
            if options.skip not in (1,2,3,5,10) or options.size not in (480,600,960) or not .15 <= options.confidence <= .9:
                raise HTTPException(400, 'Недопустимые параметры обработки.')
            stop.clear()
            state.update(pending=False, running=True, status='Начинаем обработку…', frame=0, count=0, maximum=0, fps=0, download=False)
            worker = threading.Thread(target=process_photo if video['kind'] == 'photo' else process, args=(dict(video), options, model), daemon=True)
            worker.start()
    return {'ok': True}


def process(info, opts, detector):
    global latest
    cap = writer = None
    output = WORK / 'result.mp4'
    frames = 0
    started = time.monotonic()
    error = None
    try:
        cap = cv2.VideoCapture(info['path'])
        if not cap.isOpened():
            raise RuntimeError('Не удалось открыть исходное видео.')
        writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*'mp4v'), info['fps'], (info['width'], info['height']))
        if not writer.isOpened():
            raise RuntimeError('Не удалось создать MP4. Проверьте доступное место и поддержку кодека.')
        boxes = []
        while not stop.is_set():
            ok, frame = cap.read()
            if not ok:
                break
            if frames % opts.skip == 0:
                boxes = detector.detect(frame, opts.size, opts.confidence)
            if stop.is_set():
                break
            result = draw(frame, boxes)
            writer.write(result)
            frames += 1
            ok, jpeg = cv2.imencode('.jpg', result, [cv2.IMWRITE_JPEG_QUALITY, 80])
            with lock:
                if ok: latest = jpeg.tobytes()
                state.update(frame=frames, count=len(boxes), maximum=max(state['maximum'], len(boxes)), fps=frames/max(time.monotonic()-started, .001), status='Идёт обработка видео…')
    except Exception as exc:
        error = str(exc)
    finally:
        if cap: cap.release()
        if writer: writer.release()
        valid = False
        if frames and output.exists() and output.stat().st_size:
            check = cv2.VideoCapture(str(output))
            valid = check.isOpened() and check.read()[0]
            check.release()
        with lock:
            state.update(running=False, download=valid, status=('Ошибка обработки: '+error if error else ('Обработка остановлена.' if stop.is_set() else ('Обработка завершена.' if valid else 'Не удалось создать читаемое видео.'))))

@app.post('/api/stop')
def stop_processing():
    stop.set()
    with lock:
        was_pending = state['pending']
        state['pending'] = False
        if state['running']:
            state['status'] = 'Остановка после текущего кадра…'
        elif was_pending:
            state['status'] = 'Обработка остановлена.'
    return {'ok': True}

@app.get('/api/stream')
def stream():
    def generate():
        previous = None
        while True:
            with lock:
                frame = latest
            if frame is not None and frame is not previous:
                previous = frame
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
            time.sleep(.04)
    return StreamingResponse(generate(), media_type='multipart/x-mixed-replace; boundary=frame', headers={'Cache-Control':'no-store'})

@app.get('/api/result')
def result():
    with lock:
        if not state['download'] or state['running']:
            raise HTTPException(404, 'Обработанное видео пока недоступно.')
        kind = video['kind']
    if kind == 'photo':
        return FileResponse(WORK / 'result.png', media_type='image/png', filename='burrows.png')
    return FileResponse(WORK / 'result.mp4', media_type='video/mp4', filename='burrows.mp4')
