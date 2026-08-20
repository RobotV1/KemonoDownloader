# -*- coding: utf-8 -*-
"""
KemonoDownloader 打包入口（PyInstaller --windowed 单 exe）。

- 无命令行参数：启动图形界面（UI），无控制台窗口。
- 有命令行参数：CLI 模式，行为与 main.py 完全一致；
  Windows 下尝试挂接父进程控制台以显示日志输出。
"""

import os
import sys


def _redirect_stdio():
    """仅打包（--windowed）后需要处理：UI 模式静默，CLI 模式挂接父控制台。"""
    if not getattr(sys, "frozen", False):
        return  # 源码模式已有控制台，无需处理
    devnull = open(os.devnull, "w", encoding="utf-8", errors="replace")
    sys.stdout = devnull
    sys.stderr = devnull
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            if kernel32.AttachConsole(-1):
                console_out = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                sys.stdout = console_out
                sys.stderr = console_out
                sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    if getattr(sys, "frozen", False):
        # 保证 aria2c.exe / aria2.conf / ui_config.json 相对解析到 exe 所在目录
        os.chdir(os.path.dirname(os.path.abspath(sys.executable)))

    try:
        if len(sys.argv) > 1:
            # CLI 模式：行为与 main.py 相同
            _redirect_stdio()
            import main as kd
            kd.main(sys.argv[1:])
            return

        # UI 模式
        _redirect_stdio()
        import ui
        ui.main()
    except Exception:
        import traceback
        traceback.print_exc()
        if getattr(sys, "frozen", False):
            try:
                debug_path = os.path.join(
                    os.path.dirname(os.path.abspath(sys.executable)),
                    "KemonoDownloader.error.log",
                )
                with open(debug_path, "w", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
            except Exception:
                pass
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0,
                    _fallback_i18n(
                        "程序发生未处理异常，详细信息已写入程序目录下的 KemonoDownloader.error.log。",
                        "An unhandled error occurred; details were written to KemonoDownloader.error.log next to the program.",
                    ),
                    "KemonoDownloader",
                    0x10,
                )
            except Exception:
                pass
        raise


def _fallback_i18n(zh: str, en: str) -> str:
    """异常兜底路径使用的语言判断（不依赖 main 模块）。"""
    override = os.environ.get("KEMONO_DOWNLOADER_LANG", "").strip().lower()
    if override:
        return zh if override.startswith("zh") else en
    try:
        import locale
        lang = locale.getdefaultlocale()[0] or ""
        return zh if lang.lower().startswith("zh") else en
    except Exception:
        return zh


if __name__ == "__main__":
    main()
