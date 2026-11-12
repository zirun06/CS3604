"""Verify deploy.sh separately from presentation, business and persistence checks."""

import argparse
import json
import re
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from infrastructure.utils.processes import start_process, stop_process


def deployed(application, bash, *, timeout=600):
    """Run the actual deploy script with a private file database and a loopback probe."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    deadline = monotonic() + timeout
    base = f"http://127.0.0.1:{port}"
    with TemporaryDirectory(prefix="arc-deploy-check-") as temporary:
        directory = Path(temporary)
        database = directory / "app.db"
        log = directory / "deploy.log"
        with log.open("wb") as stream:
            process = start_process([bash, "./deploy.sh"], cwd=application,
                env={"PORT": str(port), "DATABASE_URL": str(database)},
                stdout=stream, stderr=subprocess.STDOUT)
            try:
                while monotonic() < deadline and process.poll() is None:
                    try:
                        with urlopen(base + "/api/health", timeout=2) as response:
                            ready = json.load(response).get("status") == "ok"
                        with urlopen(base + "/", timeout=2) as response:
                            html = response.read(300000).decode("utf-8")
                            served = "text/html" in response.headers.get("Content-Type", "") and "<script" in html
                        scripts = re.findall(r"""<script\b[^>]*\bsrc=["']([^"']+)["']""", html, re.I)
                        local = [urlsplit(path).path for path in scripts if not urlsplit(path).netloc
                            and not urlsplit(path).scheme and urlsplit(path).path.endswith((".js", ".mjs"))]
                        if ready and served and local and database.is_file():
                            with urlopen(base + "/" + local[0].lstrip("/"), timeout=2) as response:
                                if "javascript" in response.headers.get("Content-Type", "") and response.read(1):
                                    return {"status": "GREEN", "validation_type": "deployment",
                                        "health": True, "built_entry": True, "entry_asset": local[0],
                                        "isolated_file_database": True}
                    except (URLError, TimeoutError, ValueError):
                        pass
                    sleep(0.25)
            finally:
                stop_process(process)
        return {"status": "FAILED", "validation_type": "deployment",
            "output": log.read_text(encoding="utf-8", errors="replace")[-6000:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", type=Path, help="Disposable generated application")
    parser.add_argument("--bash", default="bash", help="Bash executable; use Git Bash on Windows")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    app = args.application.resolve()
    if args.timeout <= 0 or not (app / "deploy.sh").is_file():
        parser.error("Specify a generated app with deploy.sh and a positive timeout")
    result = deployed(app, args.bash, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
