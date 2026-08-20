# -*- coding: utf-8 -*-
"""
KemonoDownloader 图形界面（Tkinter）。

启动: python ui.py
所有下载逻辑复用 main.py；本文件仅负责参数收集、配置持久化和进度展示。
"""

import json
import logging
import os
import queue
import re
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from urllib.parse import urlparse

import main as kd

i18n = kd.i18n

BASE_DIR = os.path.dirname(
    os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)
)
UI_CONFIG_PATH = os.path.join(BASE_DIR, "ui_config.json")


def _resource_path(name: str) -> str:
    """打包（--onefile）时资源位于 sys._MEIPASS，源码模式位于程序目录。"""
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", BASE_DIR)
        return os.path.join(bundle, name)
    return os.path.join(BASE_DIR, name)

# 编号模式: (内部值, 中文显示, 英文显示)
NUMBERING_MODES = [
    (kd.NUMBER_ATTACHMENTS_OFF, "关闭", "off"),
    (kd.NUMBER_ATTACHMENTS_ALL, "全部", "all"),
    (kd.NUMBER_ATTACHMENTS_IMAGES, "仅图片", "images only"),
    (kd.NUMBER_ATTACHMENTS_RENAME_ALL, "仅重命名", "rename only (no download)"),
    (kd.NUMBER_ATTACHMENTS_RENAME_IMAGES, "仅重命名图片", "rename images only (no download)"),
]
RENAME_MODES = (kd.NUMBER_ATTACHMENTS_RENAME_ALL, kd.NUMBER_ATTACHMENTS_RENAME_IMAGES)

EXISTING_FILE_MODES = list(kd.EXISTING_FILE_MODES)

# UI 中可编辑的 aria2.conf 选项: (键, 默认值)
ARIA2_OPTIONS = [
    ("max-concurrent-downloads", "5"),
    ("split", "5"),
    ("max-connection-per-server", "16"),
    ("max-overall-download-limit", ""),
    ("max-download-limit", ""),
]

DEFAULT_UI_CONFIG = {
    "folder": "",
    "number_attachments": kd.NUMBER_ATTACHMENTS_IMAGES,
    "base_url": "https://pawchive.pw/",
    "file_server": "https://file.pawchive.pw/",
    "proxy_url": "",
    "proxy_enabled": False,
    "max_retries": "5",
    "base_backoff_factor": "3.0",
    "kemono_mode": False,
    "existing_file": kd.EXISTING_FILE_VERIFY,
    "pipeline": True,
    "aria2_rpc_url": "",
}


# ---------------------------
# 配置文件 & aria2.conf
# ---------------------------
def load_ui_config() -> dict:
    """载入 ui_config.json；缺失或损坏时按默认配置自动生成。"""
    if not os.path.exists(UI_CONFIG_PATH):
        save_ui_config(DEFAULT_UI_CONFIG)
        return dict(DEFAULT_UI_CONFIG)
    try:
        with open(UI_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("config root is not an object")
    except Exception:
        save_ui_config(DEFAULT_UI_CONFIG)
        return dict(DEFAULT_UI_CONFIG)
    merged = dict(DEFAULT_UI_CONFIG)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_UI_CONFIG})
    return merged


def save_ui_config(config: dict) -> None:
    try:
        with open(UI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except OSError as e:
        kd.logger.warning(i18n(
            f"保存界面配置失败: {e}",
            f"Failed to save UI config: {e}",
        ))


def read_aria2_conf_options(conf_path: str = kd.ARIA2_CONF_PATH) -> dict:
    """读取 aria2.conf 中 UI 关心的键值（不含注释行）。"""
    values = {}
    if not os.path.exists(conf_path):
        return values
    try:
        with open(conf_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def write_aria2_conf_options(updates: dict, conf_path: str = kd.ARIA2_CONF_PATH) -> None:
    """
    按行改写 aria2.conf：保留注释与无关行；
    值为空时注释掉该键（恢复原默认），值非空时写入 key=value，键不存在则追加。
    """
    kd.ensure_aria2_conf(conf_path)
    try:
        with open(conf_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []

    remaining = dict(updates)
    out_lines = []
    for line in lines:
        stripped = line.strip()
        candidate = stripped[1:].strip() if stripped.startswith("#") else stripped
        key, sep, _ = candidate.partition("=")
        key = key.strip()
        if sep and key in remaining:
            value = remaining.pop(key)
            out_lines.append(f"{key}={value}" if value else f"#{key}=")
        else:
            out_lines.append(line)
    for key, value in remaining.items():
        out_lines.append(f"{key}={value}" if value else f"#{key}=")

    with open(conf_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")


# ---------------------------
# URL 识别 & 参数组装
# ---------------------------
def parse_creator_url(url: str, base_url: str) -> tuple:
    """
    从完整 URL 中识别 (service, userid)。
    - 主机名必须与 base_url 的主机名一致，否则抛 ValueError；
    - 路径须形如 /{service}/user/{userid}，其后的 /post/* 等后缀及 query/fragment 一律忽略。
    """
    url = (url or "").strip()
    if not url:
        raise ValueError(i18n("URL 为空", "URL is empty"))

    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)

    base = (base_url or "").strip()
    if "://" not in base:
        base = "https://" + base
    base_parsed = urlparse(base)

    if not parsed.hostname:
        raise ValueError(i18n(f"无法解析 URL: {url}", f"Cannot parse URL: {url}"))

    if parsed.hostname.lower() != (base_parsed.hostname or "").lower():
        raise ValueError(i18n(
            f"URL 主机名 {parsed.hostname} 与基础 URL 的主机名 {base_parsed.hostname} 不一致",
            f"URL host {parsed.hostname} does not match base URL host {base_parsed.hostname}",
        ))

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 3 and parts[1].lower() == "user":
        service, userid = parts[0], parts[2]
        if service and userid:
            return service, userid

    raise ValueError(i18n(
        f"URL 路径不符合 /服务名/user/用户ID 的形式: {parsed.path}",
        f"URL path does not look like /service/user/userid: {parsed.path}",
    ))


def build_argv(
        userid: str,
        service: str,
        folder: str,
        post_begins: str,
        post_counts: str,
        date_from: str,
        date_to: str,
        ext_blacklist: str,
        ext_whitelist: str,
        name_blacklist: str,
        name_whitelist: str,
        name_regex: bool,
        title_blacklist: str,
        title_whitelist: str,
        title_regex: bool,
        number_attachments: str,
        base_url: str,
        file_server: str,
        proxy_url: str,
        max_retries: str,
        base_backoff_factor: str,
        kemono_mode: bool,
        existing_file: str,
        pipeline: bool,
        aria2_rpc_url: str,
) -> list:
    """把界面字段组装为 main.parse_args 可接受的参数列表。"""
    argv = [userid, service]
    argv += ["--base_url", base_url.strip()]
    argv += ["--file_server", file_server.strip()]
    if proxy_url.strip():
        argv += ["--proxy_url", proxy_url.strip()]
    argv += ["--max_retries", str(int(max_retries))]
    argv += ["--base_backoff_factor", str(float(base_backoff_factor))]
    argv += ["--folder", folder.strip() or BASE_DIR]
    argv += ["--post_begins", str(int(post_begins))]
    argv += ["--post_counts", str(int(post_counts))]

    if date_from.strip():
        argv += ["--date_from", date_from.strip()]
    if date_to.strip():
        argv += ["--date_to", date_to.strip()]
    if ext_blacklist.strip():
        argv += ["--ext_blacklist", ext_blacklist.strip()]
    if ext_whitelist.strip():
        argv += ["--ext_whitelist", ext_whitelist.strip()]
    if name_blacklist.strip():
        argv += ["--name_blacklist", name_blacklist.strip()]
    if name_whitelist.strip():
        argv += ["--name_whitelist", name_whitelist.strip()]
    argv += ["--name_regex", "true" if name_regex else "false"]
    if title_blacklist.strip():
        argv += ["--title_blacklist", title_blacklist.strip()]
    if title_whitelist.strip():
        argv += ["--title_whitelist", title_whitelist.strip()]
    argv += ["--title_regex", "true" if title_regex else "false"]

    argv += ["--number_attachments", number_attachments]
    argv += ["--kemono_mode", "true" if kemono_mode else "false"]
    argv += ["--existing_file", existing_file]
    argv += ["--pipeline", "true" if pipeline else "false"]
    if aria2_rpc_url.strip():
        argv += ["--aria2-rpc-url", aria2_rpc_url.strip()]
    return argv


def validate_inputs(
        date_from: str,
        date_to: str,
        name_patterns: list,
        name_regex: bool,
        title_patterns: list,
        title_regex: bool,
) -> None:
    """校验日期格式与正则合法性，非法时抛 ValueError。"""
    for label, value in (("date_from", date_from), ("date_to", date_to)):
        value = value.strip()
        if not value:
            continue
        try:
            kd.parse_date_arg(value)
        except Exception:
            raise ValueError(i18n(
                f"{label} 日期格式无效: {value}，应为 YYYY-MM-DD",
                f"Invalid {label} date: {value}; expected YYYY-MM-DD",
            ))

    for patterns, use_regex, label in (
            (name_patterns, name_regex, i18n("文件名", "filename")),
            (title_patterns, title_regex, i18n("标题", "title")),
    ):
        if not use_regex:
            continue
        for pattern in patterns:
            if not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(i18n(
                    f"{label}过滤正则无效: {pattern} ({e})",
                    f"Invalid {label} filter regex: {pattern} ({e})",
                ))


# ---------------------------
# 日志桥接
# ---------------------------
class QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            pass


# ---------------------------
# 界面组件
# ---------------------------
class CollapsibleFrame(tk.Frame):
    """带标题按钮的可折叠分区，默认折叠。"""

    def __init__(self, master, title: str, collapsed: bool = True,
                 content_fill: str = "x", **kwargs):
        super().__init__(master, **kwargs)
        self._collapsed = collapsed
        self._content_fill = content_fill
        self.toggle_button = tk.Button(
            self,
            text=title,
            anchor="w",
            relief="groove",
            command=self.toggle,
        )
        self.toggle_button.pack(fill="x")
        self.content = tk.Frame(self)
        if not collapsed:
            self.content.pack(fill=self._content_fill, expand=True)
        self._title = title
        self._update_title()

    def _update_title(self):
        marker = "▶ " if self._collapsed else "▼ "
        self.toggle_button.config(text=marker + self._title)

    def toggle(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.content.pack_forget()
        else:
            self.content.pack(fill=self._content_fill, expand=True)
        self._update_title()


def _labeled_entry(parent, label: str, textvariable, width: int = 30, row: int = 0,
                   column: int = 0, label_width: int = 22):
    tk.Label(parent, text=label, width=label_width, anchor="w").grid(
        row=row, column=column, sticky="w", padx=4, pady=2,
    )
    entry = tk.Entry(parent, textvariable=textvariable, width=width)
    entry.grid(row=row, column=column + 1, sticky="w", padx=4, pady=2)
    return entry


def _format_size(num_bytes: float) -> str:
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


class DownloaderUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(i18n("Kemono 下载器", "Kemono Downloader"))
        self.root.geometry("1150x640")
        self._set_window_icon()

        self.config = load_ui_config()
        kd.ensure_aria2_conf()

        self.log_queue = queue.Queue()
        self.worker = None
        self.run_state = "idle"  # idle / running / paused
        self.tree_items = {}  # gid -> treeview item id
        self.settings_windows = {}  # key -> Toplevel

        self._build_variables()
        self._build_layout()
        self._attach_log_handler()

        self.root.after(200, self._poll_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_window_icon(self):
        try:
            if os.name != "nt":
                return
            icon_path = _resource_path("pawchive_favicon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

    # ---------- 变量 ----------
    def _build_variables(self):
        cfg = self.config
        self.url_var = tk.StringVar()
        self.service_var = tk.StringVar()
        self.userid_var = tk.StringVar()

        self.folder_var = tk.StringVar(value=cfg["folder"])
        self.post_begins_var = tk.StringVar(value="1")
        self.post_counts_var = tk.StringVar(value="0")
        self.date_from_var = tk.StringVar()
        self.date_to_var = tk.StringVar()

        self.ext_blacklist_var = tk.StringVar()
        self.ext_whitelist_var = tk.StringVar()
        self.name_blacklist_var = tk.StringVar()
        self.name_whitelist_var = tk.StringVar()
        self.name_regex_var = tk.BooleanVar(value=False)
        self.title_blacklist_var = tk.StringVar()
        self.title_whitelist_var = tk.StringVar()
        self.title_regex_var = tk.BooleanVar(value=False)

        # 高级设置（存入配置文件）
        self.base_url_var = tk.StringVar(value=cfg["base_url"])
        self.file_server_var = tk.StringVar(value=cfg["file_server"])
        self.proxy_url_var = tk.StringVar(value=cfg["proxy_url"])
        self.proxy_enabled_var = tk.BooleanVar(value=bool(cfg["proxy_enabled"]))
        self.max_retries_var = tk.StringVar(value=str(cfg["max_retries"]))
        self.backoff_var = tk.StringVar(value=str(cfg["base_backoff_factor"]))
        self.kemono_mode_var = tk.BooleanVar(value=bool(cfg["kemono_mode"]))
        self.pipeline_var = tk.BooleanVar(value=bool(cfg["pipeline"]))

        self.number_attachments_var = tk.StringVar(value=cfg["number_attachments"])
        self.existing_file_var = tk.StringVar(value=cfg["existing_file"])

        # Aria2 设置
        self.aria2_rpc_url_var = tk.StringVar(value=cfg["aria2_rpc_url"])
        conf_values = read_aria2_conf_options()
        self.aria2_option_vars = {
            key: tk.StringVar(value=conf_values.get(key, default))
            for key, default in ARIA2_OPTIONS
        }

    # ---------- 布局 ----------
    def _build_layout(self):
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill="both", expand=True)

        # 左栏：全部设置项
        left = tk.Frame(main_frame)
        left.pack(side="left", fill="y", padx=6, pady=4)

        # 右栏：下载任务
        right = tk.Frame(main_frame)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=4)

        # 目标（无标题）
        target = tk.Frame(left)
        target.pack(fill="x", pady=2)
        _labeled_entry(
            target,
            i18n("创作者 URL（粘贴自动识别）", "Creator URL (auto-parsed)"),
            self.url_var, width=44, row=0, label_width=24,
        )
        self.url_var.trace_add("write", lambda *_: self._auto_parse_url())
        cred_row = tk.Frame(target)
        cred_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=2)
        tk.Label(cred_row, text="Service", anchor="w").pack(side="left")
        tk.Entry(cred_row, textvariable=self.service_var, width=14).pack(
            side="left", padx=(4, 16),
        )
        tk.Label(cred_row, text=i18n("用户 ID", "User ID"), anchor="w").pack(side="left")
        tk.Entry(cred_row, textvariable=self.userid_var, width=14).pack(
            side="left", padx=4,
        )

        # 基本设置（无标题）
        basic = tk.Frame(left)
        basic.pack(fill="x", pady=2)
        tk.Label(basic, text=i18n("下载目录", "Folder"), width=24, anchor="w").grid(
            row=0, column=0, sticky="w", padx=4, pady=2,
        )
        folder_cell = tk.Frame(basic)
        folder_cell.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        tk.Entry(folder_cell, textvariable=self.folder_var, width=36).pack(side="left")
        tk.Button(
            folder_cell,
            text=i18n("浏览...", "Browse..."),
            command=self._browse_folder,
        ).pack(side="left", padx=4)
        _labeled_entry(basic, i18n("起始帖子序号", "Post begins"), self.post_begins_var,
                       width=8, row=1, label_width=24)
        _labeled_entry(basic, i18n("帖子数量(0=全部)", "Post counts (0=all)"),
                       self.post_counts_var, width=8, row=2, label_width=24)
        _labeled_entry(basic, i18n("起始日期 YYYY-MM-DD", "Date from YYYY-MM-DD"),
                       self.date_from_var, width=12, row=3, label_width=24)
        _labeled_entry(basic, i18n("截止日期 YYYY-MM-DD", "Date to YYYY-MM-DD"),
                       self.date_to_var, width=12, row=4, label_width=24)

        numbering_row = tk.Frame(basic)
        numbering_row.grid(row=5, column=0, columnspan=2, sticky="w", padx=4, pady=2)
        tk.Label(numbering_row, text=i18n("附件编号模式", "Numbering mode"),
                 width=24, anchor="w").pack(side="left")
        self.numbering_display = [
            zh if kd.LANGUAGE == "zh" else en for _, zh, en in NUMBERING_MODES
        ]
        self.numbering_combo = ttk.Combobox(
            numbering_row,
            values=self.numbering_display,
            state="readonly",
            width=22,
        )
        self.numbering_combo.pack(side="left")
        self._sync_numbering_combo()
        self.numbering_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_numbering_change())
        # 警告标签常驻（无警告时显示空格），避免显示/隐藏导致其他输入框位置偏移
        self.numbering_warning_var = tk.StringVar(value=" ")
        self.numbering_warning = tk.Label(
            numbering_row,
            textvariable=self.numbering_warning_var,
            fg="red",
        )
        self.numbering_warning.pack(side="left", padx=8)
        self._on_numbering_change()

        # 内容过滤（无标题）
        filters = tk.Frame(left)
        filters.pack(fill="x", pady=2)
        _labeled_entry(filters, i18n("扩展名黑名单 (逗号分隔)", "Extension blacklist (csv)"),
                       self.ext_blacklist_var, row=0, label_width=24)
        _labeled_entry(filters, i18n("扩展名白名单 (逗号分隔)", "Extension whitelist (csv)"),
                       self.ext_whitelist_var, row=1, label_width=24)
        _labeled_entry(filters, i18n("文件名黑名单 (逗号分隔)", "Filename blacklist (csv)"),
                       self.name_blacklist_var, row=2, label_width=24)
        _labeled_entry(filters, i18n("文件名白名单 (逗号分隔)", "Filename whitelist (csv)"),
                       self.name_whitelist_var, row=3, label_width=24)
        tk.Checkbutton(
            filters,
            text=i18n("文件名使用正则", "Filename regex"),
            variable=self.name_regex_var,
        ).grid(row=2, column=2, sticky="w", padx=8)
        _labeled_entry(filters, i18n("标题黑名单 (逗号分隔)", "Title blacklist (csv)"),
                       self.title_blacklist_var, row=4, label_width=24)
        _labeled_entry(filters, i18n("标题白名单 (逗号分隔)", "Title whitelist (csv)"),
                       self.title_whitelist_var, row=5, label_width=24)
        tk.Checkbutton(
            filters,
            text=i18n("标题使用正则", "Title regex"),
            variable=self.title_regex_var,
        ).grid(row=4, column=2, sticky="w", padx=8)

        # 设置子窗口按钮（同一行）
        settings_row = tk.Frame(left)
        settings_row.pack(fill="x", pady=4)
        tk.Button(
            settings_row,
            text=i18n("高级设置...", "Advanced settings..."),
            command=lambda: self._open_settings_window(
                "advanced",
                i18n("高级设置", "Advanced settings"),
                self._build_advanced_fields,
            ),
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            settings_row,
            text=i18n("Aria2 设置...", "Aria2 settings..."),
            command=lambda: self._open_settings_window(
                "aria2",
                i18n("Aria2 设置", "Aria2 settings"),
                self._build_aria2_fields,
            ),
        ).pack(side="left")

        # 停止按钮 + 开始按钮（同一行，停止在左；先 pack 开始使其靠最右）
        self.start_button = tk.Button(
            settings_row,
            text=i18n("开始下载", "Start download"),
            command=self._on_start,
            width=16,
        )
        self.start_button.pack(side="right", pady=6)
        self.stop_button = tk.Button(
            settings_row,
            text=i18n("停止下载", "Stop download"),
            command=self._on_stop,
            width=12,
            state="disabled",
        )
        self.stop_button.pack(side="right", pady=6, padx=(0, 8))

        # 右栏：下载任务进度（不可折叠）
        progress_frame = tk.LabelFrame(
            right,
            text=i18n("下载任务", "Download tasks"),
        )
        progress_frame.pack(fill="both", expand=True)
        columns = ("name", "size", "progress", "speed", "status")
        headers = {
            "name": i18n("文件名", "File"),
            "size": i18n("大小", "Size"),
            "progress": i18n("进度", "Progress"),
            "speed": i18n("速度", "Speed"),
            "status": i18n("状态", "Status"),
        }
        self.task_tree = ttk.Treeview(
            progress_frame, columns=columns, show="headings", height=8,
        )
        for col in columns:
            self.task_tree.heading(col, text=headers[col])
            self.task_tree.column(col, width=80 if col != "name" else 240)
        self.task_tree.pack(fill="both", expand=True, side="left")
        tree_scroll = ttk.Scrollbar(
            progress_frame, orient="vertical", command=self.task_tree.yview,
        )
        tree_scroll.pack(side="right", fill="y")
        self.task_tree.configure(yscrollcommand=tree_scroll.set)

        self.global_stat_var = tk.StringVar(value="")
        tk.Label(
            progress_frame, textvariable=self.global_stat_var, anchor="w",
        ).pack(fill="x", padx=4)

        # 窗口底部：日志（默认展开，与窗口等宽）
        self.log_frame = CollapsibleFrame(
            self.root,
            i18n("日志", "Log"),
            collapsed=False,
            content_fill="x",
        )
        self.log_frame.pack(fill="x", padx=6, pady=(0, 6))
        self.log_text = scrolledtext.ScrolledText(
            self.log_frame.content, height=11, state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

    # ---------- 设置子窗口 ----------
    def _open_settings_window(self, key: str, title: str, builder):
        existing = self.settings_windows.get(key)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        window = tk.Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        frame = tk.Frame(window)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        builder(frame)
        self.settings_windows[key] = window
        window.protocol(
            "WM_DELETE_WINDOW",
            lambda k=key, w=window: self._close_settings_window(k, w),
        )

    def _close_settings_window(self, key: str, window: tk.Toplevel):
        self.settings_windows.pop(key, None)
        window.destroy()

    def _build_advanced_fields(self, adv):
        _labeled_entry(adv, i18n("基础 URL", "Base URL"), self.base_url_var,
                       width=40, row=0, label_width=24)
        _labeled_entry(adv, i18n("文件服务器 URL", "File server URL"), self.file_server_var,
                       width=40, row=1, label_width=24)
        tk.Label(adv, text=i18n("代理 URL", "Proxy URL"), width=24, anchor="w").grid(
            row=2, column=0, sticky="w", padx=4, pady=2,
        )
        proxy_cell = tk.Frame(adv)
        proxy_cell.grid(row=2, column=1, sticky="w", padx=4, pady=2)
        tk.Checkbutton(
            proxy_cell,
            text=i18n("启用代理", "Enable proxy"),
            variable=self.proxy_enabled_var,
            command=self._on_proxy_toggle,
        ).pack(side="left", padx=(0, 8))
        self.proxy_entry = tk.Entry(
            proxy_cell, textvariable=self.proxy_url_var, width=34,
        )
        self.proxy_entry.pack(side="left")
        self._on_proxy_toggle()
        _labeled_entry(adv, i18n("页面最大重试次数", "Max retries"), self.max_retries_var,
                       width=8, row=3, label_width=24)
        _labeled_entry(adv, i18n("重试基准延迟(秒)", "Base backoff factor (s)"),
                       self.backoff_var, width=8, row=4, label_width=24)

        misc_row = tk.Frame(adv)
        misc_row.grid(row=5, column=0, columnspan=2, sticky="w", padx=4, pady=2)
        tk.Checkbutton(
            misc_row,
            text=i18n("Kemono 模式", "Kemono mode"),
            variable=self.kemono_mode_var,
        ).pack(side="left", padx=(0, 12))
        tk.Checkbutton(
            misc_row,
            text=i18n("流水线模式", "Pipeline mode"),
            variable=self.pipeline_var,
        ).pack(side="left", padx=(0, 12))
        tk.Label(misc_row, text=i18n("已存在文件", "Existing files"), anchor="w").pack(
            side="left",
        )
        self.existing_combo = ttk.Combobox(
            misc_row,
            values=EXISTING_FILE_MODES,
            state="readonly",
            width=12,
        )
        self.existing_combo.pack(side="left", padx=4)
        self.existing_combo.set(self.existing_file_var.get())
        self.existing_combo.bind(
            "<<ComboboxSelected>>",
            lambda *_: self.existing_file_var.set(self.existing_combo.get()),
        )

    def _build_aria2_fields(self, ar):
        _labeled_entry(
            ar,
            i18n("Aria2 RPC 地址 (留空=本地自启)", "Aria2 RPC URL (empty=local)"),
            self.aria2_rpc_url_var, width=40, row=0, label_width=24,
        )
        aria2_labels = {
            "max-concurrent-downloads": i18n("最大同时下载任务数", "Max concurrent downloads"),
            "split": i18n("单任务分段数", "Splits per task"),
            "max-connection-per-server": i18n("单服务器最大连接数", "Max connections per server"),
            "max-overall-download-limit": i18n("整体下载限速 (如 10M)", "Overall download limit"),
            "max-download-limit": i18n("单任务下载限速 (如 2M)", "Per-task download limit"),
        }
        for index, (key, _) in enumerate(ARIA2_OPTIONS, start=1):
            _labeled_entry(ar, aria2_labels[key], self.aria2_option_vars[key],
                           width=12, row=index, label_width=24)
        self.aria2_remote_hint = tk.Label(
            ar,
            text=i18n("使用远程 RPC 时以上选项不生效", "Options above only apply to local aria2"),
            fg="gray",
        )
        self.aria2_remote_hint.grid(row=len(ARIA2_OPTIONS) + 1, column=0,
                                    columnspan=2, sticky="w", padx=4, pady=2)

    # ---------- 编号模式 ----------
    def _on_proxy_toggle(self):
        self.proxy_entry.config(
            state="normal" if self.proxy_enabled_var.get() else "disabled",
        )

    def _sync_numbering_combo(self):
        current = self.number_attachments_var.get()
        for index, (internal, _, _) in enumerate(NUMBERING_MODES):
            if internal == current:
                self.numbering_combo.current(index)
                return
        self.numbering_combo.current(2)  # 默认 图片/image

    def _on_numbering_change(self):
        index = self.numbering_combo.current()
        if 0 <= index < len(NUMBERING_MODES):
            internal = NUMBERING_MODES[index][0]
            self.number_attachments_var.set(internal)
        else:
            internal = self.number_attachments_var.get()
        if internal in RENAME_MODES:
            self.numbering_warning_var.set(
                i18n("⚠ 重命名模式不下载任何文件", "⚠ Rename modes do not download files")
            )
        else:
            self.numbering_warning_var.set(" ")

    # ---------- 目标 & 浏览 ----------
    def _browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_var.set(folder)

    def _auto_parse_url(self):
        """URL 字段非空时尝试识别并回填 service/userid；失败时标红，不打断输入。"""
        url = self.url_var.get().strip()
        if not url:
            return
        try:
            service, userid = parse_creator_url(url, self.base_url_var.get())
        except ValueError:
            return
        self.service_var.set(service)
        self.userid_var.set(userid)

    # ---------- 日志 ----------
    def _attach_log_handler(self):
        handler = QueueHandler(self.log_queue)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        kd.logger.addHandler(handler)

    def _poll_log_queue(self):
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            while True:
                message = self.log_queue.get_nowait()
                if message == "__WORKER_DONE__":
                    self._on_worker_done()
                    continue
                self.log_text.config(state="normal")
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log_queue)

    # ---------- 进度轮询 ----------
    def _current_rpc_url(self) -> str:
        return self.aria2_rpc_url_var.get().strip() or kd.LOCAL_ARIA2_RPC_URL

    def _poll_aria2_status(self):
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        if self.run_state != "idle":
            self._refresh_task_tree()
            self.root.after(1000, self._poll_aria2_status)

    def _refresh_task_tree(self):
        rpc_url = self._current_rpc_url()
        try:
            active = kd.aria2_rpc_call(
                "aria2.tellActive", [], aria2_rpc_url=rpc_url, timeout=2,
            ).get("result", [])
            waiting = kd.aria2_rpc_call(
                "aria2.tellWaiting", [0, 200], aria2_rpc_url=rpc_url, timeout=2,
            ).get("result", [])
            stat = kd.aria2_rpc_call(
                "aria2.getGlobalStat", [], aria2_rpc_url=rpc_url, timeout=2,
            ).get("result", {})
        except Exception:
            return

        status_text = {
            "active": i18n("下载中", "Downloading"),
            "waiting": i18n("排队中", "Queued"),
            "paused": i18n("已暂停", "Paused"),
        }

        seen = set()
        for entry in list(active) + list(waiting):
            gid = entry.get("gid")
            if not gid:
                continue
            seen.add(gid)
            files = entry.get("files") or []
            name = os.path.basename(files[0].get("path", "")) if files else gid
            total = int(entry.get("totalLength") or 0)
            done = int(entry.get("completedLength") or 0)
            speed = int(entry.get("downloadSpeed") or 0)
            progress = f"{done * 100 / total:.1f}%" if total > 0 else "-"
            values = (
                name,
                _format_size(total),
                progress,
                _format_size(speed) + "/s" if entry.get("status") == "active" else "-",
                status_text.get(entry.get("status"), entry.get("status", "")),
            )
            if gid in self.tree_items:
                self.task_tree.item(self.tree_items[gid], values=values)
            else:
                self.tree_items[gid] = self.task_tree.insert("", "end", values=values)

        for gid in list(self.tree_items):
            if gid not in seen:
                self.task_tree.delete(self.tree_items.pop(gid))

        num_active = len(active)
        num_waiting = len(waiting)
        overall_speed = int(stat.get("downloadSpeed") or 0)
        self.global_stat_var.set(i18n(
            f"全局速度: {_format_size(overall_speed)}/s    "
            f"下载中: {num_active}    排队: {num_waiting}",
            f"Global speed: {_format_size(overall_speed)}/s    "
            f"Active: {num_active}    Queued: {num_waiting}",
        ))

    # ---------- 启动/暂停/继续/停止 ----------
    def _active_run_config(self):
        """当前 worker 正在运行的 main 内部 Config（用于控制暂停/停止）。"""
        return kd.get_active_config()

    def _pause_run(self):
        cfg = self._active_run_config()
        if cfg is not None:
            cfg.pause_event.clear()
            try:
                kd.aria2_rpc_call(
                    "aria2.pauseAll", [], aria2_rpc_url=self._current_rpc_url(), timeout=5,
                )
            except Exception as e:
                kd.logger.warning(i18n(
                    f"暂停 aria2 任务失败: {e}",
                    f"Failed to pause aria2 tasks: {e}",
                ))

    def _resume_run(self):
        cfg = self._active_run_config()
        if cfg is not None:
            cfg.pause_event.set()
            try:
                kd.aria2_rpc_call(
                    "aria2.unpauseAll", [], aria2_rpc_url=self._current_rpc_url(), timeout=5,
                )
            except Exception as e:
                kd.logger.warning(i18n(
                    f"恢复 aria2 任务失败: {e}",
                    f"Failed to resume aria2 tasks: {e}",
                ))

    def _on_stop(self):
        if self.run_state == "idle":
            return
        kd.logger.info(i18n(
            "收到停止请求，正在终止抓取与下载任务（已下载文件保留）...",
            "Stop requested; aborting fetching and downloads (downloaded files are kept)...",
        ))
        self.stop_button.config(state="disabled")
        self.start_button.config(state="disabled")
        cfg = self._active_run_config()
        if cfg is not None:
            cfg.stop_event.set()
            cfg.pause_event.set()  # 解除暂停挂起
            try:
                cfg.session.close()  # 中断在途 HTTP 请求
            except Exception:
                pass
        self._on_state_changed("idle")
        # worker 将在检查点退出，_on_worker_done 完成复位

    def _on_start(self):
        if self.run_state == "running":
            # 运行中 -> 暂停
            self._pause_run()
            self._on_state_changed("paused")
            return
        if self.run_state == "paused":
            # 已暂停 -> 继续
            self._resume_run()
            self._on_state_changed("running")
            return

        # idle -> 全新启动
        self._on_start_new()

    # ---------- 启动下载 ----------
    def _collect_config(self) -> dict:
        return {
            "folder": self.folder_var.get().strip(),
            "number_attachments": self.number_attachments_var.get(),
            "base_url": self.base_url_var.get().strip(),
            "file_server": self.file_server_var.get().strip(),
            "proxy_url": self.proxy_url_var.get().strip(),
            "proxy_enabled": self.proxy_enabled_var.get(),
            "max_retries": self.max_retries_var.get().strip(),
            "base_backoff_factor": self.backoff_var.get().strip(),
            "kemono_mode": self.kemono_mode_var.get(),
            "existing_file": self.existing_file_var.get(),
            "pipeline": self.pipeline_var.get(),
            "aria2_rpc_url": self.aria2_rpc_url_var.get().strip(),
        }

    def _on_start_new(self):
        # 目标：URL 优先，其次手动输入
        url = self.url_var.get().strip()
        if url:
            try:
                service, userid = parse_creator_url(url, self.base_url_var.get())
            except ValueError as e:
                messagebox.showerror(i18n("URL 无效", "Invalid URL"), str(e))
                return
            self.service_var.set(service)
            self.userid_var.set(userid)
        else:
            service = self.service_var.get().strip()
            userid = self.userid_var.get().strip()
            if not service or not userid:
                messagebox.showerror(
                    i18n("参数缺失", "Missing parameters"),
                    i18n(
                        "请填写创作者 URL，或手动填写服务名和用户 ID。",
                        "Please provide the creator URL, or fill in service and user ID manually.",
                    ),
                )
                return

        # 其他校验
        try:
            validate_inputs(
                self.date_from_var.get(),
                self.date_to_var.get(),
                kd.parse_list_arg(self.name_blacklist_var.get())
                + kd.parse_list_arg(self.name_whitelist_var.get()),
                self.name_regex_var.get(),
                kd.parse_list_arg(self.title_blacklist_var.get())
                + kd.parse_list_arg(self.title_whitelist_var.get()),
                self.title_regex_var.get(),
            )
            argv = build_argv(
                userid=userid,
                service=service,
                folder=self.folder_var.get(),
                post_begins=self.post_begins_var.get(),
                post_counts=self.post_counts_var.get(),
                date_from=self.date_from_var.get(),
                date_to=self.date_to_var.get(),
                ext_blacklist=self.ext_blacklist_var.get(),
                ext_whitelist=self.ext_whitelist_var.get(),
                name_blacklist=self.name_blacklist_var.get(),
                name_whitelist=self.name_whitelist_var.get(),
                name_regex=self.name_regex_var.get(),
                title_blacklist=self.title_blacklist_var.get(),
                title_whitelist=self.title_whitelist_var.get(),
                title_regex=self.title_regex_var.get(),
                number_attachments=self.number_attachments_var.get(),
                base_url=self.base_url_var.get(),
                file_server=self.file_server_var.get(),
                proxy_url=(
                    self.proxy_url_var.get() if self.proxy_enabled_var.get() else ""
                ),
                max_retries=self.max_retries_var.get(),
                base_backoff_factor=self.backoff_var.get(),
                kemono_mode=self.kemono_mode_var.get(),
                existing_file=self.existing_file_var.get(),
                pipeline=self.pipeline_var.get(),
                aria2_rpc_url=self.aria2_rpc_url_var.get(),
            )
        except (ValueError, TypeError) as e:
            messagebox.showerror(i18n("参数无效", "Invalid parameters"), str(e))
            return

        if self.number_attachments_var.get() in RENAME_MODES:
            kd.logger.warning(i18n(
                "当前为重命名模式：不会下载任何文件，只会为已下载的附件编号。",
                "Rename mode is active: no files will be downloaded; only existing files will be numbered.",
            ))

        # 保存配置 & 写 aria2.conf
        save_ui_config(self._collect_config())
        try:
            write_aria2_conf_options({
                key: var.get().strip() for key, var in self.aria2_option_vars.items()
            })
        except OSError as e:
            messagebox.showerror(
                i18n("Aria2 配置错误", "Aria2 config error"),
                i18n(f"写入 aria2.conf 失败: {e}", f"Failed to write aria2.conf: {e}"),
            )
            return

        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        for item in list(self.tree_items.values()):
            self.task_tree.delete(item)
        self.tree_items.clear()

        self.run_state = "running"
        self.start_button.config(text=i18n("暂停下载", "Pause download"))
        self.stop_button.config(state="normal")
        self.worker = threading.Thread(target=self._run_worker, args=(argv,), daemon=True)
        self.worker.start()
        self.root.after(1000, self._poll_aria2_status)

    def _on_state_changed(self, state: str):
        self.run_state = state
        if state == "idle":
            self.start_button.config(
                text=i18n("开始下载", "Start download"), state="normal",
            )
            self.stop_button.config(state="disabled")
        elif state == "running":
            self.start_button.config(
                text=i18n("暂停下载", "Pause download"), state="normal",
            )
            self.stop_button.config(state="normal")
        elif state == "paused":
            self.start_button.config(
                text=i18n("开始下载", "Start download"), state="normal",
            )
            self.stop_button.config(state="normal")

    def _run_worker(self, argv: list):
        try:
            kd.main(argv)
        except SystemExit as e:
            kd.logger.warning(i18n(
                f"下载流程结束（退出码: {e.code}）。",
                f"Download process ended (exit code: {e.code}).",
            ))
        except Exception:
            kd.logger.error(i18n(
                "下载流程发生未处理异常:\n" + traceback.format_exc(),
                "Unhandled exception in download process:\n" + traceback.format_exc(),
            ))
        finally:
            self.log_queue.put("__WORKER_DONE__")

    def _on_worker_done(self):
        self._on_state_changed("idle")
        self._refresh_task_tree()

    def _on_close(self):
        if self.run_state != "idle":
            confirmed = messagebox.askokcancel(
                i18n("确认退出", "Confirm exit"),
                i18n(
                    "下载仍在进行中，退出将中断抓取（aria2 已下载的任务会保留）。确定退出？",
                    "A download is still running; exiting will interrupt fetching (completed aria2 tasks are kept). Exit anyway?",
                ),
            )
            if not confirmed:
                return
        save_ui_config(self._collect_config())
        self.root.destroy()


def main():
    # 保证 aria2c / aria2.conf / ui_config.json 等相对路径始终解析到程序目录
    os.chdir(BASE_DIR)
    root = tk.Tk()
    DownloaderUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
