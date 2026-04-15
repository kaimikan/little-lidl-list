@echo off
title Little Lidl List
cd /d "%~dp0"

if not exist .venv (
    echo Setting up virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -e .
    playwright install chromium
) else (
    call .venv\Scripts\activate.bat
)

echo Starting Little Lidl List...
python -m lidl.app
