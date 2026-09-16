from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


DEFAULT_CHROME_BINARY = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEFAULT_RUNTIME_ROOT = Path("tmp_runtime/selenium")
SELENIUM_MANAGER_CACHE_ENV = "SE_CACHE_PATH"
SELENIUM_AVOID_STATS_ENV = "SE_AVOID_STATS"
RUNTIME_ROOT_ENV = "MARKETS_CHROME_RUNTIME_ROOT"


def build_chrome_driver(
    *,
    context: str,
    headless: bool = True,
    chrome_binary_env_vars: Iterable[str] = (),
    enable_performance_logging: bool = False,
) -> webdriver.Chrome:
    options = Options()
    chrome_binary = _resolve_chrome_binary(chrome_binary_env_vars)
    if chrome_binary is not None:
        options.binary_location = str(chrome_binary)

    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1600,1200")
    options.add_argument("--remote-debugging-pipe")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-breakpad")
    options.add_argument("--noerrdialogs")
    if enable_performance_logging:
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    failure_notes: list[str] = []
    last_exc: WebDriverException | None = None
    normalized_context = _normalize_context(context)

    for candidate_root in _runtime_root_candidates():
        try:
            runtime_root = _ensure_runtime_tree(candidate_root)
        except OSError as exc:
            failure_notes.append(f"root={candidate_root} unavailable ({exc})")
            continue

        attempt_plan = [("primary", _shared_manager_cache_root(runtime_root))]
        fresh_cache_root = _fresh_manager_cache_root(runtime_root, context, "clean-cache")
        attempt_plan.append(("clean-cache", fresh_cache_root))

        for attempt_label, cache_root in attempt_plan:
            run_root = _prepare_run_root(runtime_root, context, attempt_label)
            try:
                return _start_chrome_driver(
                    options=options,
                    runtime_root=runtime_root,
                    context=context,
                    run_root=run_root,
                    cache_root=cache_root,
                    attempt_label=attempt_label,
                )
            except WebDriverException as exc:
                last_exc = exc
                _cleanup_run_root(run_root)
                failure_notes.append(
                    f"root={runtime_root} attempt={attempt_label} "
                    f"cache={cache_root} failed ({type(exc).__name__}: {exc})"
                )
                if attempt_label == "primary" and _should_retry_with_clean_cache(exc):
                    continue
                break

    message = (
        f"Chrome driver startup failed for context '{normalized_context}'. "
        + " | ".join(failure_notes[-6:])
    )
    raise WebDriverException(message) from last_exc


def _start_chrome_driver(
    *,
    options: Options,
    runtime_root: Path,
    context: str,
    run_root: Path,
    cache_root: Path,
    attempt_label: str,
) -> webdriver.Chrome:
    user_data_dir = run_root / "user-data"
    data_path = run_root / "data-path"
    disk_cache_dir = run_root / "disk-cache"
    for path in (user_data_dir, data_path, disk_cache_dir):
        path.mkdir(parents=True, exist_ok=True)

    chrome_options = _clone_options(options)

    # Use a clean per-run profile so scheduled refreshes do not inherit stale
    # session locks, damaged state, or partial crash recovery from prior runs.
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_options.add_argument(f"--data-path={data_path}")
    chrome_options.add_argument(f"--disk-cache-dir={disk_cache_dir}")

    if options._caps.get("goog:loggingPrefs"):  # noqa: SLF001
        chrome_options.set_capability("goog:loggingPrefs", options._caps["goog:loggingPrefs"])  # noqa: SLF001

    service_log_path = _service_log_path(runtime_root, context, attempt_label)
    _configure_selenium_manager(cache_root)
    service = Service(log_output=str(service_log_path))
    driver = webdriver.Chrome(service=service, options=chrome_options)
    _attach_runtime_cleanup(driver, run_root)
    return driver


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured_root = os.getenv(RUNTIME_ROOT_ENV)
    if configured_root:
        candidates.append(Path(configured_root))

    if os.name == "nt":
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            candidates.append(Path(local_appdata) / "MarketsDashboard" / "selenium")

    candidates.append(_repo_root() / DEFAULT_RUNTIME_ROOT)
    candidates.append(Path(tempfile.gettempdir()) / "MarketsDashboard" / "selenium")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve(strict=False)).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
    return unique


def _ensure_runtime_tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    required_dirs = (
        root,
        root / "manager-cache",
        root / "manager-cache-runs",
        root / "profiles",
        root / "service-logs",
    )
    for directory in required_dirs:
        directory.mkdir(parents=True, exist_ok=True)
        _assert_directory_writable(directory)
    return root


def _assert_directory_writable(directory: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=directory, prefix="writable_", suffix=".tmp", delete=True) as handle:
        handle.write(b"ok")
        handle.flush()


def _configure_selenium_manager(cache_root: Path) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ[SELENIUM_MANAGER_CACHE_ENV] = str(cache_root)
    os.environ[SELENIUM_AVOID_STATS_ENV] = "true"


def _resolve_chrome_binary(env_vars: Iterable[str]) -> Path | None:
    for env_var in env_vars:
        candidate = os.getenv(env_var)
        if candidate and Path(candidate).exists():
            return Path(candidate)
    if DEFAULT_CHROME_BINARY.exists():
        return DEFAULT_CHROME_BINARY
    return None


def _prepare_run_root(runtime_root: Path, context: str, attempt_label: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_root = runtime_root / "profiles" / _normalize_context(context) / f"{timestamp}_{attempt_label}"
    run_root.mkdir(parents=True, exist_ok=False)
    return run_root


def _shared_manager_cache_root(runtime_root: Path) -> Path:
    cache_root = runtime_root / "manager-cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def _fresh_manager_cache_root(runtime_root: Path, context: str, attempt_label: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    cache_root = runtime_root / "manager-cache-runs" / _normalize_context(context) / f"{timestamp}_{attempt_label}"
    cache_root.mkdir(parents=True, exist_ok=False)
    return cache_root


def _service_log_path(runtime_root: Path, context: str, attempt_label: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_dir = runtime_root / "service-logs" / _normalize_context(context)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{timestamp}_{attempt_label}.log"


def _normalize_context(context: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in context)


def _clone_options(options: Options) -> Options:
    clone = Options()
    clone.binary_location = options.binary_location
    for argument in options.arguments:
        clone.add_argument(argument)
    for key, value in options.experimental_options.items():
        clone.add_experimental_option(key, value)
    for key, value in options._caps.items():  # noqa: SLF001
        if key == "browserName":
            continue
        clone.set_capability(key, value)
    return clone


def _attach_runtime_cleanup(driver: webdriver.Chrome, run_root: Path) -> None:
    original_quit = driver.quit
    cleaned = False

    def quit_with_cleanup() -> None:
        nonlocal cleaned
        try:
            original_quit()
        finally:
            if not cleaned:
                cleaned = True
                _cleanup_run_root(run_root)

    driver.quit = quit_with_cleanup  # type: ignore[method-assign]


def _cleanup_run_root(run_root: Path) -> None:
    shutil.rmtree(run_root, ignore_errors=True)


def _should_retry_with_clean_cache(exc: WebDriverException) -> bool:
    return _looks_like_profile_startup_issue(exc) or _looks_like_manager_cache_issue(exc)


def _looks_like_profile_startup_issue(exc: WebDriverException) -> bool:
    message = str(exc).lower()
    patterns = (
        "devtoolsactiveport",
        "session not created",
        "chrome failed to start",
        "user data directory is already in use",
        "access denied",
        "acceso denegado",
        "crashpad",
        "platform_channel",
    )
    return any(pattern in message for pattern in patterns)


def _looks_like_manager_cache_issue(exc: WebDriverException) -> bool:
    message = str(exc).lower()
    patterns = (
        "metadata cannot be written in cache",
        "selenium manager",
        "chromedriver.exe unexpectedly exited",
        "status code was: 1",
        "unable to obtain driver",
    )
    return any(pattern in message for pattern in patterns)
