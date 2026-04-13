#!/bin/bash
# File Modifier Pro - Web Startup Script (Venv Mode)

VENV_DIR="venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "Checking dependencies..."
pip install --upgrade pip
pip install -r requirements.txt | grep -v 'already satisfied'

echo ""
echo "Starting Web Server..."
echo "Please open http://127.0.0.1:8000 in your browser."
python3 app.py
