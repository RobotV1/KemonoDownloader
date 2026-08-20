[简体中文](./ReadMe_ZH_CN.md)

# KemonoDownloader (actually PawchiveDownloader)

A Python tool for batch-downloading creator content from Kemono.

Since Kemono has stopped providing download services, the default download source is now [**Pawchive**](https://pawchive.pw/).

[**Pawchive**](https://pawchive.pw/) is a mirror of Kemono.cr. It preserves all thumbnails and text resources after Kemono stopped its download service.

## Featuresf

- Batch-download all posts and attachments from a specified creator.
- Uses Aria2 instead of curl / requests for efficient downloads, with progress viewable through the AriaNg web UI.
- Optional support for downloading through a remote Aria2 server.
- Automatic retry mechanism for unstable network / Kemono / proxy conditions.
- HTTP/HTTPS proxy support.
- Automatically creates a folder structure organized by post.
- Compared with older versions, supports downloading previews, various attachment files, and embedded links.
- Saves full post content as HTML files.
- Cross-platform support (Windows / Linux).

## Dependencies

- Python 3.10+
- [requests](https://pypi.org/project/requests/)
- [Aria2](https://github.com/aria2/aria2/releases/tag/release-1.37.0) (use either a specified download server or a local `aria2c` executable)

## Usage

### Download the Tool and Configuration Files

Download the latest Release, or download the following three files:

> aria2.conf
>
> aria2.session
>
> main.py

Then download the appropriate version for your system from the [Aria2 release page](https://github.com/aria2/aria2/releases/tag/release-1.37.0), and place it in the same directory as the three files above.

Install dependencies:

```bash
pip install requests
```

Alternatively, download `requirements.txt` and run:

```bash
pip install -r requirements.txt
```

### Download Server Configuration

If you have your own Aria2 download server, or if an Aria2 server is already running locally, you can configure the Aria2 download service with the command-line arguments below.

If you do not know what Aria2 is, or if you do not want to add download records to an existing server, you can skip server configuration and use the Aria2 download server started by the program. The server started by the program uses port `6888`, so it will not conflict with an existing local server, if one exists.

### Basic Usage

This program supports command-line usage and also provides a graphical interface (see the "Graphical Interface" section below).

```bash
python main.py <user ID> <service name>
```

or

```cmd
KemonoDownloader.exe <user ID> <service name>
```

**Example:**

If the artist page URL is:

```text
https://pawchive.pw/fanbox/user/12345678
```

Then the command is:

```bash
python main.py 12345678 fanbox
```

or

```cmd
KemonoDownloader.exe 12345678 fanbox
```

### Posts Whose Attachments Were Not Crawled by Pawchive

If the attachments of a crawled post have not been archived by Pawchive, the program will only

### Command-Line Arguments

| Argument                | Description                                                  | Default                         |
| ----------------------- | ------------------------------------------------------------ | ------------------------------- |
| `userid`                | Target user ID (required)                                    | -                               |
| `service`               | Service name, such as `fanbox`, `patreon`, etc. (required)   | -                               |
| `--base_url`            | Kemono base URL. Currently points to Pawchive by default.    | `https://pawchive.pw/`          |
| `--file_server`         | Pawchive download server URL                                 | `https://file.pawchive.pw/`     |
| `--proxy_url`           | HTTP/HTTPS proxy address                                     | `None`                          |
| `--max_retries`         | Maximum number of retries for page requests                  | `5`                             |
| `--base_backoff_factor` | Base factor for page request retry delay (seconds)           | `3.0`                           |
| `--folder`              | Target download folder                                       | Current working directory       |
| `--post_begins`         | Start downloading from the Nth post                          | `1`                             |
| `--post_counts`         | Number of posts to download (`0` means all posts)            | `0`                             |
| `--ext_blacklist`       | Extension blacklist, comma-separated (case-insensitive), e.g. `mp4,zip` | None                            |
| `--ext_whitelist`       | Extension whitelist, comma-separated; if set, only listed types are downloaded | None                            |
| `--name_blacklist`      | Filename blacklist, comma-separated; case-insensitive substring match by default | None                            |
| `--name_whitelist`      | Filename whitelist, comma-separated                          | None                            |
| `--name_regex`          | Treat filename blacklist/whitelist patterns as regular expressions | `false`                         |
| `--title_blacklist`     | Post title blacklist, comma-separated                        | None                            |
| `--title_whitelist`     | Post title whitelist, comma-separated                        | None                            |
| `--title_regex`         | Treat post title blacklist/whitelist patterns as regular expressions | `false`                         |
| `--date_from`           | Start date `YYYY-MM-DD` (inclusive); older posts are skipped | None                            |
| `--date_to`             | End date `YYYY-MM-DD` (inclusive); newer posts are skipped   | None                            |
| `--existing_file`       | How to handle existing files: `skip`/`redownload`/`verify`   | `verify`                        |
| `--pipeline`            | Pipeline mode: keep fetching posts while downloads run in the background | `true`                          |
| `--aria2-rpc-url`       | Aria2 JSON-RPC address                                       | `http://localhost:6888/jsonrpc` |
| `--kemono_mode`         | Compatibility option for use if Kemono comes back online     | `false`                         |
| `--number_attachments`  | Attachment numbering mode: `off`/`on`/`image`/`rename`/`image_rename` | `off`                           |

### Language Configuration

The program chooses its display language automatically:

- Chinese system locale: Chinese output.
- Any other locale: English output.

You can override the detected language with the `KEMONO_DOWNLOADER_LANG` environment variable. Values starting with `zh` use Chinese; other values such as `en` use English. This affects console logs, error messages, and `--help` text.

PowerShell:

```powershell
$env:KEMONO_DOWNLOADER_LANG = "en"
python main.py 12345678 fanbox
```

Command Prompt:

```cmd
set KEMONO_DOWNLOADER_LANG=en
KemonoDownloader.exe 12345678 fanbox
```

Bash:

```bash
KEMONO_DOWNLOADER_LANG=en python main.py 12345678 fanbox
```

### Kemono Mode

Corresponds to the command-line argument `--kemono_mode`.

Pawchive's server behavior differs somewhat from Kemono's. If Kemono provides file downloads again, or if you need to download files from another server that behaves the same way as Kemono, point `--base_url` to Kemono and set this parameter to `true`.

### Using a Proxy

```bash
python main.py 12345678 fanbox --proxy_url http://127.0.0.1:7897
```

### Specify a Download Range

```bash
# Start from the 10th post and download 20 posts
python main.py 12345678 fanbox --post_begins 10 --post_counts 20
```

### Content Filtering

- When both a blacklist and a whitelist are given for the same dimension, the intersection applies: an item must match the whitelist and must not match the blacklist.
- Filenames and titles use case-insensitive substring matching by default; add `--name_regex` / `--title_regex` to use regular expressions.
- Extension and filename filters apply to both previews and regular attachments; embed (`.url`) attachments are not affected.
- Date filtering is based on post publish dates (both bounds inclusive). The post list is ordered newest to oldest:
  - `--date_from` with `--post_begins`: fetch from the Nth post back to the start date;
  - `--date_to` with `--post_counts`: fetch the first N posts starting from the end date;
  - with three or more conditions, the intersection applies.

```bash
# Download only images published in June 2026
python main.py 12345678 fanbox --date_from 2026-06-01 --date_to 2026-06-30 --ext_whitelist jpg,jpeg,png

# Skip videos and archives, and posts whose title contains "notice"
python main.py 12345678 fanbox --ext_blacklist mp4,zip --title_blacklist notice
```

### Existing File Handling

`--existing_file` controls what happens when a local file with the same name exists:

- `skip`: skip it without downloading.
- `redownload`: always redownload (legacy behavior).
- `verify` (default): probe the remote file size with a HEAD request; skip if it matches the local size, delete and redownload on mismatch (e.g. files corrupted by interrupted downloads); conservatively skip if the probe fails. Interrupted downloads with a leftover `.aria2` control file are detected and resumed/redownloaded.

```bash
python main.py 12345678 fanbox --existing_file skip
```

### Pipeline Mode

`--pipeline` is enabled by default. When enabled, submitting download tasks no longer blocks fetching: the program keeps its original pace of one post every 3 seconds while Aria2 downloads attachments in parallel in the background, and waits for remaining tasks after fetching finishes. Download-failure retries are scheduled by backoff time and do not stall the fetching loop. The request rate toward the Pawchive servers is identical to the legacy behavior, and actual download concurrency is still bounded by `max-concurrent-downloads` in `aria2.conf`.

To restore the legacy blocking behavior (wait for each post's downloads before fetching the next post):

```bash
python main.py 12345678 fanbox --pipeline false
```

### Attachment Numbering

`--number_attachments` is disabled by default. Available modes:

- `on`: prefix all attachment filenames by attachment order.
- `image`: prefix only image attachment filenames.
- `rename`: do not download; fetch post metadata and number already downloaded attachment files.
- `image_rename`: do not download; number only already downloaded image attachment files.

Numbering starts at `00_` and uses two digits by default. If the attachment count needs more digits, the count width is used instead, such as `000_`.

```bash
python main.py 12345678 fanbox --number_attachments on
python main.py 12345678 fanbox --number_attachments image_rename
```

## Graphical Interface

Run `python ui.py` to launch the graphical interface (Tkinter, no extra dependencies). The UI covers every feature of the command-line mode:

- **Download target**: paste a full creator URL (e.g. `https://pawchive.pw/fanbox/user/12345678`, or a post link with a `/post/xxx` suffix) to auto-detect the service and user ID; the URL host is validated against the base URL in "Advanced settings". You can also fill in the two fields manually (only a non-empty check, for compatibility with other similar sites).
- **Basic settings**: download folder, post range, date filters, attachment numbering mode (the UI defaults to "image"; choosing "rename"/"image_rename" shows a warning because those modes do not download files).
- **Content filters**: extension/filename/title blacklists and whitelists with regex toggles.
- **Advanced settings** (collapsed by default, saved automatically): base URL, file server, proxy, retry parameters, Kemono mode, existing-file handling, pipeline mode.
- **Aria2 settings** (collapsed by default): RPC URL (empty = start local aria2), concurrency, splits, connections per server, and download speed limits, written back to `aria2.conf` when a download starts; these options only apply to the local aria2 when a remote RPC URL is used.
- **Download tasks**: real-time aria2 task progress and global speed (polled from the local RPC once per second; no extra pressure on the server).
- **Pause/Resume**: while a download is running, the "Start download" button becomes "Pause download"; clicking it pauses both fetching and aria2 downloads. While paused, click "Start download" to resume.
- **Stop**: the "Stop download" button (left of "Start download") immediately aborts fetching and download tasks; downloaded files are kept, and in-flight aria2 tasks are cleaned up so they are not auto-resumed uncontrollably on the next launch.
- **Log**: live log output inside the window.

The configuration file `ui_config.json` lives next to the program and stores the download folder, numbering mode, and advanced settings; it is loaded automatically on startup. If `ui_config.json` or `aria2.conf` is missing at startup, it is generated automatically with default values.

## Packaging as a Single-File Exe

The program can be packaged into a single `KemonoDownloader.exe` (main program only, **aria2c not included**):

1. Install the build dependency: `pip install pyinstaller`
2. Run `build.bat` in the project directory (or run the PyInstaller command inside it manually)
3. The artifact is at `dist\KemonoDownloader.exe`

The exe supports both invocation styles:

- **Double-click**: opens the graphical interface (no console window).
- **Command line**: behaves exactly like `python main.py`; when run from cmd / PowerShell / Windows Terminal it attaches to the parent console and shows logs:
  ```cmd
  KemonoDownloader.exe <user ID> <service name> [arguments...]
  ```

For deployment, place `aria2c.exe` next to the exe. `aria2.conf`, `aria2.session`, and `ui_config.json` are auto-generated next to the exe when missing. If an unhandled error occurs, details are written to `KemonoDownloader.error.log` next to the exe.

## Output Structure

Downloaded content is organized as follows:

```text
<download directory>/
└── <service name>_<username>/
    ├── <publish date>_<post title>_<post ID>/
    │   ├── ! Content.html       # Post content
    │   ├── attachment files...
    │   └── em0_xxx.url          # Embedded link
    └── ...
```

## Logs

- Real-time INFO-level logs are printed to the console.
- A `kemono_downloader.log` file is generated in the download directory, recording detailed DEBUG-level logs.

## Aria2 Configuration

If `--aria2-rpc-url` is not specified, the program automatically starts `aria2c` from the same directory. Make sure that:

1. The `aria2c` / `aria2c.exe` executable exists in the program directory.
2. The `aria2.conf` configuration file exists in the program directory.
3. Open the [official AriaNg demo](<https://ariang.mayswind.net/latest/#!/settings/rpc/set?protocol=http&host=localhost&port=6888&interface=jsonrpc>) to view download progress. The link sets RPC to the local aria2 URL `http://localhost:6888/jsonrpc`, so a local `AriaNg.html` is no longer needed.

## License

MIT License
