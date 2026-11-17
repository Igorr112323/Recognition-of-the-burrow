@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHON="
py -3 -c "import sys; assert (3,9) <= sys.version_info[:2] <= (3,13)" >nul 2>&1
if not errorlevel 1 set "PYTHON=py -3"
if defined PYTHON goto python_ok
python -c "import sys; assert (3,9) <= sys.version_info[:2] <= (3,13)" >nul 2>&1
if not errorlevel 1 set "PYTHON=python"
if defined PYTHON goto python_ok
echo Установите Python версии 3.9–3.13 с сайта python.org и включите добавление Python в PATH.
pause
exit /b 1
:python_ok
if exist ".venv\Scripts\python.exe" goto venv_ok
%PYTHON% -m venv ".venv"
if errorlevel 1 goto failed
:venv_ok
if not exist ".venv\.deps_ok" goto install
".venv\Scripts\python.exe" -c "import torch, torchvision, cv2, PIL, fastapi, uvicorn, requests, multipart" >nul 2>&1
if not errorlevel 1 goto dependencies_ok
:install
if exist ".venv\.deps_ok" del ".venv\.deps_ok"
echo Установка компонентов. При первом запуске потребуется интернет и некоторое время.
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import torch, torchvision, cv2, PIL, fastapi, uvicorn, requests, multipart"
if errorlevel 1 goto failed
>".venv\.deps_ok" echo ok
:dependencies_ok
".venv\Scripts\python.exe" "download_model.py"
".venv\Scripts\python.exe" "launcher.py"
if errorlevel 1 goto failed
exit /b 0
:failed
echo Произошла ошибка запуска или установки. Проверьте сообщение выше, интернет и свободное место.
pause
exit /b 1
