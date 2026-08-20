# KemonoDownloader （PawchiveDownloader actually）

一个用于从 Kemono 批量下载创作者内容的 Python 工具

由于Kemono停止了下载服务，现在默认从 [**Pawchive**](https://pawchive.pw/) 下载

[**Pawchive**](https://pawchive.pw/) 是 Kemono.cr 的一个镜像，保存了 Kemono 停止下载服务后的所有缩略图以及文本资源



## 功能特性

- 批量下载指定创作者的所有帖子及附件

- 使用 Aria2 而不是 curl / request 进行高效下载，可通过 AriaNg 可视化查看进度

- 可选使用远程 Aria2 服务器进行下载

- 自动重试机制，应对 网络 / Kemono / 代理 不稳定情况

- 支持 HTTP/HTTPS 代理

- 自动创建按帖子组织的文件夹结构

- 相比旧版本，支持下载预览图、各类附件文件和嵌入链接

- 完整保存帖子内容为 HTML 文件

- 跨平台支持（Windows / Linux）

  

## 依赖

- Python 3.10+

- [requests](https://pypi.org/project/requests/)

- [Aria2](https://github.com/aria2/aria2/releases/tag/release-1.37.0)（指定下载服务器或使用本地 aria2c 可执行文件）

  

## 使用方法



### 下载工具和配置文件

下载最新的 Release 或者下载

> aria2.conf
>
> aria2.session
>
> main.py

三个文件，并从 [Aria2 release](https://github.com/aria2/aria2/releases/tag/release-1.37.0)  页面下载合适您系统的版本，放在和以上三个文件相同的目录下

安装依赖：

```
pip install requests
```

或者下载 requirements.txt 并执行
```
pip install -r requirements.txt
```



### 下载服务器配置

如果你拥有自己的 Aria2 下载服务器，或者本地已经运行了Aria2服务器，可以通过下面的命令行参数配置 Aria2 下载服务

如果你不知道什么是 Aria2 ，或者不想将在已有服务器中添加下载记录，可以不配置服务器，使用程序拉起的 Aria2 下载服务器进行下载。程序拉起的服务器使用6888端口，不会和本地已有服务器（如果有）冲突。



### 基本用法

本程序支持命令行调用，也提供图形界面（见下文"图形界面"章节）

```bash
python main.py <用户ID> <服务名称>
```
或
```cmd
KemonoDownloader.exe <用户ID> <服务名称>
```

**示例：**

如果Artist的页面链接为：

```
https://pawchive.pw/fanbox/user/12345678
```

那么使用命令为：
```bash
python main.py 12345678 fanbox
```
或
```cmd
KemonoDownloader.exe 12345678 fanbox
```



### 关于 Pawchive 未抓取到附件的帖子

如果抓取的帖子的附件未被Pawchive收录，程序将只会



### 命令行参数

| 参数                    | 说明                                                         | 默认值                          |
| ----------------------- | ------------------------------------------------------------ | ------------------------------- |
| `userid`                | 目标用户的 ID（必填）                                        | -                               |
| `service`               | 服务名称，如 `fanbox`、`patreon` 等（必填）                  | -                               |
| `--base_url`            | Kemono 基础 URL，现在默认指向 Pawchive。                     | `https://pawchive.pw/`          |
| `--file_server`         | Pawchive 下载服务器URL                                       | `https://file.pawchive.pw/`     |
| `--proxy_url`           | HTTP/HTTPS 代理地址                                          | `None`                          |
| `--max_retries`         | 页面请求最大重试次数                                         | `5`                             |
| `--base_backoff_factor` | 页面请求重试延迟基准因子（秒）                               | `3. 0`                          |
| `--folder`              | 下载目标文件夹                                               | 当前工作目录                    |
| `--post_begins`         | 从第 N 个帖子开始下载                                        | `1`                             |
| `--post_counts`         | 下载帖子数量（0 表示全部）                                   | `0`                             |
| `--ext_blacklist`       | 扩展名黑名单，逗号分隔（不区分大小写），如 `mp4,zip`         | 无                              |
| `--ext_whitelist`       | 扩展名白名单，逗号分隔；非空时仅下载列出的类型               | 无                              |
| `--name_blacklist`      | 文件名黑名单，逗号分隔；默认不区分大小写子串匹配             | 无                              |
| `--name_whitelist`      | 文件名白名单，逗号分隔                                       | 无                              |
| `--name_regex`          | 文件名黑/白名单按正则表达式匹配                              | `false`                         |
| `--title_blacklist`     | Post 标题黑名单，逗号分隔                                    | 无                              |
| `--title_whitelist`     | Post 标题白名单，逗号分隔                                    | 无                              |
| `--title_regex`         | Post 标题黑/白名单按正则表达式匹配                           | `false`                         |
| `--date_from`           | 起始日期 `YYYY-MM-DD`（含当日），早于该日期的帖子不下载      | 无                              |
| `--date_to`             | 截止日期 `YYYY-MM-DD`（含当日），晚于该日期的帖子不下载      | 无                              |
| `--existing_file`       | 已存在文件处理：`skip`/`redownload`/`verify`                 | `verify`                        |
| `--pipeline`            | 流水线模式：提交下载任务后继续抓取，下载在后台并行进行       | `true`                          |
| `--aria2-rpc-url`       | Aria2 JSON-RPC 地址                                          | `http://localhost:6888/jsonrpc` |
| `--kemono_mode`         | Kemono复活时的兼容性选项                                     | `false`                         |
| `--number_attachments`  | 附件编号模式：`off`/`on`/`image`/`rename`/`image_rename`，也支持中文模式名 | `off`                           |

### 语言配置

程序会自动根据本地系统语言选择显示语言：

- 中文系统环境：显示中文
- 非中文系统环境：显示英文

也可以通过 `KEMONO_DOWNLOADER_LANG` 环境变量手动覆盖语言。以 `zh` 开头的值会使用中文，其他值（例如 `en`）会使用英文。该设置会影响控制台日志、错误提示和 `--help` 文案。

PowerShell：

```powershell
$env:KEMONO_DOWNLOADER_LANG = "zh"
python main.py 12345678 fanbox
```

命令提示符：

```cmd
set KEMONO_DOWNLOADER_LANG=zh
KemonoDownloader.exe 12345678 fanbox
```

Bash：

```bash
KEMONO_DOWNLOADER_LANG=zh python main.py 12345678 fanbox
```

### Kemono模式

对应命令行参数 `--kemono_mode` 

Pawchive 的服务器逻辑与Kemono存在一定的区别，如果 Kemono 重新提供文件下载，或者需要从其他和Kemono行为一样的服务器下载文件，需要在将`--base_url`指向Kemono的同时，将此参数设置为true。

### 使用代理

```bash
python main.py 12345678 fanbox --proxy_url http://127.0.0.1:7897
```



### 指定下载范围

```bash
# 从第 10 个帖子开始，下载 20 个帖子
python main.py 12345678 fanbox --post_begins 10 --post_counts 20
```

### 内容过滤

- 同一维度同时传入黑名单和白名单时，取交集：必须命中白名单且不命中黑名单。
- 文件名/标题默认按不区分大小写的子串匹配，加 `--name_regex` / `--title_regex` 后按正则匹配。
- 扩展名、文件名过滤同时作用于预览图和正式附件，embed（.url 链接）不受影响。
- 日期过滤基于帖子发布日期（均含当日），帖子列表按新到旧排序：
  - `--date_from` 与 `--post_begins` 同用：从第 N 个帖子取到起始日期为止；
  - `--date_to` 与 `--post_counts` 同用：从截止日期起取前 N 个帖子；
  - 三个及以上条件同用时取交集。

```bash
# 只下载 2026 年 6 月的图片
python main.py 12345678 fanbox --date_from 2026-06-01 --date_to 2026-06-30 --ext_whitelist jpg,jpeg,png

# 跳过视频和压缩包，标题含"通知"的帖子不下载
python main.py 12345678 fanbox --ext_blacklist mp4,zip --title_blacklist 通知
```

### 已存在文件处理

`--existing_file` 控制遇到同名本地文件时的行为：

- `skip`：直接跳过，不下载。
- `redownload`：总是重新下载（旧版本行为）。
- `verify`（默认）：通过 HEAD 请求探测远程文件大小，与本地一致则跳过；不一致（如下载中断导致的损坏文件）则删除并重下；探测失败时保守跳过。存在 `.aria2` 控制文件的中断残留会被识别并续传/重下。

```bash
python main.py 12345678 fanbox --existing_file skip
```

### 流水线模式

`--pipeline` 默认开启。开启后，提交下载任务不再阻塞抓取：程序保持每 3 秒一帖的原有节奏抓取帖子，附件下载由 Aria2 在后台并行进行，抓取结束后统一等待剩余任务完成；下载失败的重试按退避时间排期，不会卡住抓取流程。对 Pawchive 服务器的请求频率与旧版完全一致，实际下载并发数仍由 `aria2.conf` 的 `max-concurrent-downloads` 限制。

如需恢复逐帖阻塞下载的旧行为：

```bash
python main.py 12345678 fanbox --pipeline false
```

### 附件编号

`--number_attachments` 默认关闭。可选模式：

- `on` / `开启`：为所有附件文件名前追加顺序编号。
- `image` / `图片`：仅为图片类型附件追加编号。
- `rename` / `重命名`：不执行下载，只获取帖子信息并为已下载的附件文件编号。
- `image_rename` / `图片模式重命名`：不执行下载，只为已下载的图片类型附件编号。

编号从 `00_` 开始，默认两位；如果附件数量超过两位数，则使用附件数量的位数，例如 `000_`。

```bash
python main.py 12345678 fanbox --number_attachments on
python main.py 12345678 fanbox --number_attachments 图片模式重命名
```

## 图形界面

运行 `python ui.py` 启动图形界面（Tkinter，无需额外依赖）。界面完整支持命令行模式的所有功能：

- **下载目标**：直接粘贴创作者完整 URL（如 `https://pawchive.pw/fanbox/user/12345678` 或带 `/post/xxx` 后缀的帖子链接）即可自动识别服务名和用户 ID；识别时会校验 URL 主机名与"高级设置"中的基础 URL 是否一致。也可以手动填写两个字段（仅做非空校验，以兼容其他类似站点）。
- **基本设置**：下载目录、帖子范围、日期过滤、附件编号模式（界面默认"图片"模式；选择"重命名/图片模式重命名"时会显示警告，因为该模式不下载文件）。
- **内容过滤**：扩展名/文件名/标题黑白名单及正则开关。
- **高级设置**（默认折叠，自动保存）：基础 URL、文件服务器、代理、重试参数、Kemono 模式、已存在文件处理、流水线模式。
- **Aria2 设置**（默认折叠）：RPC 地址（留空则本地自启）及并发数、分段数、单服务器连接数、下载限速等，开始下载时写回 `aria2.conf`；使用远程 RPC 时这些选项仅对本地 aria2 生效。
- **下载任务**：实时显示 aria2 任务进度与全局速度（本地 RPC 每秒轮询，不增加服务器压力）。
- **暂停/继续**：下载进行中，"开始下载"按钮变为"暂停下载"，点击即同时暂停抓取与 aria2 下载；暂停状态下点击"开始下载"继续。
- **停止下载**："停止下载"按钮（位于"开始下载"左侧）立即终止抓取与下载任务，已下载的文件保留；在途 aria2 任务会被清理，不会在下次启动时失控自动续下。
- **日志**：界面内实时显示运行日志。

配置文件 `ui_config.json` 位于程序目录，保存下载目录、编号模式及高级设置的值，启动时自动载入。程序启动时若 `ui_config.json` 或 `aria2.conf` 缺失，会按默认配置自动生成。



## 打包为单文件 exe

程序可打包为单文件 `KemonoDownloader.exe`（仅主程序，**不包含 aria2c**）：

1. 安装构建依赖：`pip install pyinstaller`
2. 在项目目录运行 `build.bat`（或手动执行其中的 PyInstaller 命令）
3. 产物位于 `dist\KemonoDownloader.exe`

exe 同时支持两种调用方式：

- **双击运行**：打开图形界面（无控制台窗口）。
- **命令行调用**：行为与 `python main.py` 完全一致，在 cmd / PowerShell / Windows Terminal 中执行会挂接父控制台显示日志：
  ```cmd
  KemonoDownloader.exe <用户ID> <服务名称> [参数...]
  ```

部署时请将 `aria2c.exe` 放在 exe 同目录；`aria2.conf`、`aria2.session`、`ui_config.json` 缺失时会自动生成于 exe 同目录。若发生未处理的异常，错误详情会写入 exe 同目录的 `KemonoDownloader.error.log`。

## 输出结构

下载的内容会按以下结构组织：

```
<下载目录>/
└── <服务名>_<用户名>/
    ├── <发布日期>_<帖子标题>_<帖子ID>/
    │   ├── ! Content.html       # 帖子内容
    │   ├── 附件文件... 
    │   └── em0_xxx. url         # 嵌入链接
    └── ... 
```



## 日志

- 控制台实时输出 INFO 级别日志
- 下载目录下生成 `kemono_downloader. log` 文件，记录 DEBUG 级别详细日志



## Aria2 配置

如果未指定 `--aria2-rpc-url`，程序会自动在同目录下启动 `aria2c`，需要确保：

1. `aria2c` / `aria2c.exe` 可执行文件存在于程序目录
2. `aria2.conf` 配置文件存在于程序目录
3. 可打开 [AriaNg 官方 demo](<https://ariang.mayswind.net/latest/#!/settings/rpc/set?protocol=http&host=localhost&port=6888&interface=jsonrpc>) 查看下载进度；该链接会将 RPC 设置为本地 aria2 地址 `http://localhost:6888/jsonrpc`，不再需要本地 `AriaNg.html`



## 许可证

MIT License
