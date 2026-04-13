@echo off
setlocal
set VENV_DIR=venv

echo Checking for virtual environment...
if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    python -m venv %VENV_DIR%
)

echo Activating virtual environment...
call %VENV_DIR%\Scripts\activate

echo Checking dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Starting Web Server...
echo Please open http://127.0.0.1:8000 in your browser.
python app.py

pause
