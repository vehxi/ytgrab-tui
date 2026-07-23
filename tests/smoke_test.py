import asyncio
from pathlib import Path

from ytdl_tui.app import (
    YtgrabApp,
    browser_cookie_args,
    build_download_command,
    build_inspect_command,
    conversion_encoder,
    is_authentication_error,
    is_youtube_url,
    load_cookie_browser,
    mac_conversion_codec,
    media_is_mac_compatible,
    parse_progress_line,
    quality_options,
    save_cookie_browser,
)
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, OptionList


async def smoke_test() -> None:
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not is_youtube_url("https://example.com/video")
    options = quality_options([{"height": 1080}, {"height": 720}, {"height": None}])
    assert [option.id for option in options] == ["1080", "720", "audio"]
    codec_formats = [
        {"height": 2160, "vcodec": "av01.0.12M.08"},
        {"height": 1440, "vcodec": "vp9"},
        {"height": 1080, "vcodec": "avc1.640028"},
        {"height": 720, "vcodec": "avc1.4d401f"},
    ]
    mac_options = quality_options(codec_formats, "mac")
    assert [option.id for option in mac_options] == [
        "2160",
        "1440",
        "1080",
        "720",
        "audio",
    ]
    assert mac_conversion_codec("1080") == "h264"
    assert mac_conversion_codec("2160") == "hevc"
    assert conversion_encoder("h264", "Darwin") == "h264_videotoolbox"
    assert conversion_encoder("hevc", "Linux") == "libx265"
    assert media_is_mac_compatible("h264", "aac")
    assert media_is_mac_compatible("hevc", "aac")
    assert not media_is_mac_compatible("vp9", "opus")

    snapshot = parse_progress_line("YTGRAB_PROGRESS: 42.5%| 8.2MiB/s|00:13")
    assert snapshot is not None
    assert snapshot.percent == 42.5
    assert snapshot.speed == "8.2MiB/s"
    assert snapshot.eta == "00:13"
    escaped_snapshot = parse_progress_line(
        "\r\x1b[KYTGRAB_PROGRESS: 17.0%| 1.0MiB/s|00:42"
    )
    assert escaped_snapshot is not None
    assert escaped_snapshot.percent == 17.0
    assert escaped_snapshot.eta == "00:42"
    assert parse_progress_line("[download] ordinary output") is None
    assert is_authentication_error("Sign in to confirm you’re not a bot")
    assert browser_cookie_args("chrome") == ["--cookies-from-browser", "chrome"]
    assert browser_cookie_args(None) == []

    settings_file = Path("/tmp/ytgrab-smoke-settings.json")
    save_cookie_browser("firefox", settings_file)
    assert load_cookie_browser(settings_file) == "firefox"

    video_command = build_download_command(
        "https://youtu.be/dQw4w9WgXcQ", "720", Path("/tmp/downloads")
    )
    assert video_command[-1] == "https://youtu.be/dQw4w9WgXcQ"
    assert "--progress" in video_command
    authenticated_command = build_download_command(
        "https://youtu.be/dQw4w9WgXcQ", "720", Path("/tmp/downloads"), "chrome"
    )
    cookie_index = authenticated_command.index("--cookies-from-browser")
    assert authenticated_command[cookie_index + 1] == "chrome"
    assert authenticated_command[-1] == "https://youtu.be/dQw4w9WgXcQ"
    inspect_command = build_inspect_command(
        "https://youtu.be/dQw4w9WgXcQ", "firefox"
    )
    assert inspect_command[-3:] == [
        "--cookies-from-browser",
        "firefox",
        "https://youtu.be/dQw4w9WgXcQ",
    ]
    selector = video_command[video_command.index("-f") + 1]
    assert selector.startswith("bv*[height=720][ext=mp4]+ba[ext=m4a]/")
    assert "bv*[height<=720]+ba" in selector
    mac_command = build_download_command(
        "https://youtu.be/dQw4w9WgXcQ",
        "1080",
        Path("/tmp/downloads"),
        mode="mac",
    )
    mac_selector = mac_command[mac_command.index("-f") + 1]
    assert "[vcodec^=avc]" in mac_selector
    assert "[acodec^=mp4a]" in mac_selector
    assert "bv*[height=1080]+ba" in mac_selector
    assert "-t" not in video_command
    assert "--merge-output-format" in video_command
    assert "mp4" in video_command
    assert "%(height)sp" in video_command[video_command.index("-o") + 1]
    audio_command = build_download_command(
        "https://youtu.be/dQw4w9WgXcQ", "audio", Path("/tmp/downloads")
    )
    assert "--audio-format" in audio_command
    assert "mp3" in audio_command
    assert "[audio]" in audio_command[audio_command.index("-o") + 1]

    app = YtgrabApp()
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.theme == "ytgrab-dark"
        assert app.current_theme.dark
        assert app.query_one("#source-window", Vertical).display
        assert not app.query_one("#result-window", Vertical).display
        assert not app.query_one("#auth-row", Horizontal).display
        assert not app.screen.has_class("narrow")
        app.set_logo_scanning(True)
        app.animate_logo()
        app.set_logo_scanning(False)
        url = app.query_one("#url", Input)
        inspect = app.query_one("#inspect", Button)
        assert inspect.disabled

        url.value = "https://youtu.be/dQw4w9WgXcQ"
        await pilot.pause()
        app.request_browser_auth(url.value)
        assert app.query_one("#auth-row", Horizontal).display
        assert app.screen.has_class("auth-required")
        app.set_auth_row_visible(False)
        app.prepare_download_ui("720")
        assert app.is_downloading
        assert app.query_one("#progress-panel", Vertical).display
        assert not app.query_one("#quality-list", OptionList).display
        app.finish_download_cancelled()
        assert not app.is_downloading
        assert app.query_one("#quality-list", OptionList).display
        app.show_result_window()
        assert not app.query_one("#source-window", Vertical).display
        assert app.query_one("#result-window", Vertical).display
        app.action_back_to_source()
        assert app.query_one("#source-window", Vertical).display
        assert not app.query_one("#result-window", Vertical).display
        url.value = "https://youtu.be/dQw4w9WgXcQ"
        await pilot.pause()
        assert not inspect.disabled

        download = app.query_one("#download", Button)
        download.disabled = False
        url.value = "https://youtube.com/watch?v=not-a-real-video"
        await pilot.pause()
        assert download.disabled

        url.value = "https://example.com/video"
        await pilot.pause()
        assert inspect.disabled

    compact_app = YtgrabApp()
    async with compact_app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        assert compact_app.screen.has_class("narrow")
        assert compact_app.screen.has_class("compact")


if __name__ == "__main__":
    asyncio.run(smoke_test())
