from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.theme import Theme
from textual.timer import Timer
from textual.widgets import Button, Input, Label, OptionList, ProgressBar, Select, Static
from textual.widgets.option_list import Option


# A deliberately low-resolution interpretation of a three-point geometric mark.
# Keeping it as text makes the identity crisp in every terminal without shipping
# an image asset or depending on a particular font.
LOGO_GEOMETRY = (
    "         ▲",
    "        ◢█◣",
    "       ◢███◣",
    "      ◢██ ██◣",
    "    ◢███   ███◣",
    "  ◢████  ◇  ████◣",
    "◢███    ╱ ╲    ███◣",
)


def render_logo(color: str) -> str:
    """Render the mark with a fixed one-cell down-right terminal shadow."""
    width = max(map(len, LOGO_GEOMETRY))
    geometry = tuple(line.ljust(width) for line in LOGO_GEOMETRY)
    rendered: list[str] = []
    for row in range(len(geometry) + 1):
        cells: list[str] = []
        for column in range(width + 1):
            foreground = (
                geometry[row][column]
                if row < len(geometry) and column < width
                else " "
            )
            casts_shadow = (
                row > 0
                and column > 0
                and geometry[row - 1][column - 1] != " "
            )
            if foreground != " ":
                cells.append(f"[{color}]{foreground}[/]")
            elif casts_shadow:
                cells.append("[#263329]░[/]")
            else:
                cells.append(" ")
        rendered.append("".join(cells).rstrip())
    return "\n".join(rendered)


LOGO = render_logo("#efb84b")
LOGO_SCAN_FRAMES = tuple(
    render_logo(color)
    for color in ("#707d72", "#8faf76", "#efb84b", "#8faf76")
)
STANDARD_HEIGHTS = (2160, 1440, 1080, 720, 480, 360, 240, 144)
PROGRESS_PREFIX = "YTGRAB_PROGRESS:"
POSTPROCESS_PREFIX = "YTGRAB_POST:"
FILE_PREFIX = "YTGRAB_FILE:"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
AUTH_ERROR_MARKERS = (
    "sign in to confirm you’re not a bot",
    "sign in to confirm you're not a bot",
    "use --cookies-from-browser",
)
BROWSER_LABELS = {
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "safari": "Safari",
    "brave": "Brave",
    "edge": "Microsoft Edge",
}

YTGRAB_DARK_THEME = Theme(
    name="ytgrab-dark",
    primary="#efb84b",
    secondary="#8faf76",
    accent="#efb84b",
    warning="#e8aa5b",
    error="#e57066",
    success="#8faf76",
    foreground="#e5eadf",
    background="#0c100d",
    surface="#141a16",
    panel="#202820",
    dark=True,
    variables={
        "border": "#efb84b",
        "border-blurred": "#344038",
        "input-cursor-background": "#efb84b",
        "input-cursor-foreground": "#0c100d",
        "input-selection-background": "#202820",
        "button-color-foreground": "#0c100d",
    },
)


@dataclass(frozen=True)
class ProgressSnapshot:
    percent: float | None
    speed: str
    eta: str


def parse_progress_line(line: str) -> ProgressSnapshot | None:
    """Parse the stable machine-readable prefix emitted by yt-dlp."""
    # yt-dlp may clear the current terminal line before writing progress even
    # when colors are disabled.  Ignore those control sequences so the marker
    # remains detectable if its output behavior changes or --newline is lost.
    line = ANSI_ESCAPE_RE.sub("", line).lstrip()
    if not line.startswith(PROGRESS_PREFIX):
        return None
    payload = line.removeprefix(PROGRESS_PREFIX)
    percent_text, _, remainder = payload.partition("|")
    speed, _, eta = remainder.partition("|")
    match = re.search(r"[\d.]+", percent_text)
    percent = float(match.group()) if match else None
    return ProgressSnapshot(percent=percent, speed=speed.strip(), eta=eta.strip())


def browser_cookie_args(browser: str | None) -> list[str]:
    """Return yt-dlp authentication arguments without persisting cookies."""
    return ["--cookies-from-browser", browser] if browser else []


def build_download_command(
    url: str,
    quality: str,
    output_dir: Path,
    browser: str | None = None,
    mode: str = "best",
) -> list[str]:
    """Build a yt-dlp command without invoking a shell."""
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--no-simulate",
        "--newline",
        "--no-colors",
        # --print implies quiet mode in yt-dlp. Re-enable progress explicitly;
        # otherwise the after_move filename print suppresses every update.
        "--progress",
        "--progress-delta",
        "0.25",
        "--progress-template",
        f"download:{PROGRESS_PREFIX}%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--progress-template",
        f"postprocess:{POSTPROCESS_PREFIX}%(progress.status)s",
        "--print",
        f"after_move:{FILE_PREFIX}%(filepath)s",
        "--continue",
        "--no-overwrites",
        "--trim-filenames",
        "180",
        "-P",
        str(output_dir),
    ]
    command.extend(browser_cookie_args(browser))

    if quality == "audio":
        command.extend(
            [
                "-f",
                "bestaudio/best",
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "-o",
                "%(title)s [%(id)s] [audio].%(ext)s",
            ]
        )
    else:
        try:
            height = int(quality)
        except ValueError:
            height = 1080
        if mode == "mac":
            format_selector = "/".join(
                [
                    f"bv*[height={height}][vcodec^=avc][ext=mp4]+ba[acodec^=mp4a][ext=m4a]",
                    f"b[height={height}][vcodec^=avc][acodec^=mp4a][ext=mp4]",
                    f"bv*[height={height}]+ba",
                    f"b[height={height}]",
                    f"bv*[height<={height}][vcodec^=avc][ext=mp4]+ba[acodec^=mp4a][ext=m4a]",
                    f"b[height<={height}][vcodec^=avc][acodec^=mp4a][ext=mp4]",
                    f"bv*[height<={height}]+ba",
                    f"b[height<={height}]",
                ]
            )
        else:
            format_selector = "/".join(
                [
                    f"bv*[height={height}][ext=mp4]+ba[ext=m4a]",
                    f"bv*[height={height}]+ba",
                    f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]",
                    f"bv*[height<={height}]+ba",
                    f"b[height<={height}]",
                ]
            )
        command.extend(
            [
                "-f",
                format_selector,
                "--merge-output-format",
                "mp4",
                "-o",
                "%(title)s [%(id)s] [%(height)sp].%(ext)s",
            ]
        )

    command.append(url)
    return command


def build_inspect_command(url: str, browser: str | None = None) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--socket-timeout",
        "15",
    ]
    command.extend(browser_cookie_args(browser))
    command.append(url)
    return command


def is_authentication_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in AUTH_ERROR_MARKERS)


def available_browsers() -> list[str]:
    """Return browsers yt-dlp can read and that appear installed locally."""
    system = platform.system()
    if system == "Darwin":
        applications = {
            "chrome": "Google Chrome.app",
            "firefox": "Firefox.app",
            "safari": "Safari.app",
            "brave": "Brave Browser.app",
            "edge": "Microsoft Edge.app",
        }
        roots = (Path("/Applications"), Path.home() / "Applications")
        return [
            browser
            for browser, bundle in applications.items()
            if any((root / bundle).exists() for root in roots)
        ]
    if system == "Windows":
        roots = [
            Path(value)
            for name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)")
            if (value := os.environ.get(name))
        ]
        executables = {
            "chrome": Path("Google/Chrome/Application/chrome.exe"),
            "firefox": Path("Mozilla Firefox/firefox.exe"),
            "brave": Path("BraveSoftware/Brave-Browser/Application/brave.exe"),
            "edge": Path("Microsoft/Edge/Application/msedge.exe"),
        }
        return [
            browser
            for browser, executable in executables.items()
            if any((root / executable).exists() for root in roots)
        ]
    executables = {
        "chrome": ("google-chrome", "google-chrome-stable", "chromium"),
        "firefox": ("firefox",),
        "brave": ("brave-browser", "brave"),
        "edge": ("microsoft-edge", "microsoft-edge-stable"),
    }
    return [
        browser
        for browser, commands in executables.items()
        if any(shutil.which(command) for command in commands)
    ]


def settings_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    elif system == "Windows" and os.environ.get("APPDATA"):
        root = Path(os.environ["APPDATA"])
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "ytgrab" / "settings.json"


def load_cookie_browser(path: Path | None = None) -> str | None:
    try:
        data = json.loads((path or settings_path()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    browser = data.get("cookie_browser")
    return browser if browser in BROWSER_LABELS else None


def save_cookie_browser(browser: str | None, path: Path | None = None) -> None:
    destination = path or settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"cookie_browser": browser}, indent=2) + "\n",
        encoding="utf-8",
    )


def is_youtube_url(value: str) -> bool:
    """Return True for a normal HTTP(S) YouTube URL."""
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com"


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "—"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def quality_options(formats: list[dict], mode: str = "best") -> list[Option]:
    """Build a compact list of available video heights plus audio."""
    heights = {item.get("height") for item in formats if item.get("height")}
    available = [height for height in STANDARD_HEIGHTS if height in heights]
    if not available:
        available = sorted(heights, reverse=True)[:8]

    options = [
        Option(f"▶  {height}p  ·  video + audio", id=str(height))
        for height in available
    ]
    options.append(Option("♫  audio only  ·  mp3", id="audio"))
    return options


def mac_conversion_codec(quality: str) -> str:
    try:
        height = int(quality)
    except ValueError:
        height = 1080
    return "hevc" if height > 1080 else "h264"


def conversion_encoder(codec: str, system: str | None = None) -> str:
    """Choose an FFmpeg encoder that exists on the current platform."""
    if (system or platform.system()) == "Darwin":
        return f"{codec}_videotoolbox"
    return "libx265" if codec == "hevc" else "libx264"


def media_is_mac_compatible(video_codec: str, audio_codec: str | None) -> bool:
    return video_codec in {"h264", "hevc"} and audio_codec in {None, "aac"}


def format_eta(seconds: float) -> str:
    seconds = max(0, round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def terminate_process(process: asyncio.subprocess.Process) -> None:
    """Stop a child process group on POSIX and the child itself on Windows."""
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass


def process_group_options() -> dict[str, int | bool]:
    """Return portable subprocess options for independently stoppable jobs."""
    if os.name == "posix":
        return {"start_new_session": True}
    return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}


class YtgrabApp(App[None]):
    """YTGRAB — a focused local YouTube transfer utility."""

    CSS_PATH = "styles.tcss"
    TITLE = "YTGRAB"
    SUB_TITLE = "youtube downloader"

    BINDINGS = [
        ("ctrl+q", "quit", "quit"),
        ("ctrl+l", "focus_url", "link"),
        ("ctrl+r", "inspect", "inspect"),
        ("ctrl+x", "cancel_download", "cancel"),
        ("escape", "back_to_source", "back"),
    ]

    logo_timer: Timer
    logo_frame = 0
    selected_quality = "best"
    download_mode = "mac"
    current_formats: list[dict]
    inspected_url: str | None = None
    download_process: asyncio.subprocess.Process | None = None
    download_cancel_requested = False
    is_downloading = False
    downloaded_file: Path | None = None
    cookie_browser: str | None = None

    def compose(self) -> ComposeResult:
        self.cookie_browser = load_cookie_browser()
        detected = available_browsers()
        if self.cookie_browser and self.cookie_browser not in detected:
            detected.insert(0, self.cookie_browser)
        browser_options = [("automatic · no browser cookies", "none")]
        browser_options.extend((BROWSER_LABELS[item], item) for item in detected)

        with VerticalScroll(id="page"):
            with Horizontal(id="hero"):
                yield Static(LOGO, id="logo", markup=True)
                with Vertical(id="hero-copy"):
                    yield Static("YTGRAB  /  LOCAL TRANSFER", id="tagline")
                    yield Static(
                        "signal in  ·  media out  ·  nothing uploaded",
                        id="services",
                    )
                yield Static("SYSTEM  READY\nyt-dlp / ffmpeg", id="system-badge")

            with Vertical(id="source-window"):
                with Vertical(id="transfer-form"):
                    yield Label("01  SOURCE", id="url-label")
                    with Horizontal(id="url-bar"):
                        yield Input(
                            placeholder="https://youtube.com/watch?v=…",
                            id="url",
                        )
                        yield Button("inspect", id="inspect", disabled=True)

                    with Horizontal(id="output-row"):
                        yield Static("destination", id="output-label")
                        yield Input("~/Downloads", id="output-path")

                    with Horizontal(id="auth-row"):
                        yield Static("youtube auth", id="auth-label")
                        yield Select(
                            browser_options,
                            value=self.cookie_browser or "none",
                            allow_blank=False,
                            id="auth-browser",
                        )

                    yield Static(
                        "↵ inspect  ·  ^l edit link  ·  ^q quit",
                        id="status-line",
                    )

            with Vertical(id="result-window"):
                with Horizontal(id="result"):
                    with Vertical(id="format-panel"):
                        yield Label("02  FORMAT", classes="micro-label section-label")
                        yield Select(
                            [
                                ("◇  Compatible MP4  ·  H.264 / HEVC", "mac"),
                                ("◆  Best quality  ·  AV1 / VP9 allowed", "best"),
                            ],
                            value="mac",
                            allow_blank=False,
                            id="quality-mode",
                        )
                        yield OptionList(id="quality-list", compact=True)
                        with Vertical(id="progress-panel"):
                            yield Static("PREPARING", id="progress-stage")
                            yield ProgressBar(
                                total=100,
                                show_percentage=False,
                                show_eta=False,
                                id="progress-bar",
                            )
                            yield Static("0%", id="progress-percent")
                            yield Static("speed —  ·  time left —", id="progress-stats")
                            yield Static("", id="progress-file", markup=False)
                        yield Button("download selected", id="download", disabled=True)
                    with Vertical(id="video-info"):
                        yield Label("SOURCE  /  YOUTUBE", classes="micro-label")
                        yield Static("", id="video-title", markup=False)
                        yield Static("", id="video-meta", markup=False)

                yield Static(
                    "↑↓ choose  ·  ↵ download  ·  esc back",
                    id="result-hints",
                )

    def on_mount(self) -> None:
        self.register_theme(YTGRAB_DARK_THEME)
        self.theme = YTGRAB_DARK_THEME.name
        self.query_one("#result-window", Vertical).display = False
        self.query_one("#progress-panel", Vertical).display = False
        self.set_auth_row_visible(False)
        self.update_auth_badge()
        self.logo_timer = self.set_interval(0.18, self.animate_logo, pause=True)
        self.inspected_url = None
        self.download_process = None
        self.download_cancel_requested = False
        self.is_downloading = False
        self.downloaded_file = None
        self.current_formats = []
        self.update_layout_classes(self.size.width)
        self.query_one("#url", Input).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.update_layout_classes(event.size.width)

    def update_layout_classes(self, width: int) -> None:
        self.screen.set_class(width <= 96, "narrow")
        self.screen.set_class(width <= 64, "compact")

    def animate_logo(self) -> None:
        self.logo_frame = (self.logo_frame + 1) % len(LOGO_SCAN_FRAMES)
        self.query_one("#logo", Static).update(LOGO_SCAN_FRAMES[self.logo_frame])

    def set_logo_scanning(self, scanning: bool) -> None:
        logo = self.query_one("#logo", Static)
        if scanning:
            self.logo_timer.resume()
        else:
            self.logo_timer.pause()
            logo.update(LOGO)

    @on(Input.Changed, "#url")
    def url_changed(self, event: Input.Changed) -> None:
        if self.is_downloading:
            return
        valid = is_youtube_url(event.value)
        self.inspected_url = None
        self.query_one("#inspect", Button).disabled = not valid
        self.query_one("#download", Button).disabled = True
        self.show_source_window(focus=False)

        status = "link changed  ·  ↵ inspect" if event.value.strip() else (
            "↵ inspect  ·  ^l edit link  ·  ^q quit"
        )
        self.query_one("#status-line", Static).update(status)

    @on(Input.Submitted, "#url")
    def url_submitted(self, event: Input.Submitted) -> None:
        if is_youtube_url(event.value):
            self.action_inspect()
        elif event.value.strip():
            self.notify("Enter a full youtube.com or youtu.be URL", severity="warning")

    def action_focus_url(self) -> None:
        if not self.is_downloading:
            self.show_source_window()

    def action_back_to_source(self) -> None:
        if self.is_downloading:
            self.notify("Cancel the active download before going back", severity="warning")
            return
        self.show_source_window()

    def show_source_window(self, *, focus: bool = True) -> None:
        self.query_one("#source-window", Vertical).display = True
        self.query_one("#result-window", Vertical).display = False
        if focus:
            self.query_one("#url", Input).focus()

    def show_result_window(self) -> None:
        self.query_one("#source-window", Vertical).display = False
        self.query_one("#result-window", Vertical).display = True

    def set_auth_row_visible(self, visible: bool) -> None:
        self.query_one("#auth-row", Horizontal).display = visible
        self.screen.set_class(visible, "auth-required")

    def update_auth_badge(self) -> None:
        auth = self.cookie_browser or "anonymous"
        self.query_one("#system-badge", Static).update(f"SYSTEM  READY\nauth / {auth}")

    def request_browser_auth(self, url: str) -> None:
        self.inspected_url = None
        self.show_source_window(focus=False)
        self.set_loading(False)
        self.set_auth_row_visible(True)
        self.query_one("#status-line", Static).update(
            "youtube verification  ·  choose your signed-in browser"
        )
        self.query_one("#auth-browser", Select).focus()
        self.notify("Choose a browser where you are signed in to YouTube", severity="warning")

    @on(Select.Changed, "#auth-browser")
    def auth_browser_changed(self, event: Select.Changed) -> None:
        browser = None if event.value == "none" else str(event.value)
        if browser == self.cookie_browser:
            return
        self.cookie_browser = browser
        try:
            save_cookie_browser(browser)
        except OSError as error:
            self.notify(f"Could not save authentication setting: {error}", severity="warning")
        self.update_auth_badge()
        url = self.query_one("#url", Input).value.strip()
        if browser and is_youtube_url(url):
            self.query_one("#status-line", Static).update(
                f"retrying with {BROWSER_LABELS[browser].lower()} cookies"
            )
            self.inspect_video(url)

    def action_inspect(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        if not is_youtube_url(url):
            self.notify("Paste a valid YouTube URL", severity="warning")
            return
        self.inspect_video(url)

    @on(Button.Pressed, "#inspect")
    def inspect_pressed(self) -> None:
        self.action_inspect()

    @on(Input.Changed, "#output-path")
    def output_changed(self, event: Input.Changed) -> None:
        if not event.value.strip():
            self.query_one("#status-line", Static).update("choose an output folder")

    @on(OptionList.OptionHighlighted, "#quality-list")
    def quality_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id is not None:
            self.selected_quality = event.option.id

    @on(Select.Changed, "#quality-mode")
    def quality_mode_changed(self, event: Select.Changed) -> None:
        mode = str(event.value)
        if mode == self.download_mode:
            return
        self.download_mode = mode
        if self.current_formats:
            self.update_quality_options()

    def update_quality_options(self) -> None:
        options = quality_options(self.current_formats, self.download_mode)
        quality_list = self.query_one("#quality-list", OptionList)
        quality_list.set_options(options)
        quality_list.highlighted = 0
        self.selected_quality = options[0].id or "audio"
        label = "Compatible MP4" if self.download_mode == "mac" else "Best quality"
        self.query_one("#status-line", Static).update(f"{label}  ·  choose quality")
        quality_list.focus()

    @on(OptionList.OptionSelected, "#quality-list")
    def quality_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is not None:
            self.selected_quality = event.option.id
        self.query_one("#download", Button).focus()

    @on(Button.Pressed, "#download")
    def download_pressed(self) -> None:
        if self.is_downloading:
            self.request_download_cancel()
        else:
            self.start_download()

    def action_cancel_download(self) -> None:
        if self.is_downloading:
            self.request_download_cancel()

    def start_download(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        if self.inspected_url != url:
            self.notify("Inspect the current link first", severity="warning")
            return

        raw_output = self.query_one("#output-path", Input).value.strip()
        if not raw_output:
            self.notify("Choose an output folder", severity="warning")
            return

        output_dir = Path(raw_output).expanduser().resolve()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.notify(f"Could not create folder: {error}", severity="error")
            return
        if not output_dir.is_dir():
            self.notify("The output path is not a folder", severity="error")
            return

        self.download_video(url, self.selected_quality, output_dir)

    def prepare_download_ui(self, quality: str) -> None:
        self.is_downloading = True
        self.download_cancel_requested = False
        self.downloaded_file = None
        self.query_one("#quality-mode", Select).display = False
        self.query_one("#quality-list", OptionList).display = False
        self.query_one("#progress-panel", Vertical).display = True
        self.query_one("#progress-stage", Static).update(
            "DOWNLOADING AUDIO" if quality == "audio" else f"DOWNLOADING {quality}p"
        )
        self.query_one("#progress-bar", ProgressBar).update(total=100, progress=0)
        self.query_one("#progress-percent", Static).update("0%")
        self.query_one("#progress-stats", Static).update("speed —  ·  time left —")
        self.query_one("#progress-file", Static).update("")
        self.query_one("#download", Button).label = "cancel"
        self.query_one("#download", Button).disabled = False
        self.query_one("#url", Input).disabled = True
        self.query_one("#output-path", Input).disabled = True
        self.query_one("#inspect", Button).disabled = True
        self.query_one("#status-line", Static).update("transfer started  ·  ^x cancel")
        self.query_one("#result-hints", Static).update("^x cancel  ·  partial files can resume later")
        self.set_logo_scanning(True)

    def finish_download_ui(self) -> None:
        self.is_downloading = False
        self.download_process = None
        self.query_one("#url", Input).disabled = False
        self.query_one("#output-path", Input).disabled = False
        current_url = self.query_one("#url", Input).value
        self.query_one("#inspect", Button).disabled = not is_youtube_url(current_url)
        self.set_logo_scanning(False)

    def finish_download_success(self) -> None:
        self.finish_download_ui()
        self.query_one("#progress-bar", ProgressBar).update(total=100, progress=100)
        self.query_one("#progress-percent", Static).update("100%")
        self.query_one("#progress-stage", Static).update("DONE")
        filename = self.downloaded_file.name if self.downloaded_file else "file saved"
        self.query_one("#progress-file", Static).update(filename)
        self.query_one("#download", Button).label = "download again"
        self.query_one("#download", Button).disabled = False
        self.query_one("#status-line", Static).update(f"done  ·  {filename}")
        self.query_one("#result-hints", Static).update("↵ download again  ·  ^l new link  ·  ^q quit")
        self.notify("Download complete", severity="information")

    def finish_download_cancelled(self) -> None:
        self.finish_download_ui()
        self.query_one("#progress-panel", Vertical).display = False
        self.query_one("#quality-mode", Select).display = True
        self.query_one("#quality-list", OptionList).display = True
        self.query_one("#download", Button).label = "download selected"
        self.query_one("#download", Button).disabled = False
        self.query_one("#status-line", Static).update("download cancelled  ·  resume any time")
        self.query_one("#result-hints", Static).update("↑↓ choose  ·  ↵ download  ·  esc back")
        self.query_one("#quality-list", OptionList).focus()

    def finish_download_error(self, message: str) -> None:
        self.finish_download_ui()
        self.query_one("#progress-stage", Static).update("ERROR")
        self.query_one("#progress-file", Static).update(message)
        self.query_one("#download", Button).label = "retry"
        self.query_one("#download", Button).disabled = False
        self.query_one("#status-line", Static).update("download failed  ·  ready to retry")
        self.notify("Download failed", severity="error")

    def request_download_cancel(self) -> None:
        process = self.download_process
        if process is None or process.returncode is not None:
            return
        self.download_cancel_requested = True
        self.query_one("#progress-stage", Static).update("STOPPING")
        self.query_one("#download", Button).disabled = True
        terminate_process(process)

    def update_download_progress(self, snapshot: ProgressSnapshot) -> None:
        if snapshot.percent is not None:
            percent = max(0.0, min(snapshot.percent, 100.0))
            self.query_one("#progress-bar", ProgressBar).update(total=100, progress=percent)
            self.query_one("#progress-percent", Static).update(f"{percent:.1f}%")
        speed = snapshot.speed if snapshot.speed not in {"", "N/A"} else "—"
        eta = snapshot.eta if snapshot.eta not in {"", "N/A"} else "—"
        self.query_one("#progress-stats", Static).update(f"speed {speed}  ·  time left {eta}")

    async def probe_downloaded_media(
        self, path: Path
    ) -> tuple[str, str | None, float] | None:
        ffprobe = shutil.which("ffprobe")
        if ffprobe is None:
            return None
        process = await asyncio.create_subprocess_exec(
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name:format=duration",
            "-of",
            "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return None
        try:
            data = json.loads(stdout)
            streams = data.get("streams") or []
            video_codec = next(
                item["codec_name"] for item in streams if item.get("codec_type") == "video"
            )
            audio_codec = next(
                (item.get("codec_name") for item in streams if item.get("codec_type") == "audio"),
                None,
            )
            duration = float((data.get("format") or {}).get("duration") or 0)
        except (KeyError, TypeError, ValueError, StopIteration, json.JSONDecodeError):
            return None
        return video_codec, audio_codec, duration

    async def convert_download_for_mac(self, path: Path, quality: str) -> str | None:
        """Convert incompatible media in-place; return an error message on failure."""
        media = await self.probe_downloaded_media(path)
        if media is None:
            return "ffprobe could not inspect the downloaded file"
        video_codec, audio_codec, duration = media
        if media_is_mac_compatible(video_codec, audio_codec):
            return None

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            return "ffmpeg is required for Mac-compatible conversion"

        target_codec = mac_conversion_codec(quality)
        encoder = conversion_encoder(target_codec)
        target_label = "HEVC" if target_codec == "hevc" else "H.264"
        final_path = path.with_suffix(".mp4")
        temporary_path = path.with_name(f".{path.stem}.ytgrab-converting.mp4")
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as error:
            return f"could not prepare conversion: {error}"

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-map_metadata",
            "0",
            "-c:v",
            encoder,
        ]
        if platform.system() == "Darwin":
            command.extend(["-allow_sw", "1", "-q:v", "65"])
        else:
            command.extend(
                ["-preset", "medium", "-crf", "24" if target_codec == "hevc" else "20"]
            )
        if target_codec == "hevc":
            command.extend(["-tag:v", "hvc1"])
        else:
            command.extend(["-profile:v", "high", "-pix_fmt", "yuv420p"])
        command.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "256k",
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-nostats",
                str(temporary_path),
            ]
        )

        self.query_one("#progress-stage", Static).update(f"CONVERTING TO {target_label}")
        self.query_one("#progress-bar", ProgressBar).update(total=100, progress=0)
        self.query_one("#progress-percent", Static).update("0%")
        self.query_one("#progress-file", Static).update(path.name)
        started_at = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **process_group_options(),
            )
        except OSError as error:
            return f"could not start ffmpeg: {error}"
        self.download_process = process

        assert process.stdout is not None
        last_output = "ffmpeg conversion failed"
        while line_bytes := await process.stdout.readline():
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if line:
                last_output = line
            if not line.startswith(("out_time_us=", "out_time_ms=")) or duration <= 0:
                continue
            try:
                current_seconds = int(line.partition("=")[2]) / 1_000_000
            except ValueError:
                continue
            percent = max(0.0, min(current_seconds / duration * 100, 100.0))
            elapsed = time.monotonic() - started_at
            remaining = elapsed * (100 - percent) / percent if percent > 0 else 0
            self.query_one("#progress-bar", ProgressBar).update(total=100, progress=percent)
            self.query_one("#progress-percent", Static).update(f"{percent:.1f}%")
            eta = format_eta(remaining) if percent > 0 else "—"
            self.query_one("#progress-stats", Static).update(
                f"hardware encode  ·  time left {eta}"
            )

        return_code = await process.wait()
        self.download_process = None
        if self.download_cancel_requested:
            temporary_path.unlink(missing_ok=True)
            return None
        if return_code != 0:
            temporary_path.unlink(missing_ok=True)
            return last_output
        try:
            os.replace(temporary_path, final_path)
            if final_path != path:
                path.unlink(missing_ok=True)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            return f"could not save converted file: {error}"
        self.downloaded_file = final_path
        return None

    @work(group="download", exclusive=True)
    async def download_video(self, url: str, quality: str, output_dir: Path) -> None:
        self.prepare_download_ui(quality)
        command = build_download_command(
            url, quality, output_dir, self.cookie_browser, self.download_mode
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **process_group_options(),
            )
        except OSError as error:
            self.finish_download_error(str(error))
            return
        self.download_process = process
        last_error = "yt-dlp could not download the file"

        assert process.stdout is not None
        while line_bytes := await process.stdout.readline():
            line = line_bytes.decode("utf-8", errors="replace").strip()
            snapshot = parse_progress_line(line)
            if snapshot is not None:
                self.update_download_progress(snapshot)
            elif line.startswith(POSTPROCESS_PREFIX):
                self.query_one("#progress-stage", Static).update("PROCESSING WITH FFMPEG")
            elif line.startswith(FILE_PREFIX):
                self.downloaded_file = Path(line.removeprefix(FILE_PREFIX))
            elif "[Merger]" in line:
                self.query_one("#progress-stage", Static).update("MERGING VIDEO + AUDIO")
            elif "[ExtractAudio]" in line:
                self.query_one("#progress-stage", Static).update("CREATING MP3")
            elif line.startswith("ERROR:"):
                last_error = line.removeprefix("ERROR:").strip()

        return_code = await process.wait()
        if self.download_cancel_requested:
            self.finish_download_cancelled()
        elif return_code == 0:
            conversion_error = None
            if (
                self.download_mode == "mac"
                and quality != "audio"
                and self.downloaded_file is not None
            ):
                conversion_error = await self.convert_download_for_mac(
                    self.downloaded_file, quality
                )
            if self.download_cancel_requested:
                self.finish_download_cancelled()
            elif conversion_error:
                self.finish_download_error(conversion_error)
            else:
                self.finish_download_success()
        elif is_authentication_error(last_error):
            self.finish_download_ui()
            self.query_one("#progress-panel", Vertical).display = False
            self.query_one("#quality-list", OptionList).display = True
            self.query_one("#download", Button).label = "download selected"
            self.request_browser_auth(url)
        else:
            self.finish_download_error(last_error)

    def set_loading(self, loading: bool) -> None:
        inspect = self.query_one("#inspect", Button)
        current_url = self.query_one("#url", Input).value
        inspect.disabled = loading or not is_youtube_url(current_url)
        inspect.label = "···" if loading else "inspect"
        self.set_logo_scanning(loading)

    @work(group="inspect", exclusive=True)
    async def inspect_video(self, url: str) -> None:
        self.set_loading(True)
        self.query_one("#status-line", Static).update("inspecting link  ·  yt-dlp")

        process = await asyncio.create_subprocess_exec(
            *build_inspect_command(url, self.cookie_browser),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=35)
        except TimeoutError:
            process.kill()
            await process.wait()
            if self.query_one("#url", Input).value.strip() == url:
                self.show_error("YouTube did not respond within 35 seconds")
            else:
                self.set_loading(False)
            return

        if self.query_one("#url", Input).value.strip() != url:
            self.set_loading(False)
            return

        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace").strip()
            if is_authentication_error(error_text):
                self.request_browser_auth(url)
                return
            detail = error_text.splitlines()
            self.show_error(detail[-1] if detail else "yt-dlp could not inspect the link")
            return

        try:
            info = json.loads(stdout)
        except json.JSONDecodeError:
            self.show_error("yt-dlp returned an unexpected response")
            return

        formats = info.get("formats") or []
        self.current_formats = formats
        title = str(info.get("title") or "Untitled")
        uploader = str(info.get("uploader") or info.get("channel") or "Unknown creator")
        duration = format_duration(info.get("duration"))

        quality_list = self.query_one("#quality-list", OptionList)
        self.query_one("#quality-mode", Select).display = True
        self.update_quality_options()

        self.query_one("#video-title", Static).update(title)
        self.query_one("#video-meta", Static).update(f"▶  YouTube  ·  {duration}  ·  {uploader}")
        self.show_result_window()
        self.query_one("#download", Button).disabled = False
        self.inspected_url = url
        self.query_one("#status-line", Static).update("found  ·  choose quality")
        self.set_auth_row_visible(False)
        self.set_loading(False)
        quality_list.focus()

    def show_error(self, message: str) -> None:
        self.inspected_url = None
        self.show_source_window(focus=False)
        self.query_one("#download", Button).disabled = True
        self.query_one("#status-line", Static).update(f"error  ·  {message}")
        self.set_loading(False)
        self.notify("Inspection failed", severity="error")

    def on_unmount(self) -> None:
        process = self.download_process
        if process is not None:
            terminate_process(process)


def main() -> None:
    YtgrabApp().run()


if __name__ == "__main__":
    main()
