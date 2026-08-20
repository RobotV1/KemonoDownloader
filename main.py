import argparse
import atexit
import html
import json
import locale
import os
import platform
import signal
import sys
import time
from typing import Callable, Dict, Iterable, Optional, List
from dataclasses import dataclass, field
import logging
import threading
import unicodedata
import re
import subprocess
from datetime import date, datetime
from urllib.parse import urlencode, urlparse

import requests

# ---------------------------
# Logger 配置（基础 - 控制台）
# ---------------------------
logger = logging.getLogger("Kemono_downloader")
logger.setLevel(logging.DEBUG)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s",
    "%Y-%m-%d %H:%M:%S",
)
_console_handler.setFormatter(_console_formatter)

if not logger.handlers:
    logger.addHandler(_console_handler)


# ---------------------------
# I18N
# ---------------------------
def detect_language() -> str:
    """Return zh for Chinese environments, otherwise en."""
    override = os.environ.get("KEMONO_DOWNLOADER_LANG", "").strip().lower()
    if override:
        if override.startswith("zh") or override in ("cn", "chinese", "chs", "cht"):
            return "zh"
        return "en"

    candidates = []
    for env_name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)

    for getter in (locale.getlocale, getattr(locale, "getdefaultlocale", None)):
        if getter is None:
            continue
        try:
            locale_value = getter()
        except Exception:
            continue

        if isinstance(locale_value, tuple):
            candidates.extend(str(part) for part in locale_value if part)
        elif locale_value:
            candidates.append(str(locale_value))

    try:
        candidates.append(locale.getencoding())
    except AttributeError:
        pass

    normalized_candidates = [
        candidate.strip().replace("-", "_").lower()
        for candidate in candidates
        if candidate
    ]
    return "zh" if any(
        candidate.startswith("zh")
        or "chinese" in candidate
        or "中文" in candidate
        or "汉语" in candidate
        or "漢語" in candidate
        or candidate in ("chs", "cht")
        for candidate in normalized_candidates
    ) else "en"


LANGUAGE = detect_language()


def i18n(zh: str, en: str) -> str:
    return zh if LANGUAGE == "zh" else en


ARGPARSE_ZH_TRANSLATIONS = {
    "usage: ": "用法: ",
    "positional arguments": "位置参数",
    "options": "选项",
    "optional arguments": "可选参数",
    "show this help message and exit": "显示帮助信息并退出",
    "the following arguments are required: %s": "缺少必需参数: %s",
    "unrecognized arguments: %s": "无法识别的参数: %s",
    "argument %(argument_name)s: %(message)s": "参数 %(argument_name)s: %(message)s",
    "invalid %(type)s value: %(value)r": "无效的 %(type)s 值: %(value)r",
    "expected one argument": "需要一个参数",
    "expected at most one argument": "最多需要一个参数",
    "expected at least one argument": "至少需要一个参数",
    "expected %s argument": "需要 %s 个参数",
    "expected %s arguments": "需要 %s 个参数",
}


def argparse_gettext(message: str) -> str:
    if LANGUAGE != "zh":
        return message
    return ARGPARSE_ZH_TRANSLATIONS.get(message, message)


def configure_argparse_language() -> None:
    argparse._ = argparse_gettext


# ---------------------------
# 配置类 & 常量
# ---------------------------
LOCAL_ARIA2_RPC_URL = "http://localhost:6888/jsonrpc"
ARIANG_OFFICIAL_DEMO_BASE_URL = "https://ariang.mayswind.net/latest"

NUMBER_ATTACHMENTS_OFF = "off"
NUMBER_ATTACHMENTS_ALL = "all"
NUMBER_ATTACHMENTS_IMAGES = "images"
NUMBER_ATTACHMENTS_RENAME_ALL = "rename"
NUMBER_ATTACHMENTS_RENAME_IMAGES = "rename_images"

EXISTING_FILE_SKIP = "skip"
EXISTING_FILE_REDOWNLOAD = "redownload"
EXISTING_FILE_VERIFY = "verify"
EXISTING_FILE_MODES = (
    EXISTING_FILE_SKIP,
    EXISTING_FILE_REDOWNLOAD,
    EXISTING_FILE_VERIFY,
)

IMAGE_ATTACHMENT_EXTENSIONS = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".ico",
    ".jfif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}


@dataclass
class Config:
    postCounts: int = 0
    baseUrl: str = ""
    fileServer: str = ""
    kemonoMode: bool = False
    proxies: Optional[Dict[str, str]] = None
    maxRetries: int = 5
    baseBackoffFactor: float = 1.0
    targetOS: str = "windows"
    folder: str = ""
    embedCount: int = 0
    skipPic: List[str] = field(
        default_factory=lambda: [
            "/5e/46/5e46bc830d84fbad826963d2e2223f15fba27a05bef94814efa84e3bb3fcb7ef.png"
        ]
    )
    headers: Dict[str, str] = field(
        default_factory=lambda: {
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-CH-UA": '"Microsoft Edge";v="146", "Chromium";v="146", "Not=A?Brand";v="24"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
            ),
        }
    )
    aria2_rpc_url: str = LOCAL_ARIA2_RPC_URL
    session: requests.Session = field(default_factory=requests.Session)
    emptyContentPosts: Dict[str, dict] = field(default_factory=dict)
    emptyContentRetryMilestones: List[int] = field(default_factory=lambda: [1, 3, 7, 13])
    emptyContentRetryMilestonesDone: set = field(default_factory=set)
    numberAttachmentsMode: str = NUMBER_ATTACHMENTS_OFF
    # ---- 过滤配置 ----
    extBlacklist: List[str] = field(default_factory=list)
    extWhitelist: List[str] = field(default_factory=list)
    titleBlacklistMatcher: Optional[Callable[[str], bool]] = None
    titleWhitelistMatcher: Optional[Callable[[str], bool]] = None
    nameBlacklistMatcher: Optional[Callable[[str], bool]] = None
    nameWhitelistMatcher: Optional[Callable[[str], bool]] = None
    dateFrom: Optional[date] = None
    dateTo: Optional[date] = None
    # ---- 已存在文件处理: skip / redownload / verify ----
    existingFileMode: str = EXISTING_FILE_VERIFY
    activeReferer: Optional[str] = None
    # ---- 流水线模式 ----
    pipelineEnabled: bool = True
    pendingTasks: List["DownloadTask"] = field(default_factory=list)
    failedAttachments: List[str] = field(default_factory=list)
    # ---- 运行控制（暂停/停止，由 UI 驱动；CLI 下恒为运行态）----
    pause_event: threading.Event = field(default_factory=threading.Event)
    stop_event: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self):
        self.pause_event.set()


SMALL_RETRY_TIMES = 2
SMALL_RETRY_INTERVAL = 5

BIG_RETRY_TIMES = 5
BIG_RETRY_BASE_INTERVAL = 20

MAX_TOTAL_RETRY = BIG_RETRY_TIMES * (SMALL_RETRY_TIMES + 1)

_local_aria2_process: Optional[subprocess.Popen] = None
_local_aria2_rpc_url: Optional[str] = None
_local_aria2_cleanup_started = False

# 当前运行中的 Config（供 UI 获取暂停/停止控制句柄）
_active_config: Optional[Config] = None


def get_active_config() -> Optional[Config]:
    return _active_config


def check_run_control(config: Config) -> bool:
    """
    运行控制检查点：
      暂停时挂起调用线程（暂停期间 worker 线程被阻塞，UI 不受影响）；
      停止请求后返回 False。
    """
    config.pause_event.wait()
    return not config.stop_event.is_set()


def abort_pending_tasks(config: Config) -> None:
    """
    停止时清理所有在途 aria2 任务（尽力而为），
    避免未完成任务残留在 aria2.session 中导致下次启动时失控自动续下。
    """
    for task in list(config.pendingTasks):
        gid = task.gid
        if not gid:
            continue
        try:
            aria2_rpc_call(
                "aria2.remove", [gid],
                aria2_rpc_url=config.aria2_rpc_url, aria2_token=None, timeout=5,
            )
        except Exception:
            pass
        try:
            aria2_rpc_call(
                "aria2.removeDownloadResult", [gid],
                aria2_rpc_url=config.aria2_rpc_url, aria2_token=None, timeout=5,
            )
        except Exception:
            pass
    config.pendingTasks.clear()
    logger.info(i18n(
        "已清理在途 aria2 下载任务。",
        "Cleaned up in-flight aria2 download tasks.",
    ))

ARIA2_CONF_PATH = "aria2.conf"

# aria2.conf 缺失时自动生成的默认配置
DEFAULT_ARIA2_CONF = """## 文件保存相关 ##

# 启用磁盘缓存, 0为禁用缓存, 需1.16以上版本, 默认:16M
disk-cache=64M

# 文件预分配方式, 可选：none, prealloc, trunc, falloc, 默认:prealloc
# 预分配对于机械硬盘可有效降低磁盘碎片、提升磁盘读写性能、延长磁盘寿命。
# 机械硬盘使用 ext4（具有扩展支持），btrfs，xfs 或 NTFS（仅 MinGW 编译版本）等文件系统建议设置为 falloc
# 若无法下载，提示 fallocate failed.cause：Operation not supported 则说明不支持，请设置为 none
# prealloc 分配速度慢, trunc 无实际作用，不推荐使用。
# 固态硬盘不需要预分配，只建议设置为 none ，否则可能会导致双倍文件大小的数据写入，从而影响寿命。
file-allocation=none

# 断点续传
continue=true

# 始终尝试断点续传，无法断点续传则终止下载，默认：true
always-resume=false

# 不支持断点续传的 URI 数值，当 always-resume=false 时生效。
# 达到这个数值从将头开始下载，值为 0 时所有 URI 不支持断点续传时才从头开始下载。
max-resume-failure-tries=0

## 下载连接相关 ##

# 文件未找到重试次数，默认:0 (禁用)
# 重试时同时会记录重试次数，所以也需要设置 max-tries 这个选项
max-file-not-found=10

# 最大尝试次数，0 表示无限，默认:5
max-tries=0

# 重试等待时间（秒）, 默认:0 (禁用)
retry-wait=10

# 连接超时时间（秒）。默认：60
connect-timeout=60

# 最大同时下载任务数, 运行时可修改, 默认:5
max-concurrent-downloads=5

# 同一服务器连接数, 添加时可指定, 最大:16
max-connection-per-server=16

# 最小文件分片大小, 添加时可指定, 取值范围1M -1024M, 默认:20M
# 假定size=10M, 文件为20MiB 则使用两个来源下载; 文件为15MiB 则使用一个来源下载
#min-split-size=10M

# 单个任务最大线程数, 添加时可指定, 默认:5
split=5

# 整体下载速度限制, 运行时可修改, 默认:0
#max-overall-download-limit=

# 单个任务下载速度限制, 默认:0
#max-download-limit=

# 整体上传速度限制, 运行时可修改, 默认:0
#max-overall-upload-limit=0

# 单个任务上传速度限制, 默认:0
#max-upload-limit=0

# GZip 支持，默认:false
http-accept-gzip=true

# URI 复用，默认: true
reuse-uri=false

# 禁用 netrc 支持，默认:false
no-netrc=true

# 允许覆盖，当相关控制文件(.aria2)不存在时从头开始重新下载。默认:false
allow-overwrite=true

# 使用 UTF-8 处理 Content-Disposition ，默认:false
content-disposition-default-utf8=true

# 禁用IPv6, 默认:false
#disable-ipv6=false

# 代理服务器
#all-proxy=http://127.0.0.1:7897

async-dns=false

## 进度保存相关 ##

# 从会话文件中读取下载任务
input-file=aria2.session
# 在Aria2退出时保存`错误/未完成`的下载任务到会话文件
save-session=aria2.session
# 定时保存会话, 0为退出时才保存（此处需要设置，否则失去自动保存）, 需1.16.1以上版本, 默认:0 

# 任务状态改变后保存会话的间隔时间（秒）, 0 为仅在进程正常退出时保存, 默认:0
# 为了及时保存任务状态、防止任务丢失，此项值只建议设置为 1
save-session-interval=1

# 自动保存任务进度到控制文件(*.aria2)的间隔时间（秒），0 为仅在进程正常退出时保存，默认：60
# 此项值也会间接影响从内存中把缓存的数据写入磁盘的频率
# 想降低磁盘 IOPS (每秒读写次数)则提高间隔时间
# 想在意外非正常退出时尽量保存更多的下载进度则降低间隔时间
# 非正常退出：进程崩溃、系统崩溃、SIGKILL 信号、设备断电等
auto-save-interval=20

# 强制保存，即使任务已完成也保存信息到会话文件, 默认:false
# 开启后会在任务完成后保留 .aria2 文件，文件被移除且任务存在的情况下重启后会重新下载。
# 关闭后已完成的任务列表会在重启后清空。
force-save=false

## RPC相关设置 ##

# 启用RPC, 默认:false
enable-rpc=true
# 允许所有来源, 默认:false
rpc-allow-origin-all=true
# 允许非外部访问, 默认:false
rpc-listen-all=true
# 事件轮询方式, 取值:[epoll, kqueue, port, poll, select], 不同系统默认值不同
#event-poll=select
# RPC监听端口, 端口被占用时可以修改, 默认:6800
rpc-listen-port=6888

user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0

# 安静模式
# 禁止在控制台输出日志
quiet=true
"""


def ensure_aria2_conf(conf_path: str = ARIA2_CONF_PATH) -> None:
    """aria2.conf / aria2.session 缺失时按默认配置自动生成。"""
    if not os.path.exists(conf_path):
        try:
            with open(conf_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_ARIA2_CONF)
            logger.info(i18n(
                f"未找到 {conf_path}，已按默认配置生成。",
                f"{conf_path} not found; generated with default settings.",
            ))
        except OSError as e:
            logger.warning(i18n(
                f"生成默认 {conf_path} 失败: {e}",
                f"Failed to generate default {conf_path}: {e}",
            ))

    session_path = os.path.join(os.path.dirname(os.path.abspath(conf_path)) or ".", "aria2.session")
    if not os.path.exists(session_path):
        try:
            with open(session_path, "w", encoding="utf-8"):
                pass
            logger.info(i18n(
                "未找到 aria2.session，已自动生成空文件。",
                "aria2.session not found; generated an empty file.",
            ))
        except OSError as e:
            logger.warning(i18n(
                f"生成默认 aria2.session 失败: {e}",
                f"Failed to generate default aria2.session: {e}",
            ))


def build_ariang_rpc_setup_url(aria2_rpc_url: str) -> str:
    parsed_url = urlparse(aria2_rpc_url)
    protocol = parsed_url.scheme or "http"
    host = parsed_url.hostname or "localhost"
    port = parsed_url.port or (443 if protocol in ("https", "wss") else 80)
    rpc_interface = parsed_url.path.strip("/") or "jsonrpc"
    query = urlencode(
        {
            "protocol": protocol,
            "host": host,
            "port": str(port),
            "interface": rpc_interface,
        }
    )
    return f"{ARIANG_OFFICIAL_DEMO_BASE_URL}/#!/settings/rpc/set?{query}"


def get_site_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/") + "/"
    api_suffix = "api/v1/"
    if normalized.endswith(api_suffix):
        return normalized[:-len(api_suffix)]
    return normalized


def build_kemono_referer(
        config: Config,
        service: str,
        userID: str,
        postID: str | None = None,
) -> str:
    user_page = f"{get_site_base_url(config.baseUrl)}{service}/user/{userID}"
    if postID:
        return f"{user_page}/post/{postID}"
    return user_page


def build_request_headers(config: Config, referer: str | None = None) -> Dict[str, str]:
    headers = dict(config.headers)
    if referer:
        headers["Referer"] = referer
    return headers


def build_browser_page_headers(config: Config, referer: str | None = None) -> Dict[str, str]:
    headers = build_request_headers(config, referer)
    headers.update(
        {
            "Accept": "application/json,text/plain,*/*",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin" if referer else "none",
        }
    )
    return headers


def visit_post_page_before_api(postID: str, userID: str, service: str, config: Config):
    post_page_url = build_kemono_referer(config, service, userID, postID)
    user_page_url = build_kemono_referer(config, service, userID)
    headers = build_browser_page_headers(config, referer=user_page_url)

    try:
        logger.info(i18n(
            f"预访问帖子网页路径: {post_page_url}",
            f"Pre-visiting post page URL: {post_page_url}",
        ))
        response = config.session.get(
            post_page_url,
            proxies=config.proxies,
            headers=headers,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning(i18n(
            f"预访问帖子网页路径失败，继续请求 API: {e}",
            f"Post page pre-visit failed; continuing with API request: {e}",
        ))
    except Exception as e:
        logger.warning(i18n(
            f"预访问帖子网页路径发生未知错误，继续请求 API: {e}",
            f"Unexpected post page pre-visit error; continuing with API request: {e}",
        ))


def fetch_post_detail_data(
        postID: str,
        userID: str,
        service: str,
        config: Config,
):
    url = config.baseUrl + service + "/user/" + userID + "/post/" + postID
    headers = build_request_headers(
        config,
        referer=build_kemono_referer(config, service, userID, postID),
    )
    data = None

    visit_post_page_before_api(postID, userID, service, config)

    for attempt in range(config.maxRetries):
        try:
            response = config.session.get(
                url,
                proxies=config.proxies,
                headers=headers,
            )
            response.raise_for_status()

            try:
                data = response.json()
                if data:
                    return data
                logger.warning(i18n(
                    f"帖子详情 JSON 为空 (尝试 {attempt + 1}/{config.maxRetries})。",
                    f"Post detail JSON is empty (attempt {attempt + 1}/{config.maxRetries}).",
                ))
            except json.JSONDecodeError as e:
                logger.warning(
                    i18n(
                        f"错误：无效的 JSON 字符串，可能是网络错误 "
                        f"(尝试 {attempt + 1}/{config.maxRetries}): {e}",
                        f"Error: invalid JSON, possibly due to a network issue "
                        f"(attempt {attempt + 1}/{config.maxRetries}): {e}",
                    )
                )
            except AttributeError as e:
                logger.warning(
                    i18n(
                        f"错误：JSON 对象结构不符合预期，可能是网络错误 "
                        f"(尝试 {attempt + 1}/{config.maxRetries}): {e}",
                        f"Error: unexpected JSON object structure, possibly due to a network issue "
                        f"(attempt {attempt + 1}/{config.maxRetries}): {e}",
                    )
                )

        except requests.exceptions.Timeout:
            logger.warning(i18n(
                f"获取帖子超时 (尝试 {attempt + 1}/{config.maxRetries}): {url}",
                f"Timed out while fetching post (attempt {attempt + 1}/{config.maxRetries}): {url}",
            ))
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code is not None and 500 <= status_code < 600:
                logger.warning(
                    i18n(
                        f"获取帖子遭遇服务器错误 (HTTP {status_code}) "
                        f"(尝试 {attempt + 1}/{config.maxRetries}): {e}",
                        f"Server error while fetching post (HTTP {status_code}) "
                        f"(attempt {attempt + 1}/{config.maxRetries}): {e}",
                    )
                )
            elif status_code == 429:
                logger.warning(
                    i18n(
                        f"获取帖子遭遇服务器错误 (HTTP 429) "
                        f"(尝试 {attempt + 1}/{config.maxRetries}): {e}",
                        f"Rate limited while fetching post (HTTP 429) "
                        f"(attempt {attempt + 1}/{config.maxRetries}): {e}",
                    )
                )
            else:
                logger.error(
                    i18n(
                        f"获取帖子失败 (HTTP {status_code if status_code is not None else 'Unknown'})，不重试: {e}",
                        f"Failed to fetch post (HTTP {status_code if status_code is not None else 'Unknown'}); not retrying: {e}",
                    )
                )
                return None
        except requests.exceptions.RequestException as e:
            logger.warning(
                i18n(
                    f"获取帖子时发生网络错误 (尝试 {attempt + 1}/{config.maxRetries}): {e}",
                    f"Network error while fetching post (attempt {attempt + 1}/{config.maxRetries}): {e}",
                )
            )
        except Exception as e:
            logger.error(
                i18n(
                    f"获取帖子时发生未知错误 (尝试 {attempt + 1}/{config.maxRetries}): {e}",
                    f"Unexpected error while fetching post (attempt {attempt + 1}/{config.maxRetries}): {e}",
                )
            )

        if attempt < config.maxRetries - 1:
            waitTime = config.baseBackoffFactor * (2 ** attempt)
            logger.info(i18n(
                f"将在 {waitTime:.2f} 秒后重试...",
                f"Retrying in {waitTime:.2f} seconds...",
            ))
            time.sleep(waitTime)
        else:
            logger.error(i18n(
                f"所有 {config.maxRetries} 次尝试获取帖子均失败。",
                f"All {config.maxRetries} attempts to fetch the post failed.",
            ))

    return None


def get_attachment_server(attachment: dict, config: Config) -> str:
    if config.kemonoMode:
        return attachment.get("server")
    return config.fileServer


# ---------------------------
# Aria2 RPC 相关
# ---------------------------
def aria2_rpc_call(
        method: str,
        params: list,
        aria2_rpc_url: str = "http://localhost:6888/jsonrpc",
        aria2_token: str | None = None,
        timeout: float | None = None,
):
    """通用 aria2 RPC 调用封装。"""
    rpc_params = []
    if aria2_token:
        rpc_params.append(f"token:{aria2_token}")
    rpc_params.extend(params)

    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": method,
        "params": rpc_params,
    }
    resp = requests.post(aria2_rpc_url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ---------------------------
# 文件 / 下载相关
# ---------------------------
def cleanup_files(targetFolder: str, attachmentName: str):
    """删除目标文件及其 .aria2 临时文件。"""
    file_path = os.path.join(targetFolder, attachmentName)
    aria2_file = file_path + ".aria2"

    for f in (file_path, aria2_file):
        try:
            if os.path.exists(f):
                os.remove(f)
                logger.info(i18n(f"已删除文件: {f}", f"Deleted file: {f}"))
        except Exception as e:
            logger.warning(i18n(f"删除文件 {f} 失败: {e}", f"Failed to delete file {f}: {e}"))


def downloadRes(
        path: str,
        server: str,
        attachmentName: str,
        targetFolder: str,
        aria2_rpc_url: str = "http://localhost:6888/jsonrpc",
        aria2_token: str = None,
        sourceAttachmentName: str | None = None,
        targetOS: str = "windows",
) -> str:
    """
    使用 aria2 RPC 添加下载任务，返回 aria2 分配的 GID。
    """
    attachmentName = sanitizeFilenameAdvanced(str(attachmentName), targetOS)
    urlAttachmentName = sanitizeFilenameAdvanced(
        str(sourceAttachmentName or attachmentName),
        targetOS,
    )
    targetUrl = server.rstrip("/") + "/data" + path + "?" + urlencode({"f": urlAttachmentName})

    options = {
        "dir": targetFolder,
        "out": attachmentName,
    }

    params = []

    if aria2_token:
        params.append(f"token:{aria2_token}")

    params.append([targetUrl])
    params.append(options)

    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "aria2.addUri",
        "params": params,
    }

    response = requests.post(aria2_rpc_url, json=payload)
    response.raise_for_status()
    res_json = response.json()
    logger.info(i18n(
        f"已添加 aria2 任务: {attachmentName} -> GID: {res_json.get('result')}",
        f"Added aria2 task for {attachmentName} -> GID: {res_json.get('result')}",
    ))
    return res_json.get("result")


def saveRes(targetFolder: str, filename: str, picContent: bytes, config: Config):
    """
    将字节内容写入文件，文件名先做 sanitize。
    使用 config.targetOS 来决定 sanitize 风格。
    """
    filename = sanitizeFilenameAdvanced(filename, config.targetOS)
    if not os.path.exists(targetFolder):
        os.makedirs(targetFolder)
        logger.info(i18n(f"已创建文件夹: {targetFolder}", f"Created folder: {targetFolder}"))

    filePath = os.path.join(targetFolder, filename)

    try:
        with open(filePath, "wb") as f:
            f.write(picContent)
        logger.info(i18n(f"已保存文件: {filePath}", f"Saved file: {filePath}"))
    except IOError as e:
        message = i18n(
            f"保存文件 {filePath} 时发生错误: {e}",
            f"Error saving file {filePath}: {e}",
        )
        logger.error(message)
        raise Exception(message)


# ---------------------------
# 批量附件下载任务结构 & 逻辑
# ---------------------------
@dataclass
class DownloadTask:
    gid: str
    attachment: dict
    attachmentName: str
    sourceName: str
    targetFolder: str
    retry_count: int = 0
    # 流水线模式：失败重试的到期时间戳；None 表示任务正在 aria2 中下载
    retry_due: Optional[float] = None


@dataclass
class AttachmentNamePlan:
    attachment: dict
    source_name: str
    existing_name: str
    download_name: str
    should_number: bool = False


def is_attachment_numbering_enabled(config: Config) -> bool:
    return config.numberAttachmentsMode != NUMBER_ATTACHMENTS_OFF


def is_attachment_numbering_rename_mode(config: Config) -> bool:
    return config.numberAttachmentsMode in (
        NUMBER_ATTACHMENTS_RENAME_ALL,
        NUMBER_ATTACHMENTS_RENAME_IMAGES,
    )


def is_attachment_numbering_image_only(config: Config) -> bool:
    return config.numberAttachmentsMode in (
        NUMBER_ATTACHMENTS_IMAGES,
        NUMBER_ATTACHMENTS_RENAME_IMAGES,
    )


def get_attachment_source_name(attachment: dict) -> str:
    name = attachment.get("name")
    if name is not None and str(name) != "":
        return str(name)

    path = attachment.get("path")
    if path is not None and str(path) != "":
        fallback = os.path.basename(str(path).rstrip("/"))
        if fallback:
            return fallback

    return "attachment"


def is_deferred_attachment(attachment: dict) -> bool:
    return attachment.get("deferred") is True


def log_deferred_attachment_error(attachment_name: str) -> None:
    logger.error(i18n(
        f"附件 {attachment_name} 标记为 deferred=true；Pawchive 并未存储该文件，已跳过下载。",
        f"Attachment {attachment_name} is marked deferred=true; "
        "Pawchive did not store this file, so the download was skipped.",
    ))


def get_attachment_extension(attachment: dict) -> str:
    for key in ("name", "path", "url"):
        value = attachment.get(key)
        if not value:
            continue
        clean_value = str(value).split("?", 1)[0].split("#", 1)[0]
        ext = os.path.splitext(clean_value)[1].lower()
        if ext:
            return ext
    return ""


def is_image_attachment(attachment: dict) -> bool:
    att_type = str(attachment.get("type") or "").strip().lower()
    if att_type in ("thumbnail", "image", "picture", "preview"):
        return True
    if att_type == "embed":
        return False
    return get_attachment_extension(attachment) in IMAGE_ATTACHMENT_EXTENSIONS


def is_numberable_attachment(attachment: dict) -> bool:
    return str(attachment.get("type") or "").strip().lower() != "embed"


def build_numbered_attachment_name(filename: str, index: int, width: int, config: Config) -> str:
    prefix = f"{index:0{width}d}_"
    return sanitizeFilenameAdvanced(prefix + filename, config.targetOS)


def prepare_attachment_name_plans(
        previews: List[dict],
        attachments: List[dict],
        config: Config,
) -> tuple[List[AttachmentNamePlan], List[AttachmentNamePlan]]:
    preview_plans = []
    for attachment in previews:
        source_name = sanitizeFilenameAdvanced(
            get_attachment_source_name(attachment),
            config.targetOS,
        )
        preview_plans.append(
            AttachmentNamePlan(
                attachment=attachment,
                source_name=source_name,
                existing_name=source_name,
                download_name=source_name,
            )
        )

    attachment_plans = []
    for attachment in attachments:
        source_name = get_attachment_source_name(attachment)
        existing_name = sanitizeFilenameAdvanced(source_name, config.targetOS)
        attachment_plans.append(
            AttachmentNamePlan(
                attachment=attachment,
                source_name=existing_name,
                existing_name=existing_name,
                download_name=existing_name,
            )
        )

    if not is_attachment_numbering_enabled(config):
        return preview_plans, attachment_plans

    image_only = is_attachment_numbering_image_only(config)
    target_plans = [
        plan
        for plan in preview_plans + attachment_plans
        if is_numberable_attachment(plan.attachment)
        and (not image_only or is_image_attachment(plan.attachment))
    ]
    width = max(2, len(str(len(target_plans))))
    for index, plan in enumerate(target_plans):
        plan.should_number = True
        plan.download_name = build_numbered_attachment_name(
            plan.existing_name,
            index,
            width,
            config,
        )

    return preview_plans, attachment_plans


def find_existing_numbered_attachment(targetFolder: str, existingName: str) -> Optional[str]:
    if not os.path.isdir(targetFolder):
        return None

    for filename in os.listdir(targetFolder):
        if not filename.endswith(existingName):
            continue
        prefix = filename[:-len(existingName)]
        if prefix.endswith("_") and prefix[:-1].isdigit():
            return os.path.join(targetFolder, filename)

    return None


def rename_existing_attachment_files(
        attachment_plans: List[AttachmentNamePlan],
        postFolder: str,
) -> bool:
    target_plans = [plan for plan in attachment_plans if plan.should_number]
    if not target_plans:
        logger.info(i18n(
            "没有符合编号条件的附件文件。",
            "No attachment files matched the numbering mode.",
        ))
        return True

    renamed_count = 0
    skipped_count = 0
    missing_count = 0

    for plan in target_plans:
        source_path = os.path.join(postFolder, plan.existing_name)
        target_path = os.path.join(postFolder, plan.download_name)

        if os.path.normcase(source_path) == os.path.normcase(target_path):
            skipped_count += 1
            continue

        if os.path.exists(target_path):
            logger.info(i18n(
                f"已存在编号文件，跳过: {plan.download_name}",
                f"Numbered file already exists, skipped: {plan.download_name}",
            ))
            skipped_count += 1
            continue

        if not os.path.exists(source_path):
            numbered_source = find_existing_numbered_attachment(postFolder, plan.existing_name)
            if numbered_source:
                source_path = numbered_source

        if not os.path.exists(source_path):
            logger.warning(i18n(
                f"未找到可重命名的已下载附件: {plan.existing_name}",
                f"Downloaded attachment not found for renaming: {plan.existing_name}",
            ))
            missing_count += 1
            continue

        try:
            os.rename(source_path, target_path)
            renamed_count += 1
            logger.info(i18n(
                f"已重命名附件: {os.path.basename(source_path)} -> {plan.download_name}",
                f"Renamed attachment: {os.path.basename(source_path)} -> {plan.download_name}",
            ))
        except OSError as e:
            missing_count += 1
            logger.error(i18n(
                f"重命名附件失败 {plan.existing_name} -> {plan.download_name}: {e}",
                f"Failed to rename attachment {plan.existing_name} -> {plan.download_name}: {e}",
            ))

    logger.info(i18n(
        f"附件编号重命名完成: 已重命名 {renamed_count}, 跳过 {skipped_count}, 缺失/失败 {missing_count}",
        f"Attachment numbering rename finished: renamed {renamed_count}, skipped {skipped_count}, missing/failed {missing_count}",
    ))
    return missing_count == 0


# ---------------------------
# 过滤 & 已存在文件检查
# ---------------------------
def parse_date_arg(value: str) -> date:
    """argparse type: YYYY-MM-DD -> date。"""
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(
            i18n(
                f"无效的日期: {value!r}，格式应为 YYYY-MM-DD",
                f"Invalid date: {value!r}; expected format YYYY-MM-DD",
            )
        )


def parse_list_arg(value: str) -> List[str]:
    """argparse type: 逗号分隔的字符串 -> 列表（去空白、去空项）。"""
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def parse_ext_list_arg(value: str) -> List[str]:
    """argparse type: 逗号分隔的扩展名列表，统一为小写且不带点。"""
    return [item.lower().lstrip(".") for item in parse_list_arg(value)]


def compile_text_matcher(
        patterns: List[str],
        use_regex: bool,
) -> Optional[Callable[[str], bool]]:
    """
    根据模式列表构建匹配器；列表为空返回 None（表示不过滤）。
    use_regex 时按正则 search 匹配（不区分大小写），否则按不区分大小写的子串匹配。
    正则非法时抛出 re.error，由调用方处理。
    """
    if not patterns:
        return None
    if use_regex:
        compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]

        def regex_match(text: str) -> bool:
            return any(pattern.search(text) for pattern in compiled)

        return regex_match

    lowered = [pattern.lower() for pattern in patterns]

    def substring_match(text: str) -> bool:
        lowered_text = text.lower()
        return any(pattern in lowered_text for pattern in lowered)

    return substring_match


def _passes_black_white_lists(
        text: str,
        whitelist_matcher: Optional[Callable[[str], bool]],
        blacklist_matcher: Optional[Callable[[str], bool]],
) -> bool:
    """白名单非空则须命中白名单，且不得命中黑名单。"""
    if whitelist_matcher is not None and not whitelist_matcher(text):
        return False
    if blacklist_matcher is not None and blacklist_matcher(text):
        return False
    return True


def match_post_title(title: str, config: Config) -> bool:
    return _passes_black_white_lists(
        title,
        config.titleWhitelistMatcher,
        config.titleBlacklistMatcher,
    )


def match_attachment(attachment: dict, config: Config) -> bool:
    """
    扩展名 / 文件名过滤。embed 附件（.url 快捷方式）不受过滤影响。
    """
    att_type = str(attachment.get("type") or "").strip().lower()
    if att_type == "embed":
        return True

    ext = get_attachment_extension(attachment).lstrip(".")
    if config.extWhitelist and ext not in config.extWhitelist:
        return False
    if ext and ext in config.extBlacklist:
        return False

    return _passes_black_white_lists(
        get_attachment_source_name(attachment),
        config.nameWhitelistMatcher,
        config.nameBlacklistMatcher,
    )


def _partition_filtered(
        attachments: List[dict],
        config: Config,
) -> tuple[List[dict], List[dict]]:
    """按过滤规则拆分附件列表，返回 (保留, 被过滤)。"""
    kept, filtered = [], []
    for attachment in attachments:
        (kept if match_attachment(attachment, config) else filtered).append(attachment)
    return kept, filtered


def get_post_date(post: dict) -> Optional[date]:
    """从帖子 published 字段解析日期（取前 10 位 YYYY-MM-DD）；失败返回 None。"""
    published = post.get("published")
    if not published:
        return None
    try:
        return datetime.strptime(str(published)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def probe_remote_file_size(
        server: str,
        path: str,
        url_name: str,
        config: Config,
) -> Optional[int]:
    """
    通过 HEAD 请求探测远程文件大小（字节）。
    任何失败（网络错误、非 2xx、缺少 Content-Length）均返回 None（fail-open）。
    """
    url = server.rstrip("/") + "/data" + path + "?" + urlencode({"f": url_name})
    headers = build_request_headers(config, referer=config.activeReferer)
    try:
        response = config.session.head(
            url,
            proxies=config.proxies,
            headers=headers,
            timeout=30,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            logger.warning(i18n(
                f"探测远程文件大小失败 (HTTP {response.status_code}): {url}",
                f"Failed to probe remote file size (HTTP {response.status_code}): {url}",
            ))
            return None
        content_length = response.headers.get("Content-Length")
        if content_length is None:
            logger.warning(i18n(
                f"远程响应缺少 Content-Length，无法校验大小: {url}",
                f"Remote response has no Content-Length; cannot verify size: {url}",
            ))
            return None
        return int(content_length)
    except (ValueError, requests.exceptions.RequestException) as e:
        logger.warning(i18n(
            f"探测远程文件大小时发生错误: {e} ({url})",
            f"Error while probing remote file size: {e} ({url})",
        ))
        return None


def check_local_file(
        targetFolder: str,
        download_name: str,
        server: str,
        path: str,
        url_name: str,
        config: Config,
) -> str:
    """
    检查本地已存在文件，返回 "download"（需要下载）或 "skip"（跳过）。

    判定规则：
      1. 文件不存在 -> download；
      2. 存在 .aria2 控制文件（下载中断残留）-> download（aria2 会断点续传）；
      3. existingFileMode == redownload -> download（总是重下，兼容旧行为）；
      4. existingFileMode == skip -> skip；
      5. existingFileMode == verify -> HEAD 探测比对大小：
         相等 -> skip；不等 -> 删除本地文件后 download；探测失败 -> 保守 skip。
    """
    file_path = os.path.join(
        targetFolder,
        sanitizeFilenameAdvanced(str(download_name), config.targetOS),
    )

    if not os.path.exists(file_path):
        return "download"

    if os.path.exists(file_path + ".aria2"):
        logger.info(i18n(
            f"检测到中断的下载残留 (.aria2)，将续传/重下: {file_path}",
            f"Found interrupted download residue (.aria2); will resume/redownload: {file_path}",
        ))
        return "download"

    if config.existingFileMode == EXISTING_FILE_REDOWNLOAD:
        return "download"

    if config.existingFileMode == EXISTING_FILE_SKIP:
        logger.info(i18n(f"文件已存在，跳过: {file_path}", f"File exists, skipped: {file_path}"))
        return "skip"

    remote_size = probe_remote_file_size(server, path, url_name, config)
    if remote_size is None:
        logger.warning(i18n(
            f"无法探测远程大小，保守跳过已存在文件: {file_path}",
            f"Could not probe remote size; conservatively skipping existing file: {file_path}",
        ))
        return "skip"

    local_size = os.path.getsize(file_path)
    if local_size == remote_size:
        logger.info(i18n(
            f"文件已存在且大小一致 ({local_size} 字节)，跳过: {file_path}",
            f"File exists with matching size ({local_size} bytes), skipped: {file_path}",
        ))
        return "skip"

    logger.info(i18n(
        f"文件大小不一致（本地 {local_size} / 远程 {remote_size} 字节），重新下载: {file_path}",
        f"Size mismatch (local {local_size} / remote {remote_size} bytes); redownloading: {file_path}",
    ))
    try:
        os.remove(file_path)
    except OSError as e:
        logger.warning(i18n(
            f"删除损坏文件失败 {file_path}: {e}",
            f"Failed to delete corrupted file {file_path}: {e}",
        ))
    return "download"


def submit_all_attachments(
        attachment_plans: List[AttachmentNamePlan],
        targetFolder: str,
        config: Config,
) -> tuple[List[DownloadTask], bool]:
    """
    先循环提交所有附件，记录 GID，返回 DownloadTask 列表和提交结果。
    """
    tasks: List[DownloadTask] = []
    all_submitted = True
    for plan in attachment_plans:
        attachment = plan.attachment
        attachmentName = plan.download_name

        if is_deferred_attachment(attachment):
            log_deferred_attachment_error(attachmentName)
            all_submitted = False
            continue

        path = attachment.get("path")
        server = get_attachment_server(attachment, config)

        decision = check_local_file(
            targetFolder,
            attachmentName,
            server,
            path,
            plan.source_name,
            config,
        )
        if decision == "skip":
            continue

        try:
            gid = downloadRes(
                path,
                server,
                attachmentName,
                targetFolder,
                aria2_rpc_url=config.aria2_rpc_url,
                aria2_token=None,
                sourceAttachmentName=plan.source_name,
                targetOS=config.targetOS,
            )
            logger.info(i18n(
                f"成功提交附件: {attachmentName}, GID={gid}",
                f"Submitted attachment: {attachmentName}, GID={gid}",
            ))
            tasks.append(
                DownloadTask(
                    gid=gid,
                    attachment=attachment,
                    attachmentName=attachmentName,
                    sourceName=plan.source_name,
                    targetFolder=targetFolder,
                    retry_count=0,
                )
            )
        except Exception as e:
            all_submitted = False
            logger.error(i18n(
                f"提交附件 {attachmentName} 到 Aria2 时失败: {e}",
                f"Failed to submit attachment {attachmentName} to Aria2: {e}",
            ))
    return tasks, all_submitted


def poll_and_retry_tasks(
        tasks: List[DownloadTask],
        config: Config,
        max_retries: int = MAX_TOTAL_RETRY,
        poll_interval: int = 3,
) -> bool:
    """
    轮询所有 GID 的状态：
      - 成功：从列表中移除，并提示下载成功；
      - 失败：从列表中移除，执行重试，将重试后的 GID 重新加入列表；
    直到所有任务都结束（成功或耗尽重试次数）。
    """
    active_tasks: List[DownloadTask] = list(tasks)
    all_success = True

    if not active_tasks:
        logger.info(i18n("没有附件需要下载。", "No attachments to download."))
        return True

    logger.info(i18n(
        f"开始等待下载任务完成，任务数量: {len(active_tasks)}",
        f"Waiting for download tasks to complete. Task count: {len(active_tasks)}",
    ))

    while active_tasks:
        if not check_run_control(config):
            for task in active_tasks:
                gid = task.gid
                try:
                    aria2_rpc_call(
                        "aria2.remove", [gid],
                        aria2_rpc_url=config.aria2_rpc_url,
                        aria2_token=None, timeout=5,
                    )
                except Exception:
                    pass
                try:
                    aria2_rpc_call(
                        "aria2.removeDownloadResult", [gid],
                        aria2_rpc_url=config.aria2_rpc_url,
                        aria2_token=None, timeout=5,
                    )
                except Exception:
                    pass
            logger.info(i18n(
                "收到停止请求，已清理在途 aria2 下载任务。",
                "Stop requested; cleaned up in-flight aria2 download tasks.",
            ))
            return False
        for task in list(active_tasks):
            gid = task.gid
            attachment = task.attachment
            attachmentName = task.attachmentName

            try:
                res = aria2_rpc_call(
                    "aria2.tellStatus",
                    [gid],
                    aria2_rpc_url=config.aria2_rpc_url,
                    aria2_token=None,
                )
                status = res.get("result", {}).get("status")
            except Exception as e:
                logger.error(i18n(
                    f"查询 GID={gid} (附件 {attachmentName}) 状态失败: {e}",
                    f"Failed to query status for GID={gid} (attachment {attachmentName}): {e}",
                ))
                continue

            if status == "complete":
                logger.info(i18n(
                    f"附件 {attachmentName} 下载完成 (GID={gid})",
                    f"Attachment {attachmentName} download completed (GID={gid})",
                ))
                active_tasks.remove(task)


            elif status in ("error", "removed"):
                logger.warning(
                    i18n(
                        f"附件 {attachmentName} 下载失败 (GID={gid})，当前重试次数: {task.retry_count}",
                        f"Attachment {attachmentName} download failed (GID={gid}); current retry count: {task.retry_count}",
                    )
                )
                # 先从当前轮询列表中移除该任务
                active_tasks.remove(task)
                # 在重试之前，删除 aria2 中旧的任务记录
                try:
                    aria2_rpc_call(
                        "aria2.removeDownloadResult",
                        [gid],
                        aria2_rpc_url=config.aria2_rpc_url,
                        aria2_token=None,
                    )
                    logger.info(i18n(
                        f"已从 aria2 中删除任务记录 (GID={gid})",
                        f"Removed download record from aria2 (GID={gid})",
                    ))
                except Exception as e:
                    # 删除失败不影响后续重试，只记录一下
                    logger.warning(i18n(
                        f"从 aria2 删除任务记录失败 (GID={gid}): {e}",
                        f"Failed to remove download record from aria2 (GID={gid}): {e}",
                    ))
                if task.retry_count >= max_retries:
                    logger.error(
                        i18n(
                            f"附件 {attachmentName} 已耗尽最大重试次数 ({max_retries})，放弃下载。",
                            f"Attachment {attachmentName} reached the maximum retry count ({max_retries}); giving up.",
                        )
                    )
                    all_success = False
                    continue
                # 删除失败任务产生的文件（包括 .aria2）
                cleanup_files(task.targetFolder, attachmentName)
                # 计算退避时间
                if task.retry_count < SMALL_RETRY_TIMES:
                    backoff = SMALL_RETRY_INTERVAL
                else:
                    backoff = BIG_RETRY_BASE_INTERVAL * (
                            task.retry_count - SMALL_RETRY_TIMES + 1
                    )
                logger.info(
                    i18n(
                        f"附件 {attachmentName} 将在 {backoff} 秒后重试 "
                        f"(当前重试次数: {task.retry_count + 1}/{max_retries})",
                        f"Attachment {attachmentName} will retry in {backoff} seconds "
                        f"(retry {task.retry_count + 1}/{max_retries})",
                    )
                )
                time.sleep(backoff)
                # 重新提交新的下载任务
                try:
                    new_gid = downloadRes(
                        attachment.get("path"),
                        get_attachment_server(attachment, config),
                        attachmentName,
                        task.targetFolder,
                        aria2_rpc_url=config.aria2_rpc_url,
                        aria2_token=None,
                        sourceAttachmentName=task.sourceName,
                        targetOS=config.targetOS,
                    )
                    logger.info(
                        i18n(
                            f"已重新提交附件 {attachmentName}，新 GID={new_gid} "
                            f"(重试次数: {task.retry_count + 1})",
                            f"Resubmitted attachment {attachmentName}; new GID={new_gid} "
                            f"(retry count: {task.retry_count + 1})",
                        )
                    )
                    new_task = DownloadTask(
                        gid=new_gid,
                        attachment=attachment,
                        attachmentName=attachmentName,
                        sourceName=task.sourceName,
                        targetFolder=task.targetFolder,
                        retry_count=task.retry_count + 1,
                    )
                    active_tasks.append(new_task)
                except Exception as e:
                    logger.error(i18n(
                        f"重试提交附件 {attachmentName} 到 Aria2 失败: {e}",
                        f"Failed to resubmit attachment {attachmentName} to Aria2: {e}",
                    ))
                    all_success = False
            else:
                logger.debug(
                    i18n(
                        f"附件 {attachmentName} 状态: {status} (GID={gid})，继续等待...",
                        f"Attachment {attachmentName} status: {status} (GID={gid}); waiting...",
                    )
                )

        if active_tasks:
            time.sleep(poll_interval)

    logger.info(i18n(
        "全部附件的下载任务已处理完毕。",
        "All attachment download tasks have been processed.",
    ))
    return all_success


def sweep_pending_tasks(config: Config) -> None:
    """
    流水线模式：对所有在途任务做一次非阻塞状态扫描。
      - 下载完成 -> 移出队列；
      - 下载失败 -> 计算退避时间并记录 retry_due，到期后重新提交（不阻塞抓取流程）；
      - 重试到期 -> 清理残留文件并重新提交。
    """
    if not config.pendingTasks:
        return

    now = time.time()
    for task in list(config.pendingTasks):
        attachmentName = task.attachmentName

        # 等待重试到期的任务
        if task.retry_due is not None:
            if task.retry_due > now:
                continue
            config.pendingTasks.remove(task)
            cleanup_files(task.targetFolder, attachmentName)
            try:
                new_gid = downloadRes(
                    task.attachment.get("path"),
                    get_attachment_server(task.attachment, config),
                    attachmentName,
                    task.targetFolder,
                    aria2_rpc_url=config.aria2_rpc_url,
                    aria2_token=None,
                    sourceAttachmentName=task.sourceName,
                    targetOS=config.targetOS,
                )
                logger.info(i18n(
                    f"已重新提交附件 {attachmentName}，新 GID={new_gid} "
                    f"(重试次数: {task.retry_count})",
                    f"Resubmitted attachment {attachmentName}; new GID={new_gid} "
                    f"(retry count: {task.retry_count})",
                ))
                task.gid = new_gid
                task.retry_due = None
                config.pendingTasks.append(task)
            except Exception as e:
                logger.error(i18n(
                    f"重试提交附件 {attachmentName} 到 Aria2 失败: {e}",
                    f"Failed to resubmit attachment {attachmentName} to Aria2: {e}",
                ))
                if task.retry_count >= MAX_TOTAL_RETRY:
                    config.failedAttachments.append(attachmentName)
                else:
                    task.retry_due = time.time() + BIG_RETRY_BASE_INTERVAL
                    config.pendingTasks.append(task)
            continue

        gid = task.gid
        try:
            res = aria2_rpc_call(
                "aria2.tellStatus",
                [gid],
                aria2_rpc_url=config.aria2_rpc_url,
                aria2_token=None,
            )
            status = res.get("result", {}).get("status")
        except Exception as e:
            logger.error(i18n(
                f"查询 GID={gid} (附件 {attachmentName}) 状态失败: {e}",
                f"Failed to query status for GID={gid} (attachment {attachmentName}): {e}",
            ))
            continue

        if status == "complete":
            logger.info(i18n(
                f"附件 {attachmentName} 下载完成 (GID={gid})",
                f"Attachment {attachmentName} download completed (GID={gid})",
            ))
            config.pendingTasks.remove(task)

        elif status in ("error", "removed"):
            logger.warning(i18n(
                f"附件 {attachmentName} 下载失败 (GID={gid})，当前重试次数: {task.retry_count}",
                f"Attachment {attachmentName} download failed (GID={gid}); current retry count: {task.retry_count}",
            ))
            config.pendingTasks.remove(task)
            try:
                aria2_rpc_call(
                    "aria2.removeDownloadResult",
                    [gid],
                    aria2_rpc_url=config.aria2_rpc_url,
                    aria2_token=None,
                )
            except Exception as e:
                logger.warning(i18n(
                    f"从 aria2 删除任务记录失败 (GID={gid}): {e}",
                    f"Failed to remove download record from aria2 (GID={gid}): {e}",
                ))
            if task.retry_count >= MAX_TOTAL_RETRY:
                logger.error(i18n(
                    f"附件 {attachmentName} 已耗尽最大重试次数 ({MAX_TOTAL_RETRY})，放弃下载。",
                    f"Attachment {attachmentName} reached the maximum retry count ({MAX_TOTAL_RETRY}); giving up.",
                ))
                config.failedAttachments.append(attachmentName)
                continue
            if task.retry_count < SMALL_RETRY_TIMES:
                backoff = SMALL_RETRY_INTERVAL
            else:
                backoff = BIG_RETRY_BASE_INTERVAL * (task.retry_count - SMALL_RETRY_TIMES + 1)
            task.retry_count += 1
            task.retry_due = now + backoff
            logger.info(i18n(
                f"附件 {attachmentName} 将在 {backoff} 秒后重试 "
                f"(重试次数: {task.retry_count}/{MAX_TOTAL_RETRY})",
                f"Attachment {attachmentName} will retry in {backoff} seconds "
                f"(retry {task.retry_count}/{MAX_TOTAL_RETRY})",
            ))
            config.pendingTasks.append(task)

        else:
            logger.debug(i18n(
                f"附件 {attachmentName} 状态: {status} (GID={gid})，继续等待...",
                f"Attachment {attachmentName} status: {status} (GID={gid}); waiting...",
            ))


def drain_pending_tasks(config: Config, poll_interval: int = 3) -> bool:
    """
    流水线模式收尾：阻塞扫描直到所有在途任务结束（成功或耗尽重试）。
    返回是否全部成功。
    """
    if not config.pipelineEnabled:
        return not config.failedAttachments

    if config.pendingTasks:
        logger.info(i18n(
            f"抓取结束，等待剩余 {len(config.pendingTasks)} 个下载任务完成...",
            f"Fetching finished; waiting for {len(config.pendingTasks)} remaining download task(s)...",
        ))
    while config.pendingTasks:
        if not check_run_control(config):
            abort_pending_tasks(config)
            return False
        sweep_pending_tasks(config)
        if config.pendingTasks:
            time.sleep(poll_interval)

    if config.failedAttachments:
        logger.error(i18n(
            f"共 {len(config.failedAttachments)} 个附件下载失败: {config.failedAttachments}",
            f"{len(config.failedAttachments)} attachment(s) failed: {config.failedAttachments}",
        ))
    else:
        logger.info(i18n(
            "全部附件的下载任务已处理完毕。",
            "All attachment download tasks have been processed.",
        ))
    return not config.failedAttachments


def sleep_with_sweeps(config: Config, seconds: float) -> None:
    """流水线模式下把帖间等待拆分为小片，其间扫描下载状态。"""
    if not config.pipelineEnabled or seconds <= 0:
        if not check_run_control(config):
            return
        time.sleep(max(0.0, seconds))
        return
    slices = max(1, int(seconds))
    for i in range(slices):
        if not check_run_control(config):
            return
        time.sleep(seconds / slices)
        sweep_pending_tasks(config)


def process_attachments_batch(
        attachment_plans: List[AttachmentNamePlan],
        postFolder: str,
        config: Config,
) -> bool:
    """
    对一个帖子里的所有附件：
      1. 先统一提交任务并记录 GID；
      2. 流水线模式：任务并入全局队列并做一次非阻塞扫描，立即返回；
         非流水线模式：统一轮询所有 GID 的状态并按需重试（阻塞至完成）。
    """
    tasks, all_submitted = submit_all_attachments(attachment_plans, postFolder, config)
    if config.pipelineEnabled:
        config.pendingTasks.extend(tasks)
        sweep_pending_tasks(config)
        return all_submitted
    downloads_succeeded = poll_and_retry_tasks(tasks, config)
    return all_submitted and downloads_succeeded


# ---------------------------
# 帖子抓取核心逻辑
# ---------------------------
def process_attachment(
        attachment,
        postFolder: str,
        config: Config,
        name_plan: AttachmentNamePlan | None = None,
):
    fallbackName = sanitizeFilenameAdvanced(get_attachment_source_name(attachment), config.targetOS)
    attachmentName = name_plan.download_name if name_plan else fallbackName
    sourceName = name_plan.source_name if name_plan else fallbackName
    att_type = attachment.get("type")

    if is_deferred_attachment(attachment):
        log_deferred_attachment_error(attachmentName)
        return i18n(
            f"跳过 Pawchive 未存储的附件: {attachmentName}",
            f"Skipped attachment not stored by Pawchive: {attachmentName}",
        )

    if att_type == "thumbnail":
        if attachment.get("name") == "https://mega.nz/rich-folder.png":
            config.skipPic.insert(0, attachment.get("path"))
        for i in config.skipPic:
            if i == attachment.get("path"):
                return i18n(f"跳过垃圾附件 (path: {i})", f"Skipped junk attachment (path: {i})")
        decision = check_local_file(
            postFolder,
            attachmentName,
            get_attachment_server(attachment, config),
            attachment.get("path"),
            sourceName,
            config,
        )
        if decision == "skip":
            return i18n(
                f"图片附件已存在，跳过: {attachmentName}",
                f"Image attachment already exists, skipped: {attachmentName}",
            )
        try:
            downloadRes(
                attachment.get("path"),
                get_attachment_server(attachment, config),
                attachmentName,
                postFolder,
                aria2_rpc_url=config.aria2_rpc_url,
                aria2_token=None,
                sourceAttachmentName=sourceName,
                targetOS=config.targetOS,
            )
            return i18n(
                f"成功处理图片附件: {attachmentName}",
                f"Processed image attachment successfully: {attachmentName}",
            )
        except Exception as e:
            return i18n(
                f"处理图片附件 {attachmentName} 时发生错误: {e}",
                f"Error while processing image attachment {attachmentName}: {e}",
            )

    if att_type == "embed":
        urlContent = "[InternetShortcut]\nURL=" + attachment.get("url")
        bUrlContent = bytes(urlContent, encoding="utf8")
        subject = attachment.get("subject")
        saveRes(
            postFolder,
            "em" + str(config.embedCount) + "_" + subject + ".url",
            bUrlContent,
            config,
        )
        config.embedCount += 1
        return i18n(f"成功处理嵌入附件: {subject}", f"Processed embed attachment successfully: {subject}")

    return i18n(
        f"跳过非图附件: {attachmentName} (类型: {att_type})",
        f"Skipped non-image attachment: {attachmentName} (type: {att_type})",
    )


def build_post_folder_path(post: dict, config: Config) -> tuple[str, str]:
    path = post.get("published")[2:10] + "_" + post.get("title") + "_" + post.get("id")
    path = sanitizeFilenameAdvanced(path, config.targetOS)
    return path, os.path.join(config.folder, path)


def write_post_content_file(post: dict, postFolder: str, config: Config) -> bool:
    contentContent = post.get("content")

    if contentContent is None or contentContent == "":
        return False

    site_base_url = get_site_base_url(config.baseUrl)
    content_html = contentContent.replace('src="/', f'src="{site_base_url}')
    content_html = content_html.replace('href="/', f'href="{site_base_url}')
    title = str(post.get("title") or "Untitled")
    escaped_title = html.escape(title)
    contentContent = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{escaped_title}</title>
            <style>
                :root {{
                    color-scheme: light;
                    --text: #1f2937;
                    --accent: #238636;
                }}

                * {{
                    box-sizing: border-box;
                }}

                body {{
                    margin: 0;
                    min-height: 100vh;
                    color: var(--text);
                    font-family:
                        "Segoe UI",
                        "Noto Sans CJK SC",
                        "Noto Sans JP",
                        "Microsoft YaHei",
                        sans-serif;
                }}

                .container {{
                    width: min(920px, calc(100% - 32px));
                    margin: 48px auto;
                    padding: 24px 16px 48px;
                }}

                .page-header {{
                    margin-bottom: 28px;
                }}

                h1 {{
                    margin: 0;
                    font-size: clamp(22px, 3vw, 30px);
                    line-height: 1.35;
                    font-weight: 700;
                }}

                .post-content {{
                    white-space: pre-line;
                    overflow-wrap: break-word;
                    font-size: 17px;
                    line-height: 1.9;
                }}

                ul {{
                    padding-left: 20px;
                }}

                ul li {{
                    line-height: 2.1;
                }}

                a {{
                    color: var(--accent);
                    text-decoration-thickness: 0.08em;
                    text-underline-offset: 0.16em;
                }}

                img,
                video {{
                    display: block;
                    max-width: 100%;
                    height: auto;
                    margin: 24px auto;
                    border-radius: 6px;
                }}

                blockquote {{
                    margin: 24px 0;
                    padding: 0;
                    color: #667085;
                }}

                @media (max-width: 700px) {{
                    .container {{
                        width: 100%;
                        margin: 0;
                        padding: 24px 18px 40px;
                    }}

                    .page-header {{
                        margin-bottom: 24px;
                    }}

                    .post-content {{
                        font-size: 16px;
                        line-height: 1.85;
                    }}
                }}
            </style>
        </head>
        <body>
            <article class="container">
                <header class="page-header">
                    <h1>{escaped_title}</h1>
                </header>
                <main class="post-content">{content_html}</main>
            </article>
        </body>
        </html>
        """
    contentPath = os.path.join(postFolder, "!Content.html")
    try:
        with open(contentPath, "w", encoding="utf-8") as file:
            file.write(contentContent)
        logger.info(i18n(
            f"内容已成功写入文件: {contentPath}",
            f"Content written successfully: {contentPath}",
        ))
        return True
    except IOError:
        logger.error(i18n(
            f"错误: 无法写入文件 {contentPath}",
            f"Error: unable to write file {contentPath}",
        ))
    except Exception as e:
        logger.error(i18n(
            f"发生了一个预料之外的错误: {e}",
            f"An unexpected error occurred: {e}",
        ))

    return False


def empty_content_key(service: str, userID: str, postID: str) -> str:
    return f"{service}:{userID}:{postID}"


def remember_empty_content_post(
        config: Config,
        postID: str,
        userID: str,
        service: str,
        post: dict,
        postFolder: str,
):
    key = empty_content_key(service, userID, postID)
    was_known = key in config.emptyContentPosts
    config.emptyContentPosts[key] = {
        "postID": postID,
        "userID": userID,
        "service": service,
        "postFolder": postFolder,
        "post": dict(post),
    }
    if not was_known:
        logger.warning(i18n(
            f"帖子 {postID} 的 content 为空，已加入待补写队列。",
            f"Post {postID} has empty content and was queued for content retry.",
        ))


def forget_empty_content_post(config: Config, service: str, userID: str, postID: str):
    key = empty_content_key(service, userID, postID)
    config.emptyContentPosts.pop(key, None)


def extract_post_from_detail(data, config: Config, postID: str):
    if not isinstance(data, dict):
        logger.error(i18n(
            f"帖子详情 JSON 类型不符合预期: {type(data).__name__}",
            f"Unexpected post detail JSON type: {type(data).__name__}",
        ))
        return None

    if config.kemonoMode:
        post = data.get("post")
        if not post:
            logger.error(i18n(
                f"返回的数据中没有 'post' 字段，跳过帖子 {postID}。",
                f"The returned data does not contain a 'post' field; skipping post {postID}.",
            ))
            return None
    else:
        post = data

    if not isinstance(post, dict):
        logger.error(i18n(
            f"帖子对象结构不符合预期，跳过帖子 {postID}。",
            f"Unexpected post object structure; skipping post {postID}.",
        ))
        return None

    return post


def retry_empty_content_posts(config: Config, reason: str):
    if not config.emptyContentPosts:
        return
    if not check_run_control(config):
        return

    logger.info(i18n(
        f"开始补抓空 content 帖子（{reason}），待处理: {len(config.emptyContentPosts)}",
        f"Retrying empty-content posts ({reason}); pending: {len(config.emptyContentPosts)}",
    ))

    for key, record in list(config.emptyContentPosts.items()):
        postID = record["postID"]
        userID = record["userID"]
        service = record["service"]
        logger.info(i18n(
            f"重新执行预访问+API: {postID}",
            f"Re-running pre-visit + API for post: {postID}",
        ))

        data = fetch_post_detail_data(postID, userID, service, config)
        post = extract_post_from_detail(data, config, postID) if data else None
        if not post:
            continue

        content = post.get("content")
        if content is None or content == "":
            logger.info(i18n(
                f"帖子 {postID} 补抓后 content 仍为空。",
                f"Post {postID} still has empty content after retry.",
            ))
            continue

        merged_post = dict(record.get("post") or {})
        merged_post.update(post)
        if write_post_content_file(merged_post, record["postFolder"], config):
            config.emptyContentPosts.pop(key, None)
            logger.info(i18n(
                f"帖子 {postID} 已补写 content。",
                f"Post {postID} content was written after retry.",
            ))


def maybe_retry_empty_content_posts(config: Config, fetched_count: int):
    if fetched_count not in config.emptyContentRetryMilestones:
        return
    if fetched_count in config.emptyContentRetryMilestonesDone:
        return

    config.emptyContentRetryMilestonesDone.add(fetched_count)
    retry_empty_content_posts(config, i18n(
        f"已获取 {fetched_count} 个帖子",
        f"after fetching {fetched_count} posts",
    ))


def getPost(postID: str, userID: str, service: str, config: Config):
    """
    通过 config 提供的参数（baseUrl, proxies, headers, maxRetries, baseBackoffFactor, folder, targetOS, skipPic, embedCount）
    """
    data = fetch_post_detail_data(postID, userID, service, config)

    if not data:
        logger.error(i18n(
            "未收到有效数据，终止处理该帖子。",
            "No valid data was received; stopping this post.",
        ))
        return None

    if not isinstance(data, dict):
        logger.error(i18n(
            f"帖子详情 JSON 类型不符合预期: {type(data).__name__}",
            f"Unexpected post detail JSON type: {type(data).__name__}",
        ))
        return None

    if config.kemonoMode:
        post = data.get("post")
        if not post:
            logger.error(i18n(
                "返回的数据中没有 'post' 字段，跳过。",
                "The returned data does not contain a 'post' field; skipping.",
            ))
            return None
    else:
        post = data

    if not isinstance(post, dict):
        logger.error(i18n(
            f"帖子对象结构不符合预期，跳过帖子 {postID}。",
            f"Unexpected post object structure; skipping post {postID}.",
        ))
        return None

    missing_fields = [
        field_name
        for field_name in ("published", "title", "id")
        if not post.get(field_name)
    ]
    if missing_fields:
        logger.error(i18n(
            f"帖子 {postID} 缺少必要字段 {missing_fields}，跳过。",
            f"Post {postID} is missing required fields {missing_fields}; skipping.",
        ))
        return None

    path, postFolder = build_post_folder_path(post, config)
    logger.info(i18n(f"\n\n正在取帖子 {path}", f"\n\nFetching post {path}"))

    config.activeReferer = build_kemono_referer(config, service, userID, postID)

    previews = data.get("previews", [])
    attachments = data.get("attachments", [])
    previews, filtered_previews = _partition_filtered(previews, config)
    attachments, filtered_attachments = _partition_filtered(attachments, config)
    filtered_count = len(filtered_previews) + len(filtered_attachments)
    if filtered_count:
        logger.info(i18n(
            f"根据过滤规则跳过 {filtered_count} 个附件: "
            f"{[get_attachment_source_name(a) for a in filtered_previews + filtered_attachments]}",
            f"Skipped {filtered_count} attachment(s) by filter rules: "
            f"{[get_attachment_source_name(a) for a in filtered_previews + filtered_attachments]}",
        ))
    preview_plans, attachment_plans = prepare_attachment_name_plans(
        previews,
        attachments,
        config,
    )

    origin_is_kemono = str(post.get("origin") or "").strip().lower() == "kemono"

    if is_attachment_numbering_rename_mode(config) and not origin_is_kemono:
        logger.info(i18n(f"准备为已下载附件编号: {path}", f"Preparing to number downloaded attachments for {path}"))
        if not os.path.exists(postFolder):
            logger.warning(i18n(
                f"帖子文件夹不存在，跳过重命名: {postFolder}",
                f"Post folder does not exist; skipping rename: {postFolder}",
            ))
            return None

        rename_success = rename_existing_attachment_files(
            preview_plans + attachment_plans,
            postFolder,
        )
        if not rename_success:
            logger.warning(i18n(
                "部分附件未能完成编号重命名，请检查上面的缺失/失败记录。",
                "Some attachments could not be numbered; check the missing/failed records above.",
            ))
        return None

    if not os.path.exists(postFolder):
        os.makedirs(postFolder)
        logger.info(i18n(f"已创建文件夹: {postFolder}", f"Created folder: {postFolder}"))

    if write_post_content_file(post, postFolder, config):
        forget_empty_content_post(config, service, userID, postID)
    else:
        remember_empty_content_post(config, postID, userID, service, post, postFolder)

    if origin_is_kemono:
        logger.warning(i18n(
            f"帖子 {postID} 仅来自 Kemono 镜像；将只记录帖子内容，"
            "并跳过该帖的所有文件下载。",
            f"Post {postID} is available only through the Kemono mirror; "
            "only its content will be recorded, and all file downloads will be skipped.",
        ))
        return None

    logger.info(i18n(f"准备下载 {path}", f"Preparing downloads for {path}"))

    config.embedCount = 0

    for plan in preview_plans:
        res = process_attachment(plan.attachment, postFolder, config, plan)
        logger.debug(f"process_attachment (preview) result: {res}")

    if attachments:
        all_success = process_attachments_batch(attachment_plans, postFolder, config)
        if all_success:
            if config.pipelineEnabled:
                logger.info(i18n(
                    "所有一般附件均已提交下载（流水线模式，后台下载中）",
                    "All regular attachments submitted (pipeline mode; downloading in background).",
                ))
            else:
                logger.info(i18n(
                    "所有一般附件均下载成功，继续执行后续操作",
                    "All regular attachments downloaded successfully; continuing.",
                ))
        else:
            logger.error(i18n(
                "存在附件未能下载（文件未存储、提交失败或重试耗尽），"
                "继续执行后续操作时请注意上述错误。",
                "Some attachments could not be downloaded because the file was not stored, "
                "submission failed, or retries were exhausted; continuing, but please review the errors above.",
            ))
    else:
        logger.info(i18n("该帖子没有一般附件。", "This post has no regular attachments."))

    return None


def getPostFromPage(
        userID: str,
        service: str,
        postBegins: int = 0,
        config: Config = None,
):
    if config is None:
        raise ValueError(i18n(
            "config 必须提供给 getPostFromPage",
            "config must be provided to getPostFromPage",
        ))

    if postBegins > 0:
        o = postBegins - 1
    else:
        o = 0
    while not o % 50 == 0:
        o -= 1

    profileUrl = config.baseUrl + service + "/user/" + userID + "/profile"
    user_page_headers = build_request_headers(
        config,
        referer=build_kemono_referer(config, service, userID),
    )

    response = None
    for attempt in range(config.maxRetries):
        response = None
        flag = False
        try:
            response = config.session.get(
                profileUrl,
                proxies=config.proxies,
                headers=user_page_headers,
            )
            response.raise_for_status()
            flag = True

        except requests.exceptions.Timeout:
            logger.warning(
                i18n(
                    f"获取页面超时 (尝试 {attempt + 1}/{config.maxRetries}): {profileUrl}",
                    f"Timed out while fetching page (attempt {attempt + 1}/{config.maxRetries}): {profileUrl}",
                )
            )
        except requests.exceptions.HTTPError as e:
            if e.response is not None and 500 <= e.response.status_code < 600:
                logger.warning(
                    i18n(
                        f"获取页面遭遇服务器错误 (HTTP {e.response.status_code}) "
                        f"(尝试 {attempt + 1}/{config.maxRetries}): {e}",
                        f"Server error while fetching page (HTTP {e.response.status_code}) "
                        f"(attempt {attempt + 1}/{config.maxRetries}): {e}",
                    )
                )
            elif e.response.status_code == 429:
                logger.warning(
                    i18n(
                        f"获取帖子遭遇服务器错误 (HTTP 429) "
                        f"(尝试 {attempt * 5}/{config.maxRetries}): {e}",
                        f"Rate limited while fetching posts (HTTP 429) "
                        f"(attempt {attempt * 5}/{config.maxRetries}): {e}",
                    )
                )
            else:
                logger.error(
                    i18n(
                        f"获取页面失败 (HTTP {e.response.status_code if e.response else 'Unknown'})，不重试: {e}",
                        f"Failed to fetch page (HTTP {e.response.status_code if e.response else 'Unknown'}); not retrying: {e}",
                    )
                )
                return None
        except requests.exceptions.RequestException as e:
            logger.warning(
                i18n(
                    f"获取页面时发生网络错误 (尝试 {attempt + 1}/{config.maxRetries}): {e}",
                    f"Network error while fetching page (attempt {attempt + 1}/{config.maxRetries}): {e}",
                )
            )
        except Exception as e:
            logger.error(
                i18n(
                    f"获取页面时发生未知错误 (尝试 {attempt + 1}/{config.maxRetries}): {e}",
                    f"Unexpected error while fetching page (attempt {attempt + 1}/{config.maxRetries}): {e}",
                )
            )

        if flag:
            break

        if attempt < config.maxRetries - 1:
            waitTime = config.baseBackoffFactor * (2 ** attempt)
            logger.info(i18n(
                f"将在 {waitTime:.2f} 秒后重试...",
                f"Retrying in {waitTime:.2f} seconds...",
            ))
            time.sleep(waitTime)
        else:
            logger.error(i18n(
                f"所有 {config.maxRetries} 次尝试获取页面均失败。",
                f"All {config.maxRetries} attempts to fetch the page failed.",
            ))
            return None

    try:
        resp_json = response.json()
    except Exception as e:
        logger.error(i18n(f"解析 profile JSON 失败: {e}", f"Failed to parse profile JSON: {e}"))
        return None

    userName = service + "_" + resp_json.get("name", "unknown")
    if (not resp_json.get("public_id") is None) and (
            not resp_json.get("name") == resp_json.get("public_id")
    ):
        userName += "_" + resp_json.get("public_id")

    config.folder = os.path.join(config.folder, userName)

    count = o
    selected_posts = 0
    processed_posts = 0

    while True:
        if config.postCounts > 0 and selected_posts >= config.postCounts:
            logger.info(i18n(
                f"\n\n{config.postCounts}个帖子取完了…",
                f"\n\nFinished fetching {config.postCounts} posts.",
            ))
            return None

        logger.info(i18n(
            f"\n\n正在取{userName}的第{o + 1}到{o + 50}个帖子…",
            f"\n\nFetching posts {o + 1} to {o + 50} for {userName}...",
        ))

        if o == 0:
            url = config.baseUrl + service + "/user/" + userID + "/posts"
        else:
            url = config.baseUrl + service + "/user/" + userID + "/posts?o=" + str(o)

        for attempt in range(config.maxRetries):
            response = None
            flag = False
            try:
                response = config.session.get(
                    url,
                    proxies=config.proxies,
                    headers=user_page_headers,
                )
                response.raise_for_status()
                flag = True

            except requests.exceptions.Timeout:
                logger.warning(
                    i18n(
                        f"获取页面超时 (尝试 {attempt + 1}/{config.maxRetries}): {url}",
                        f"Timed out while fetching page (attempt {attempt + 1}/{config.maxRetries}): {url}",
                    )
                )
            except requests.exceptions.HTTPError as e:
                if e.response is not None and 500 <= e.response.status_code < 600:
                    logger.warning(
                        i18n(
                            f"获取页面遭遇服务器错误 (HTTP {e.response.status_code}) "
                            f"(尝试 {attempt + 1}/{config.maxRetries}): {e}",
                            f"Server error while fetching page (HTTP {e.response.status_code}) "
                            f"(attempt {attempt + 1}/{config.maxRetries}): {e}",
                        )
                    )
                elif e.response.status_code == 429:
                    logger.warning(
                        i18n(
                            f"获取帖子遭遇服务器错误 (HTTP 429) "
                            f"(尝试 {attempt * 5}/{config.maxRetries}): {e}",
                            f"Rate limited while fetching posts (HTTP 429) "
                            f"(attempt {attempt * 5}/{config.maxRetries}): {e}",
                        )
                    )
                else:
                    logger.error(
                        i18n(
                            f"获取页面失败 (HTTP {e.response.status_code if e.response else 'Unknown'})，不重试: {e}",
                            f"Failed to fetch page (HTTP {e.response.status_code if e.response else 'Unknown'}); not retrying: {e}",
                        )
                    )
                    return None
            except requests.exceptions.RequestException as e:
                logger.warning(
                    i18n(
                        f"获取页面时发生网络错误 (尝试 {attempt + 1}/{config.maxRetries}): {e}",
                        f"Network error while fetching page (attempt {attempt + 1}/{config.maxRetries}): {e}",
                    )
                )
            except Exception as e:
                logger.error(
                    i18n(
                        f"获取页面时发生未知错误 (尝试 {attempt + 1}/{config.maxRetries}): {e}",
                        f"Unexpected error while fetching page (attempt {attempt + 1}/{config.maxRetries}): {e}",
                    )
                )

            if flag:
                break

            if attempt < config.maxRetries - 1:
                waitTime = config.baseBackoffFactor * (2 ** attempt)
                logger.info(i18n(
                    f"将在 {waitTime:.2f} 秒后重试...",
                    f"Retrying in {waitTime:.2f} seconds...",
                ))
                time.sleep(waitTime)
            else:
                logger.error(i18n(
                    f"所有 {config.maxRetries} 次尝试获取页面均失败。",
                    f"All {config.maxRetries} attempts to fetch the page failed.",
                ))
                return None

        if response.text == "[]":
            logger.info(i18n(
                f"\n\n{userName}的帖子取完了…",
                f"\n\nFinished fetching posts for {userName}.",
            ))
            return o

        o += 50

        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.warning(i18n("错误：无效的 JSON 字符串", "Error: invalid JSON string"))
            return None
        except AttributeError:
            logger.warning(i18n(
                "错误：JSON 对象结构不符合预期",
                "Error: unexpected JSON object structure",
            ))
            return None

        stop_fetching = False
        for post in data:
            if not check_run_control(config):
                logger.info(i18n(
                    "\n\n收到停止请求，抓取已终止。",
                    "\n\nStop requested; fetching aborted.",
                ))
                return None
            count += 1  # count 现在表示当前帖子在列表中的序号（从 1 开始，新到旧）

            # 范围条件 1: 起始序号
            if count < postBegins:
                continue

            # 范围条件 2/3: 日期区间（均含当日）
            post_date = get_post_date(post)
            if post_date is not None:
                if config.dateTo is not None and post_date > config.dateTo:
                    continue  # 晚于截止日期，跳过但继续扫描
                if config.dateFrom is not None and post_date < config.dateFrom:
                    # 列表按新到旧排序，早于起始日期即可安全终止整个抓取
                    logger.info(i18n(
                        f"\n\n已到达起始日期 {config.dateFrom}，停止抓取。",
                        f"\n\nReached start date {config.dateFrom}; stopping.",
                    ))
                    stop_fetching = True
                    break

            # 标题过滤（不消耗帖子详情请求）
            title = str(post.get("title") or "")
            if not match_post_title(title, config):
                logger.info(i18n(
                    f"根据标题过滤规则跳过帖子: {title} ({post.get('id')})",
                    f"Skipped post by title filter: {title} ({post.get('id')})",
                ))
                continue

            # 范围条件 4: 已选中数量上限
            if config.postCounts > 0 and selected_posts >= config.postCounts:
                logger.info(i18n(
                    f"\n\n{config.postCounts}个帖子取完了…",
                    f"\n\nFinished fetching {config.postCounts} posts.",
                ))
                return None

            getPost(post.get("id"), post.get("user"), post.get("service"), config)
            selected_posts += 1
            processed_posts += 1
            maybe_retry_empty_content_posts(config, processed_posts)
            sleep_with_sweeps(config, 3)

        if stop_fetching:
            return None


# ---------------------------
# 文件名清洗工具
# ---------------------------
def sanitizeFilenameAdvanced(
        filename: str,
        targetOS: str = "windows",
        default_replacement_char: str = "_",
        max_filename_length: int = 255,
        visual_similar_replacements: Dict[str, str] = None,
        reserved_names_windows: Iterable[str] = None,
) -> str:
    if not isinstance(filename, str):
        raise TypeError(i18n("输入文件名必须是字符串。", "filename must be a string."))

    target = targetOS.lower()
    if target not in ("windows", "linux"):
        raise ValueError(i18n(
            "targetOS 必须是 'windows' 或 'linux'。",
            "targetOS must be 'windows' or 'linux'.",
        ))

    if visual_similar_replacements is None:
        visual_similar_replacements = {
            "<": "＜",
            ">": "＞",
            ":": "：",
            '"': "＂",
            "|": "｜",
            "?": "？",
            "*": "＊",
            "/": "-",
            "\\": "_",
        }

    if reserved_names_windows is None:
        reserved_names_windows = {
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4",
            "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4",
            "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        }

    base = filename
    base = unicodedata.normalize("NFKC", base)

    processed_chars = []
    for ch in base:
        illegal = False
        codepoint = ord(ch)
        if codepoint < 32 or codepoint == 127:
            illegal = True
        elif target == "windows":
            if ch in '<>:"/\\|?*':
                illegal = True
        else:
            if ch == "/":
                illegal = True

        if illegal:
            if ch in visual_similar_replacements:
                processed_chars.append(visual_similar_replacements[ch])
            else:
                processed_chars.append(default_replacement_char)
        else:
            processed_chars.append(ch)

    clean_base = "".join(processed_chars)
    name_part, ext_part = os.path.splitext(clean_base)

    clean_name = name_part.lstrip(" ")
    if target == "windows":
        clean_name = clean_name.rstrip(" .")
    else:
        clean_name = clean_name.rstrip(" ")

    if target == "windows":
        if clean_name.upper() in reserved_names_windows:
            clean_name = default_replacement_char + clean_name

    ext = ext_part or ""
    max_name_len = max_filename_length - len(ext)

    if max_name_len <= 0:
        clean_name = default_replacement_char
        ext = ext[: max(0, max_filename_length - 1)]
    elif len(clean_name) > max_name_len:
        clean_name = clean_name[:max_name_len]

    final_name = clean_name + ext

    if not final_name or set(final_name) <= {"."}:
        return default_replacement_char

    return final_name


# ---------------------------
# CLI & 主入口
# ---------------------------
def parse_bool_arg(value):
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError(i18n("需要布尔值: true/false", "Expected a boolean value: true/false"))


def parse_number_attachments_arg(value):
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "0": NUMBER_ATTACHMENTS_OFF,
        "false": NUMBER_ATTACHMENTS_OFF,
        "no": NUMBER_ATTACHMENTS_OFF,
        "n": NUMBER_ATTACHMENTS_OFF,
        "off": NUMBER_ATTACHMENTS_OFF,
        "disable": NUMBER_ATTACHMENTS_OFF,
        "disabled": NUMBER_ATTACHMENTS_OFF,
        "关闭": NUMBER_ATTACHMENTS_OFF,
        "1": NUMBER_ATTACHMENTS_ALL,
        "true": NUMBER_ATTACHMENTS_ALL,
        "yes": NUMBER_ATTACHMENTS_ALL,
        "y": NUMBER_ATTACHMENTS_ALL,
        "on": NUMBER_ATTACHMENTS_ALL,
        "enable": NUMBER_ATTACHMENTS_ALL,
        "enabled": NUMBER_ATTACHMENTS_ALL,
        "all": NUMBER_ATTACHMENTS_ALL,
        "开启": NUMBER_ATTACHMENTS_ALL,
        "全部": NUMBER_ATTACHMENTS_ALL,
        "image": NUMBER_ATTACHMENTS_IMAGES,
        "images": NUMBER_ATTACHMENTS_IMAGES,
        "pic": NUMBER_ATTACHMENTS_IMAGES,
        "pics": NUMBER_ATTACHMENTS_IMAGES,
        "picture": NUMBER_ATTACHMENTS_IMAGES,
        "pictures": NUMBER_ATTACHMENTS_IMAGES,
        "图片": NUMBER_ATTACHMENTS_IMAGES,
        "图像": NUMBER_ATTACHMENTS_IMAGES,
        "rename": NUMBER_ATTACHMENTS_RENAME_ALL,
        "renumber": NUMBER_ATTACHMENTS_RENAME_ALL,
        "重命名": NUMBER_ATTACHMENTS_RENAME_ALL,
        "image_rename": NUMBER_ATTACHMENTS_RENAME_IMAGES,
        "images_rename": NUMBER_ATTACHMENTS_RENAME_IMAGES,
        "rename_images": NUMBER_ATTACHMENTS_RENAME_IMAGES,
        "pic_rename": NUMBER_ATTACHMENTS_RENAME_IMAGES,
        "图片重命名": NUMBER_ATTACHMENTS_RENAME_IMAGES,
        "图片模式重命名": NUMBER_ATTACHMENTS_RENAME_IMAGES,
    }
    try:
        return aliases[normalized]
    except KeyError:
        raise argparse.ArgumentTypeError(i18n(
            "编号模式必须是 off/on/image/rename/image_rename，或中文：关闭/开启/图片/重命名/图片模式重命名。",
            "Numbering mode must be one of off/on/image/rename/image_rename.",
        ))


def parse_args(argv=None):
    configure_argparse_language()

    default_baseUrl = "https://pawchive.pw/"
    default_fileServer = "https://file.pawchive.pw/"
    default_max_retries = 5
    default_base_backoff_factor = 3.0
    default_folder = os.getcwd()

    parser = argparse.ArgumentParser(
        description=i18n("脚本参数配置", "Script parameter configuration")
    )
    parser.add_argument(
        "userid",
        help=i18n("需要下载的用户的ID (必填)", "Target user ID (required)"),
    )
    parser.add_argument(
        "service",
        help=i18n("服务名称，如 fanbox/patreon (必填)", "Service name, such as fanbox/patreon (required)"),
    )
    parser.add_argument(
        "--base_url",
        type=str,
        default=default_baseUrl,
        help=i18n(
            f"API基础URL (默认: {default_baseUrl})",
            f"API base URL (default: {default_baseUrl})",
        ),
    )
    parser.add_argument(
        "--file_server",
        type=str,
        default=default_fileServer,
        help=i18n(
            f"文件服务器 (默认: {default_fileServer})",
            f"File server (default: {default_fileServer})",
        ),
    )
    parser.add_argument(
        "--proxy_url",
        type=str,
        default=None,
        help=i18n(
            "代理URL (例如: http://localhost:7890)。如果提供，将启用代理。",
            "Proxy URL (for example: http://localhost:7890). If provided, proxy mode is enabled.",
        ),
    )
    parser.add_argument(
        "--max_retries",
        type=int,
        default=default_max_retries,
        help=i18n(
            f"页面访问最大工作重试次数 (默认: {default_max_retries})",
            f"Maximum page request retries (default: {default_max_retries})",
        ),
    )
    parser.add_argument(
        "--base_backoff_factor",
        type=float,
        default=default_base_backoff_factor,
        help=i18n(
            f"页面访问基准重试延迟时间 (默认: {default_base_backoff_factor})",
            f"Base retry delay for page requests (default: {default_base_backoff_factor})",
        ),
    )
    parser.add_argument(
        "--folder",
        type=str,
        default=default_folder,
        help=i18n(
            f"目标文件夹 (默认: 当前工作目录，{default_folder})",
            f"Target folder (default: current working directory, {default_folder})",
        ),
    )
    parser.add_argument(
        "--post_begins",
        type=int,
        default=1,
        help=i18n(
            "从该账户的第 N 个 post 开始（默认: 1）",
            "Start from the Nth post for this account (default: 1)",
        ),
    )
    parser.add_argument(
        "--post_counts",
        type=int,
        default=0,
        help=i18n(
            "取 N 个 post，0 或小于等于0 表示无限制（默认: 0）",
            "Fetch N posts; 0 or less means unlimited (default: 0)",
        ),
    )
    parser.add_argument(
        "--ext_blacklist",
        "--ext-blacklist",
        dest="ext_blacklist",
        type=parse_ext_list_arg,
        default=[],
        metavar="EXT1,EXT2,...",
        help=i18n(
            "扩展名黑名单（逗号分隔，不区分大小写），例如: mp4,zip",
            "Extension blacklist (comma-separated, case-insensitive), for example: mp4,zip",
        ),
    )
    parser.add_argument(
        "--ext_whitelist",
        "--ext-whitelist",
        dest="ext_whitelist",
        type=parse_ext_list_arg,
        default=[],
        metavar="EXT1,EXT2,...",
        help=i18n(
            "扩展名白名单（逗号分隔，不区分大小写）；非空时仅下载列出的类型",
            "Extension whitelist (comma-separated, case-insensitive); if set, only listed types are downloaded",
        ),
    )
    parser.add_argument(
        "--name_blacklist",
        "--name-blacklist",
        dest="name_blacklist",
        type=parse_list_arg,
        default=[],
        metavar="P1,P2,...",
        help=i18n(
            "文件名黑名单（逗号分隔）；默认按不区分大小写的子串匹配，--name_regex 启用后按正则匹配",
            "Filename blacklist (comma-separated); case-insensitive substring match by default, regex when --name_regex is set",
        ),
    )
    parser.add_argument(
        "--name_whitelist",
        "--name-whitelist",
        dest="name_whitelist",
        type=parse_list_arg,
        default=[],
        metavar="P1,P2,...",
        help=i18n(
            "文件名白名单（逗号分隔）；匹配规则同 --name_blacklist",
            "Filename whitelist (comma-separated); same matching rules as --name_blacklist",
        ),
    )
    parser.add_argument(
        "--name_regex",
        "--name-regex",
        dest="name_regex",
        type=parse_bool_arg,
        nargs="?",
        const=True,
        default=False,
        help=i18n(
            "文件名黑/白名单按正则表达式匹配（默认: false）",
            "Treat filename blacklist/whitelist patterns as regular expressions (default: false)",
        ),
    )
    parser.add_argument(
        "--title_blacklist",
        "--title-blacklist",
        dest="title_blacklist",
        type=parse_list_arg,
        default=[],
        metavar="P1,P2,...",
        help=i18n(
            "Post 标题黑名单（逗号分隔）；默认按不区分大小写的子串匹配，--title_regex 启用后按正则匹配",
            "Post title blacklist (comma-separated); case-insensitive substring match by default, regex when --title_regex is set",
        ),
    )
    parser.add_argument(
        "--title_whitelist",
        "--title-whitelist",
        dest="title_whitelist",
        type=parse_list_arg,
        default=[],
        metavar="P1,P2,...",
        help=i18n(
            "Post 标题白名单（逗号分隔）；匹配规则同 --title_blacklist",
            "Post title whitelist (comma-separated); same matching rules as --title_blacklist",
        ),
    )
    parser.add_argument(
        "--title_regex",
        "--title-regex",
        dest="title_regex",
        type=parse_bool_arg,
        nargs="?",
        const=True,
        default=False,
        help=i18n(
            "Post 标题黑/白名单按正则表达式匹配（默认: false）",
            "Treat post title blacklist/whitelist patterns as regular expressions (default: false)",
        ),
    )
    parser.add_argument(
        "--date_from",
        "--date-from",
        dest="date_from",
        type=parse_date_arg,
        default=None,
        metavar="YYYY-MM-DD",
        help=i18n(
            "起始日期（含当日），早于该日期的 post 不下载；与 --post_begins 同用表示从第 N 个取到该日期",
            "Start date (inclusive); posts older than this are skipped. Combined with --post_begins, fetches from the Nth post back to this date",
        ),
    )
    parser.add_argument(
        "--date_to",
        "--date-to",
        dest="date_to",
        type=parse_date_arg,
        default=None,
        metavar="YYYY-MM-DD",
        help=i18n(
            "截止日期（含当日），晚于该日期的 post 不下载；与 --post_counts 同用表示从该日期起取前 N 个",
            "End date (inclusive); posts newer than this are skipped. Combined with --post_counts, fetches the first N posts starting from this date",
        ),
    )
    parser.add_argument(
        "--existing_file",
        "--existing-file",
        dest="existing_file",
        choices=EXISTING_FILE_MODES,
        default=EXISTING_FILE_VERIFY,
        help=i18n(
            "已存在文件的处理方式: skip=直接跳过; redownload=总是重新下载（旧行为）; "
            "verify=探测远程文件大小，一致则跳过、不一致（损坏/中断）则重下（默认: verify）",
            "How to handle existing files: skip=skip directly; redownload=always redownload (legacy behavior); "
            "verify=probe remote file size, skip if identical, redownload if mismatched (default: verify)",
        ),
    )
    parser.add_argument(
        "--pipeline",
        type=parse_bool_arg,
        nargs="?",
        const=True,
        default=True,
        help=i18n(
            "流水线模式：提交下载任务后不等待完成，继续抓取后续帖子，下载在后台并行进行"
            "（默认: true；--pipeline false 恢复逐帖阻塞下载的旧行为）",
            "Pipeline mode: continue fetching subsequent posts without waiting for downloads "
            "(default: true; use --pipeline false to restore legacy blocking behavior)",
        ),
    )
    parser.add_argument(
        "--kemono_mode",
        type=parse_bool_arg,
        nargs="?",
        const=True,
        default=False,
        help=i18n(
            "启用 Kemono 原始响应结构和附件 server 字段兼容模式（默认: false）",
            "Enable compatibility with Kemono's original response structure and attachment server field (default: false)",
        ),
    )
    parser.add_argument(
        "--number_attachments",
        "--number-attachments",
        dest="number_attachments",
        type=parse_number_attachments_arg,
        nargs="?",
        const=NUMBER_ATTACHMENTS_ALL,
        default=NUMBER_ATTACHMENTS_OFF,
        metavar="MODE",
        help=i18n(
            "附件编号模式：关闭/off（默认）、开启/on、图片/image、重命名/rename、图片模式重命名/image_rename。"
            "开启会按附件顺序在文件名前加 00_ 起的编号；两个重命名模式不下载，只给已下载文件编号。",
            "Attachment numbering mode: off (default), on, image, rename, image_rename. "
            "When enabled, filenames are prefixed from 00_ by attachment order; rename modes do not download.",
        ),
    )
    parser.add_argument(
        "--aria2-rpc-url",
        dest="aria2_rpc_url",
        type=str,
        default=None,
        help=(
            i18n(
                "Aria2 JSON-RPC 地址，例如: http://localhost:6888/jsonrpc 。"
                "如果未指定，将在脚本开始时运行本地 aria2c.exe (--conf-path=aria2.conf)。",
                "Aria2 JSON-RPC URL, for example: http://localhost:6888/jsonrpc. "
                "If omitted, a local aria2c.exe is started at launch (--conf-path=aria2.conf).",
            )
        ),
    )

    args = parser.parse_args(argv)

    return args


def init_file_logger(folder: str):
    """
    在知道 folder 后，添加文件日志 handler。
    """
    file_log_path = os.path.join(folder, "kemono_downloader.log")

    existing_same_file_handler = any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == os.path.abspath(file_log_path)
        for h in logger.handlers
    )

    if not existing_same_file_handler:
        try:
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            file_handler = logging.FileHandler(file_log_path, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(_console_formatter)
            logger.addHandler(file_handler)
            logger.debug(i18n(
                f"文件日志已初始化: {file_log_path}",
                f"File log initialized at: {file_log_path}",
            ))
        except Exception as e:
            logger.warning(i18n(
                f"无法创建文件日志 {file_log_path}: {e}",
                f"Unable to create file log {file_log_path}: {e}",
            ))


def detect_target_os() -> str:
    current_os = platform.system().lower()
    if "windows" in current_os:
        return "windows"
    if "linux" in current_os:
        return "linux"

    logger.warning(
        i18n(
            f"检测到不支持的操作系统 '{platform.system()}'。将使用 Windows 默认设置。",
            f"Unsupported operating system '{platform.system()}' detected. Using Windows defaults.",
        )
    )
    return "windows"


def stop_aria2_process():
    """关闭本程序自己启动的 aria2c，外部 RPC 实例不会被触碰。"""
    global _local_aria2_cleanup_started

    process = _local_aria2_process
    if _local_aria2_cleanup_started or process is None:
        return

    _local_aria2_cleanup_started = True

    if process.poll() is not None:
        logger.info(i18n("本地 aria2c 进程已退出。", "Local aria2c process has already exited."))
        return

    if _local_aria2_rpc_url:
        try:
            aria2_rpc_call(
                "aria2.shutdown",
                [],
                aria2_rpc_url=_local_aria2_rpc_url,
                aria2_token=None,
                timeout=3,
            )
            logger.info(i18n(
                "已向本地 aria2c 发送关闭请求。",
                "Sent shutdown request to local aria2c.",
            ))
        except Exception as e:
            logger.warning(i18n(
                f"通过 RPC 关闭本地 aria2c 失败: {e}",
                f"Failed to shut down local aria2c via RPC: {e}",
            ))

    try:
        process.wait(timeout=8)
        logger.info(i18n("本地 aria2c 已关闭。", "Local aria2c has shut down."))
        return
    except subprocess.TimeoutExpired:
        logger.warning(i18n(
            "本地 aria2c 未按时退出，尝试终止进程。",
            "Local aria2c did not exit in time; attempting to terminate it.",
        ))

    try:
        process.terminate()
        process.wait(timeout=5)
        logger.info(i18n("已终止本地 aria2c 进程。", "Terminated local aria2c process."))
        return
    except subprocess.TimeoutExpired:
        logger.warning(i18n(
            "terminate 后本地 aria2c 仍未退出，尝试强制结束。",
            "Local aria2c still did not exit after terminate; attempting to kill it.",
        ))
    except Exception as e:
        logger.warning(i18n(
            f"终止本地 aria2c 失败: {e}",
            f"Failed to terminate local aria2c: {e}",
        ))

    try:
        process.kill()
        process.wait(timeout=5)
        logger.info(i18n("已强制结束本地 aria2c 进程。", "Killed local aria2c process."))
    except Exception as e:
        logger.error(i18n(
            f"强制结束本地 aria2c 失败: {e}",
            f"Failed to kill local aria2c: {e}",
        ))


def _signal_name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except ValueError:
        return str(signum)


def _handle_aria2_exit_signal(signum, frame):
    logger.info(i18n(
        f"收到退出信号 {_signal_name(signum)}，正在关闭本地 aria2c。",
        f"Received exit signal {_signal_name(signum)}; shutting down local aria2c.",
    ))
    stop_aria2_process()
    raise SystemExit(128 + signum)


def register_aria2_cleanup(process: subprocess.Popen, rpc_url: str):
    global _local_aria2_process, _local_aria2_rpc_url

    _local_aria2_process = process
    _local_aria2_rpc_url = rpc_url

    atexit.register(stop_aria2_process)

    for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, signal_name, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, _handle_aria2_exit_signal)
        except (OSError, RuntimeError, ValueError):
            logger.debug(i18n(
                f"当前环境无法注册 {signal_name} 退出处理。",
                f"Cannot register {signal_name} exit handler in the current environment.",
            ))


def start_aria2_process(proxy_url: Optional[str]) -> subprocess.Popen:
    """
    如果命令行未提供 RPC 地址，则在最开始启动 aria2c：
    Windows: .\\aria2c.exe --conf-path=aria2.conf --stop-with-process=<PID> [--all-proxy=...]
    其他:   ./aria2c    --conf-path=aria2.conf --stop-with-process=<PID> [--all-proxy=...]
    """
    if os.name == "nt":
        exe_path = ".\\aria2c.exe"
    else:
        exe_path = "./aria2c"

    ensure_aria2_conf()

    cmd = [exe_path, "--conf-path=aria2.conf", f"--stop-with-process={os.getpid()}"]

    if proxy_url:
        cmd.append(f"--all-proxy={proxy_url}")

    try:
        process = subprocess.Popen(cmd)
        logger.info(i18n(
            "已尝试启动本地 aria2c 进程: " + " ".join(cmd),
            "Attempted to start local aria2c process: " + " ".join(cmd),
        ))
    except FileNotFoundError:
        logger.error(i18n(
            f"启动 aria2c 失败，未找到可执行文件: {exe_path}",
            f"Failed to start aria2c; executable not found: {exe_path}",
        ))
        raise SystemExit(1)
    except Exception as e:
        logger.error(i18n(f"启动 aria2c 失败: {e}", f"Failed to start aria2c: {e}"))
        raise SystemExit(1)

    ariang_demo_url = build_ariang_rpc_setup_url(LOCAL_ARIA2_RPC_URL)
    logger.info(i18n(
        f"可打开 AriaNg 官方 demo 查看下载进度（按住Ctrl并点击下面的链接）:\n "
        f"{ariang_demo_url}",
        f"Open the official AriaNg demo to view download progress (hold Ctrl and click the link below) :\n "
        f"{ariang_demo_url}",
    ))
    time.sleep(5)

    if process.poll() is not None:
        logger.error(i18n(
            f"aria2c 进程已退出，退出码: {process.returncode}",
            f"aria2c process has exited with code: {process.returncode}",
        ))
        raise SystemExit(1)

    return process


def main(argv=None):
    args = parse_args(argv)

    userid = args.userid
    service = args.service

    cfg = Config()
    cfg.baseUrl = args.base_url
    cfg.fileServer = args.file_server
    cfg.kemonoMode = args.kemono_mode
    cfg.numberAttachmentsMode = args.number_attachments

    cfg.maxRetries = args.max_retries
    cfg.baseBackoffFactor = args.base_backoff_factor
    cfg.targetOS = detect_target_os()
    cfg.folder = args.folder

    postBegins = max(1, int(args.post_begins))
    cfg.postCounts = max(0, int(args.post_counts))

    # 过滤配置
    cfg.extBlacklist = args.ext_blacklist
    cfg.extWhitelist = args.ext_whitelist
    cfg.dateFrom = args.date_from
    cfg.dateTo = args.date_to
    cfg.existingFileMode = args.existing_file
    cfg.pipelineEnabled = args.pipeline

    if cfg.dateFrom is not None and cfg.dateTo is not None and cfg.dateFrom > cfg.dateTo:
        logger.error(i18n(
            f"起始日期 {cfg.dateFrom} 晚于截止日期 {cfg.dateTo}，请检查参数。",
            f"Start date {cfg.dateFrom} is later than end date {cfg.dateTo}; please check the arguments.",
        ))
        sys.exit(2)

    try:
        cfg.nameBlacklistMatcher = compile_text_matcher(args.name_blacklist, args.name_regex)
        cfg.nameWhitelistMatcher = compile_text_matcher(args.name_whitelist, args.name_regex)
        cfg.titleBlacklistMatcher = compile_text_matcher(args.title_blacklist, args.title_regex)
        cfg.titleWhitelistMatcher = compile_text_matcher(args.title_whitelist, args.title_regex)
    except re.error as e:
        logger.error(i18n(
            f"正则表达式无效: {e}",
            f"Invalid regular expression: {e}",
        ))
        sys.exit(2)

    # 仅根据 proxy_url 判断是否使用代理
    if args.proxy_url:
        currentProxyUrlStr: Optional[str] = args.proxy_url
        cfg.proxies = {
            "http": currentProxyUrlStr,
            "https": currentProxyUrlStr,
        }
    else:
        currentProxyUrlStr = None
        cfg.proxies = None

    # 配置 Aria2 RPC 地址 & 启动 aria2c（如需要）
    init_file_logger(cfg.folder)
    if args.aria2_rpc_url:
        cfg.aria2_rpc_url = args.aria2_rpc_url
    elif is_attachment_numbering_rename_mode(cfg):
        cfg.aria2_rpc_url = LOCAL_ARIA2_RPC_URL
    else:
        cfg.aria2_rpc_url = LOCAL_ARIA2_RPC_URL
        aria2_process = start_aria2_process(currentProxyUrlStr)
        register_aria2_cleanup(aria2_process, cfg.aria2_rpc_url)

    logger.info(i18n("\n---- 配置来咯 ----", "\n---- Configuration ----"))
    logger.info(i18n(f"用户 ID: {userid}", f"User ID: {userid}"))
    logger.info(i18n(f"服务: {service}", f"Service: {service}"))
    logger.info(i18n(f"基础 URL: {cfg.baseUrl}", f"Base URL: {cfg.baseUrl}"))
    logger.info(i18n(f"文件服务器 URL: {cfg.fileServer}", f"File Server URL: {cfg.fileServer}"))
    logger.info(i18n(f"Kemono 模式: {cfg.kemonoMode}", f"Kemono Mode: {cfg.kemonoMode}"))
    logger.info(i18n(
        f"附件编号模式: {cfg.numberAttachmentsMode}",
        f"Attachment numbering mode: {cfg.numberAttachmentsMode}",
    ))
    logger.info(i18n(f"最大重试次数: {cfg.maxRetries}", f"MAX_RETRIES: {cfg.maxRetries}"))
    logger.info(i18n(
        f"基础退避系数: {cfg.baseBackoffFactor}",
        f"Base Backoff Factor: {cfg.baseBackoffFactor}",
    ))
    if cfg.proxies:
        logger.info(i18n("代理已启用: True", "Proxy Enabled: True"))
        logger.info(i18n(f"代理 URL: {currentProxyUrlStr}", f"Proxy URL: {currentProxyUrlStr}"))
        logger.info(i18n(f"代理配置: {cfg.proxies}", f"Proxies: {cfg.proxies}"))
    else:
        logger.info(i18n("代理已启用: False", "Proxy Enabled: False"))
    logger.info(i18n(f"Aria2 RPC URL: {cfg.aria2_rpc_url}", f"Aria2 RPC URL: {cfg.aria2_rpc_url}"))
    logger.info(i18n(f"目标系统: {cfg.targetOS}", f"Target OS: {cfg.targetOS}"))
    logger.info(i18n(f"目标文件夹: {cfg.folder}", f"Folder: {cfg.folder}"))
    logger.info(i18n(f"起始帖子序号: {postBegins}", f"Post begins: {postBegins}"))
    logger.info(i18n(f"帖子数量: {cfg.postCounts}", f"Post count: {cfg.postCounts}"))
    logger.info(i18n(
        f"已存在文件处理: {cfg.existingFileMode}",
        f"Existing file mode: {cfg.existingFileMode}",
    ))
    logger.info(i18n(
        f"流水线模式: {cfg.pipelineEnabled}",
        f"Pipeline mode: {cfg.pipelineEnabled}",
    ))
    if cfg.extBlacklist or cfg.extWhitelist:
        logger.info(i18n(
            f"扩展名过滤: 黑名单={cfg.extBlacklist} 白名单={cfg.extWhitelist}",
            f"Extension filter: blacklist={cfg.extBlacklist} whitelist={cfg.extWhitelist}",
        ))
    if cfg.dateFrom or cfg.dateTo:
        logger.info(i18n(
            f"日期过滤: {cfg.dateFrom or '-'} ~ {cfg.dateTo or '-'}",
            f"Date filter: {cfg.dateFrom or '-'} ~ {cfg.dateTo or '-'}",
        ))
    if args.name_blacklist or args.name_whitelist:
        logger.info(i18n(
            f"文件名过滤 (正则={args.name_regex}): 黑名单={args.name_blacklist} 白名单={args.name_whitelist}",
            f"Filename filter (regex={args.name_regex}): blacklist={args.name_blacklist} whitelist={args.name_whitelist}",
        ))
    if args.title_blacklist or args.title_whitelist:
        logger.info(i18n(
            f"标题过滤 (正则={args.title_regex}): 黑名单={args.title_blacklist} 白名单={args.title_whitelist}",
            f"Title filter (regex={args.title_regex}): blacklist={args.title_blacklist} whitelist={args.title_whitelist}",
        ))
    logger.info("-------------------\n")

    logger.info(i18n("\n---- 抓取开始咯 ----", "\n---- Fetch started ----"))

    cfg.baseUrl = cfg.baseUrl + "api/v1/"

    global _active_config
    _active_config = cfg
    try:
        getPostFromPage(userid, service, postBegins, cfg)
    finally:
        retry_empty_content_posts(cfg, i18n("结束时", "at end"))
        drain_pending_tasks(cfg)
        stop_aria2_process()
        _active_config = None


if __name__ == "__main__":
    main()
