@echo off
REM Builds dist\R3cket.exe - a single file you can copy to any Windows 10/11 laptop.
REM Needs Python 3.9+ from python.org (tick "Add Python to PATH" when installing).

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name R3cket R3cket.pyw
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)
echo.
echo Done: dist\R3cket.exe
