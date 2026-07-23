"""Generate Textual SVG snapshots for visual review."""

import asyncio
from pathlib import Path

from textual.containers import Horizontal
from textual.widgets import Button, OptionList, ProgressBar, Static
from textual.widgets.option_list import Option

from ytdl_tui.app import YtgrabApp


OUTPUT = Path("artifacts")
DEMO_URL = "https://youtu.be/abcdefghijk"


async def render() -> None:
    OUTPUT.mkdir(exist_ok=True)

    start_app = YtgrabApp()
    async with start_app.run_test(size=(140, 42), notifications=True) as pilot:
        await pilot.pause()
        start_app.save_screenshot("ytgrab-start.svg", path=str(OUTPUT))
        start_app.query_one("#url").value = DEMO_URL
        await pilot.pause()
        start_app.request_browser_auth(DEMO_URL)
        await pilot.pause()
        start_app.save_screenshot("ytgrab-auth.svg", path=str(OUTPUT))
        start_app.set_auth_row_visible(False)
        start_app.notify(
            "Could not inspect this YouTube link",
            title="INSPECTION FAILED",
            severity="error",
            timeout=10,
        )
        start_app.notify(
            "Check the link and try again",
            title="LINK WARNING",
            severity="warning",
            timeout=10,
        )
        start_app.notify(
            "Video saved to Downloads",
            title="DOWNLOAD COMPLETE",
            severity="information",
            timeout=10,
        )
        await pilot.pause(0.2)
        start_app.save_screenshot("ytgrab-notifications.svg", path=str(OUTPUT))

    result_app = YtgrabApp()
    async with result_app.run_test(size=(140, 42)) as pilot:
        result_app.query_one("#video-title", Static).update(
            "Example video — a local workflow demo"
        )
        result_app.query_one("#video-meta", Static).update(
            "▶  YouTube  ·  3:33  ·  Example Channel"
        )
        result_app.query_one("#quality-list", OptionList).set_options(
            [
                Option("▶  2160p  ·  video + audio", id="2160"),
                Option("▶  1440p  ·  video + audio", id="1440"),
                Option("▶  1080p  ·  video + audio", id="1080"),
                Option("▶  720p   ·  video + audio", id="720"),
                Option("♫  audio only  ·  mp3", id="audio"),
            ]
        )
        result_app.show_result_window()
        result_app.query_one("#download", Button).disabled = False
        result_app.query_one("#quality-list", OptionList).highlighted = 0
        result_app.query_one("#quality-list", OptionList).focus()
        await pilot.pause()
        result_app.save_screenshot("ytgrab-result.svg", path=str(OUTPUT))

        result_app.query_one("#quality-list", OptionList).display = False
        result_app.query_one("#progress-panel").display = True
        result_app.query_one("#progress-stage", Static).update("DOWNLOADING 2160p")
        result_app.query_one("#progress-bar", ProgressBar).update(total=100, progress=42.5)
        result_app.query_one("#progress-percent", Static).update("42.5%")
        result_app.query_one("#progress-stats", Static).update(
            "speed 8.2MiB/s  ·  time left 00:13"
        )
        result_app.query_one("#download", Button).label = "cancel"
        await pilot.pause()
        result_app.save_screenshot("ytgrab-progress.svg", path=str(OUTPUT))

        result_app.query_one("#progress-stage", Static).update("CONVERTING TO HEVC")
        result_app.query_one("#progress-bar", ProgressBar).update(total=100, progress=68.2)
        result_app.query_one("#progress-percent", Static).update("68.2%")
        result_app.query_one("#progress-stats", Static).update(
            "hardware encode  ·  time left 01:24"
        )
        await pilot.pause()
        result_app.save_screenshot("ytgrab-converting.svg", path=str(OUTPUT))

    compact_app = YtgrabApp()
    async with compact_app.run_test(size=(60, 42)) as pilot:
        await pilot.pause()
        compact_app.save_screenshot("ytgrab-compact.svg", path=str(OUTPUT))
        compact_app.query_one("#url").value = DEMO_URL
        await pilot.pause()
        compact_app.request_browser_auth(DEMO_URL)
        await pilot.pause()
        compact_app.save_screenshot("ytgrab-compact-auth.svg", path=str(OUTPUT))
        compact_app.set_auth_row_visible(False)

        compact_app.query_one("#video-title", Static).update(
            "Example video — a local workflow demo"
        )
        compact_app.query_one("#video-meta", Static).update(
            "▶  YouTube  ·  3:33  ·  Example Channel"
        )
        compact_app.query_one("#quality-list", OptionList).set_options(
            [
                Option("▶  2160p  ·  video + audio", id="2160"),
                Option("▶  1080p  ·  video + audio", id="1080"),
                Option("▶  720p   ·  video + audio", id="720"),
                Option("♫  audio only  ·  mp3", id="audio"),
            ]
        )
        compact_app.query_one("#download", Button).disabled = False
        compact_app.query_one("#quality-list", OptionList).highlighted = 0
        compact_app.show_result_window()
        compact_app.query_one("#quality-list", OptionList).focus()
        await pilot.pause()
        compact_app.save_screenshot("ytgrab-compact-result.svg", path=str(OUTPUT))


if __name__ == "__main__":
    asyncio.run(render())
