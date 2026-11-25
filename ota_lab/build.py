"""Build each firmware revision with a separate ESP-IDF configuration."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).absolute().parents[1]
VERSIONS = {"baseline": "1.0.0", "healthy": "1.1.0", "faulty": "1.2.0"}
APP_IMAGE = "esp32_ota_lab.bin"


def build_all(output, port):
    idf = os.environ.get("IDF_PATH")
    if not idf:
        raise ValueError("activate ESP-IDF 5.5.3 before building")
    for role, version in VERSIONS.items():
        location = (output / role).absolute()
        location.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, str(Path(idf) / "tools" / "idf.py"),
            "-C", str(ROOT / "firmware"), "-B", str(location),
            "-D", f"SDKCONFIG={location / 'sdkconfig'}",
            "-D", f"LAB_VERSION={version}",
            "-D", f"LAB_SERVER_PORT={port}",
            "-D", f"LAB_FORCE_SELF_TEST_FAILURE={'ON' if role == 'faulty' else 'OFF'}",
            "build",
        ]
        subprocess.run(command, check=True)
