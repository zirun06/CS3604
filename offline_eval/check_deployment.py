"""Verify deploy.sh separately from presentation, business and persistence checks."""

import argparse
import json
import re
from pathlib import Path
import shutil
import socket
import subprocess
from tempfile import mkdtemp
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

if __package__:
    from .deployment_process import launch
else:
    from deployment_process import launch


def probe(base, database):
    with urlopen(base + "/api/health", timeout=2) as response:
        health = json.load(response)
    if not isinstance(health, dict) or health.get("status") != "ok" or not database.is_file():
        return None
    with urlopen(base + "/", timeout=2) as response:
        if "text/html" not in response.headers.get("Content-Type", ""):
            return None
        html = response.read(300000).decode("utf-8")
    scripts = re.findall(r"""<script\b[^>]*\bsrc=["']([^"']+)["']""", html, re.I)
    for source in map(urlsplit, scripts):
        if source.netloc or source.scheme or not source.path.endswith((".js", ".mjs")):
            continue
        with urlopen(base + "/" + source.path.lstrip("/"), timeout=2) as response:
            if "javascript" in response.headers.get("Content-Type", "") and response.read(1):
                return source.path
    return None


def remove_temporary(directory, *, attempts=5):
    """Retry transient file sharing violations and report any residual path."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(directory)
            return {}
        except FileNotFoundError:
            if not directory.exists():
                return {}
            error = "Temporary directory was only partially removed"
        except OSError as exc:
            error = str(exc)
        if attempt + 1 < attempts:
            sleep(0.15 * (attempt + 1))
    return {"residual_path": str(directory), "directory_error": error}


def deployed(application, bash, *, timeout=600):
    """Run the deploy script with private process ownership and a file database."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    deadline = monotonic() + timeout
    base = f"http://127.0.0.1:{port}"
    directory = Path(mkdtemp(prefix="arc-deploy-check-")).resolve()
    database = directory / "app.db"
    log = directory / "deploy.log"
    result = {"status": "FAILED", "validation_type": "deployment"}
    cleanup = {}
    try:
        with log.open("wb") as stream:
            process = launch([bash, "./deploy.sh"], application,
                {"PORT": str(port), "DATABASE_URL": str(database)}, stream)
            try:
                while monotonic() < deadline and process.alive():
                    try:
                        asset = probe(base, database)
                        if asset:
                            result.update(status="GREEN", health=True, built_entry=True,
                                entry_asset=asset, isolated_file_database=True)
                            break
                    except (URLError, TimeoutError, ValueError):
                        pass
                    sleep(0.25)
                if result["status"] != "GREEN":
                    result["error"] = "Deployment exited or timed out before health, assets and database were ready"
            finally:
                try:
                    process.stop()
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    cleanup["process_error"] = str(error)
    except KeyboardInterrupt:
        result.update(status="INTERRUPTED", error="Deployment check interrupted")
    except (OSError, RuntimeError) as error:
        result.update(status="FAILED", error=str(error))
    finally:
        if log.is_file() and (result["status"] != "GREEN" or cleanup):
            try:
                result["output"] = log.read_text(encoding="utf-8", errors="replace")[-6000:]
            except OSError as error:
                result["log_error"] = str(error)
        try:
            cleanup.update(remove_temporary(directory))
        except KeyboardInterrupt:
            result.update(status="INTERRUPTED", error="Temporary directory cleanup interrupted")
            if directory.exists():
                cleanup["residual_path"] = str(directory)
        result["cleanup"] = {"status": "FAILED" if cleanup else "GREEN", **cleanup}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", type=Path, help="Disposable generated application")
    parser.add_argument("--bash", default="bash", help="Bash executable; use Git Bash on Windows")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    app = args.application.resolve()
    if args.timeout <= 0 or not (app / "deploy.sh").is_file():
        parser.error("Specify a generated app with deploy.sh and a positive timeout")
    try:
        result = deployed(app, args.bash, timeout=args.timeout)
    except (OSError, RuntimeError) as error:
        result = {"status": "FAILED", "validation_type": "deployment", "error": str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if result["status"] == "INTERRUPTED":
        return 130
    return 0 if result["status"] == "GREEN" and result.get("cleanup", {}).get("status") == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
