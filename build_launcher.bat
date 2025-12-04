@echo off
cd /d "%~dp0"
echo ========================================
echo Building Bandcamp Downloader Launcher
echo ========================================
echo.

echo [0/4] Checking Python version...
python --version
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo.
echo Checking if Python version is 3.11...
python -c "import sys; exit(0 if sys.version_info >= (3, 11) and sys.version_info < (3, 12) else 1)"
if errorlevel 1 (
    echo.
    echo WARNING: Python version check failed!
    echo.
    echo The launcher must be built with Python 3.11 for Windows 7 compatibility.
    echo Python 3.12+ does NOT support Windows 7.
    echo.
    echo Current Python version: 
    python --version
    echo.
    echo Please ensure you are using Python 3.11.x
    echo You can download it from: https://www.python.org/downloads/release/python-3110/
    echo.
    set /p CONTINUE="Continue anyway? (y/N): "
    if /i not "%CONTINUE%"=="y" (
        echo Build cancelled.
        pause
        exit /b 1
    )
)
echo Python version OK for Windows 7 compatibility.
echo.

echo [1/4] Installing/upgrading PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install PyInstaller
    pause
    exit /b 1
)
echo.

echo [2/4] Installing/upgrading required dependencies...
python -m pip install --upgrade requests pillow yt-dlp tkinterdnd2
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

echo [3/4] Verifying PyInstaller version...
pyinstaller --version
echo.

echo [4/4] Building launcher with PyInstaller...
echo This will bundle Python %PYTHON_VERSION% into the executable.
echo.
pyinstaller launcher.spec --clean
if errorlevel 1 (
    echo ERROR: Build failed
    pause
    exit /b 1
)
echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo.
echo IMPORTANT: The EXE was built with Python %PYTHON_VERSION%
echo This version %PYTHON_VERSION% is compatible with Windows 7.
echo.
pause

