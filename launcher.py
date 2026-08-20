# -*- coding: utf-8 -*-
"""
KemonoDownloader 统一入口（用于打包为单 exe）。

- 无参数运行        -> 打开图形界面（ui.main），并隐藏控制台窗口；
- 传入任何参数运行  -> 命令行模式，行为与原版 main.py 一致（main.main）。
"""

import os
import sys


def hide_console_window() -> None:
    """隐藏 Windows 控制台窗口（双击启动 UI 时避免残留黑框）。

    判定规则（满足其一才隐藏）：
      1. 控制台由本进程独占（onedir 等单进程场景）；
      2. 控制台窗口标题等于本 exe 完整路径——Windows 为双击启动的
         控制台程序新建的控制台标题即程序完整路径，而从 cmd/PowerShell
         等已有终端启动时标题是终端自己的，不会误隐藏用户的终端窗口。
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return

        process_ids = (ctypes.c_ulong * 16)()
        if kernel32.GetConsoleProcessList(process_ids, 16) == 1:
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
            return

        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, 512)
        if title_buf.value and os.path.normcase(title_buf.value) == os.path.normcase(
                os.path.abspath(sys.executable)):
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def _fallback_i18n(zh: str, en: str) -> str:
    """异常兜底路径使用的语言判断（不依赖 main 模块）。"""
    override = os.environ.get("KEMONO_DOWNLOADER_LANG", "").strip().lower()
    if override:
        return zh if override.startswith("zh") else en
    try:
        import locale
        lang = locale.getlocale()[0] or ""
        return zh if lang.lower().startswith("zh") else en
    except Exception:
        return zh


def _run() -> None:
    if len(sys.argv) > 1:
        # 命令行模式：完整转发参数，行为与 main.py 一致
        import main as kd

        kd.main()
    else:
        # 无参数：隐藏控制台并打开 UI
        hide_console_window()
        import ui

        ui.main()


def main() -> None:
    try:
        _run()
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


if __name__ == "__main__":
    main()
