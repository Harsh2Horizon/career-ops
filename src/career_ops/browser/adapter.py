from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from career_ops.common.io import CareerOpsError


class BrowserDriver(Protocol):
    def open(self, config: dict) -> dict: ...
    def snapshot(self) -> dict: ...
    def fill(self, field_id: str, control: str, value: str) -> None: ...
    def next(self) -> dict: ...
    def submit(self) -> dict: ...
    def close(self) -> None: ...


def installed_playwright() -> str | None:
    configured = os.environ.get("CAREEROPS_PLAYWRIGHT_MODULE")
    candidates = [Path(configured)] if configured else []
    candidates += [
        Path("/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright"),
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright",
    ]
    return next((str(p) for p in candidates if (p / "package.json").is_file()), None)


def installed_chromium() -> str | None:
    configured = os.environ.get("CAREEROPS_CHROMIUM_EXECUTABLE")
    if configured:
        return configured
    caches = [Path.home() / "Library/Caches/ms-playwright", Path.home() / ".cache/ms-playwright"]
    for cache in caches:
        binaries = sorted(
            cache.glob("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell")
        )
        binaries += sorted(
            cache.glob("chromium-*/chrome-mac-*/Chromium.app/Contents/MacOS/Chromium")
        )
        binaries += sorted(cache.glob("chromium-*/chrome-linux*/chrome"))
        if binaries:
            return str(binaries[-1])
    return None


class PlaywrightDriver:
    """JSON-lines adapter to installed Node Playwright; no cookies or passwords on disk."""

    def __init__(self):
        node = shutil.which("node")
        if not node:
            raise CareerOpsError(
                "browser_dependency_missing",
                "Install Node.js and npm install playwright, then npx playwright install chromium",
            )
        environment = os.environ.copy()
        module = installed_playwright()
        if module:
            environment["CAREEROPS_PLAYWRIGHT_MODULE"] = module
        self.process = subprocess.Popen(
            [node, str(Path(__file__).with_name("playwright_driver.mjs"))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
        )

    def call(self, operation: str, **arguments):
        if self.process.poll() is not None:
            raise CareerOpsError(
                "browser_process_failed",
                "Playwright exited. Verify browser installation and launch permissions",
            )
        self.process.stdin.write(json.dumps({"operation": operation, **arguments}) + "\n")
        self.process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=45):
                self.process.kill()
                raise CareerOpsError(
                    "browser_timeout", "Browser operation exceeded its 45-second timeout"
                )
        line = self.process.stdout.readline()
        if not line:
            raise CareerOpsError(
                "browser_process_failed",
                "Browser could not launch; verify executable and operating-system sandbox permissions",
            )
        response = json.loads(line)
        if "error" in response:
            raise CareerOpsError("browser_operation_failed", response["error"])
        return response["result"]

    def open(self, config: dict) -> dict:
        config = {**config, "executablePath": installed_chromium()}
        return self.call("open", config=config)

    def snapshot(self) -> dict:
        return self.call("snapshot")

    def fill(self, field_id: str, control: str, value: str) -> None:
        self.call("fill", field_id=field_id, control=control, value=value)

    def next(self) -> dict:
        return self.call("next")

    def submit(self) -> dict:
        return self.call("submit")

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.call("close")
            finally:
                self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
