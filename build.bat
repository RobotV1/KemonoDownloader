@echo off
REM ============================================================
REM KemonoDownloader 打包脚本（单文件 exe，仅主程序，不含 aria2c）
REM 产物: dist\KemonoDownloader.exe
REM 前置: pip install pyinstaller
REM ============================================================

python -m pip install pyinstaller || goto :error

python -m PyInstaller --noconfirm --clean --onefile --windowed --name KemonoDownloader ^
  --icon=pawchive_favicon.ico --optimize 2 ^
  --exclude-module numpy --exclude-module PIL --exclude-module unittest ^
  --exclude-module pydoc --exclude-module pydoc_data ^
  --add-data "pawchive_favicon.ico;." ^
  launcher.py || goto :error

echo.
echo 打包完成: dist\KemonoDownloader.exe
echo 使用本地下载时，请将 aria2c.exe 放到 exe 同目录（aria2.conf 缺失会自动生成）。
exit /b 0

:error
echo 打包失败。
exit /b 1
