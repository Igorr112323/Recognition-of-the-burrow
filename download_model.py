"""Проверка и загрузка готовых весов детектора."""
import hashlib
import os
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
PATH = ROOT / 'model_data' / 'best_epoch_weights.pth'
URL = 'https://zenodo.org/records/17491180/files/best_epoch_weights.pth?download=1'
SIZE = 146818258
MD5 = 'dd49f63c0e1eba57654eb42585c1da06'


def verify(path=PATH):
    if not path.is_file():
        return False, 'Файл модели не найден.'
    if path.stat().st_size != SIZE:
        return False, 'Неверный размер файла модели.'
    digest = hashlib.md5()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != MD5:
        return False, 'Контрольная сумма файла модели не совпадает.'
    return True, ''


def download(progress=lambda n: None):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    part = PATH.with_name(PATH.name + '.part')
    if verify()[0]:
        progress(SIZE)
        return
    error = None
    for attempt in range(3):
        try:
            progress(0)
            with requests.get(URL, stream=True, timeout=(15, 60)) as response:
                response.raise_for_status()
                with part.open('wb') as f:
                    count = 0
                    for chunk in response.iter_content(1024 * 256):
                        if chunk:
                            f.write(chunk)
                            count += len(chunk)
                            progress(count)
            ok, reason = verify(part)
            if not ok:
                raise ValueError(reason)
            os.replace(part, PATH)
            return
        except (requests.RequestException, OSError, ValueError) as exc:
            error = exc
            part.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(1)
    if isinstance(error, requests.RequestException):
        raise RuntimeError('Не удалось соединиться с сервером модели или загрузка прервалась. Проверьте интернет и повторите попытку.') from error
    if isinstance(error, OSError):
        raise RuntimeError('Не удалось записать файл модели. Проверьте права доступа и свободное место на диске.') from error
    raise RuntimeError('Скачанный файл модели не прошёл проверку размера или контрольной суммы.') from error

if __name__ == '__main__':
    try:
        download(lambda n: print(f'\rЗагрузка: {n / 1048576:.1f} МБ / {SIZE / 1048576:.1f} МБ ({100*n/SIZE:.1f}%)', end='', flush=True))
        print('\nФайл модели проверен.')
    except Exception as exc:
        print(f'\n{exc}\nСкачайте файл вручную: {URL}\nПоместите его в {PATH}')
