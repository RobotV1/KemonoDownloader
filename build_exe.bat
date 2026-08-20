@echo off
rem Build KemonoDownloader single-file exe (UI + CLI dual mode)
rem Usage: build_exe.bat
setlocal

set VENV_PY=.venv-build\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo [1/3] Creating build venv .venv-build ...
    python -m venv .venv-build || exit /b 1
    "%VENV_PY%" -m pip install --quiet requests pyinstaller || exit /b 1
)

rem In a venv, tkinter cannot auto-locate the Tcl/Tk data dirs; set them
rem explicitly or the frozen app will be built WITHOUT UI support.
for /f "delims=" %%I in ('%VENV_PY% -c "import sys,os;print(os.path.join(os.path.dirname(getattr(sys,'_base_executable',sys.executable)),'tcl'))"') do set TCL_ROOT=%%I
set TCL_LIBRARY=%TCL_ROOT%\tcl8.6
set TK_LIBRARY=%TCL_ROOT%\tk8.6
echo TCL_LIBRARY=%TCL_LIBRARY%

echo [2/3] Removing old build artifacts ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] Running PyInstaller ...
"%VENV_PY%" -m PyInstaller --onefile --console --name KemonoDownloader ^
    --icon pawchive_favicon.ico ^
    --add-data "pawchive_favicon.ico;." ^
    --exclude-module pip --exclude-module setuptools --exclude-module lib2to3 ^
    --exclude-module pydoc --exclude-module turtle --exclude-module turtledemo ^
    launcher.py || exit /b 1

echo.
echo Build finished: dist\KemonoDownloader.exe
endlocal
