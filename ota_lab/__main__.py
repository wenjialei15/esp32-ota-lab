"""Run the ESP32 OTA software lab."""

import argparse
from pathlib import Path
import subprocess
import sys
from .build import build_all
from .verify import device_lab, verify_all


def port_number(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main():
    parser = argparse.ArgumentParser(description="Build and verify ESP32 OTA without a physical board.")
    parser.add_argument("--port", default=8765, type=port_number, help="local HTTP port (default: 8765)")
    parser.add_argument("--output", default=Path(".build"), type=Path, help="ESP-IDF build directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="compile baseline, healthy and faulty ESP32 images")
    verify = commands.add_parser("verify", help="run the hardware-free QEMU end-to-end verification")
    run = commands.add_parser("run", help="start the device and HTTP server for manual experiments")
    for command in (verify, run):
        command.add_argument("--qemu", default="qemu-system-xtensa", help="path to the Espressif QEMU executable")
        command.add_argument("--log", type=Path, default=Path(".build/qemu.log"), help="full UART output path")
    args = parser.parse_args()
    try:
        if args.command == "build":
            build_all(args.output, args.port)
        elif args.command == "verify":
            verify_all(args.output, args.port, args.qemu, args.log)
        else:
            with device_lab(args.output, args.port, args.qemu, args.log, echo=True) as (_, console):
                print(f"Lab API: http://127.0.0.1:{args.port}/api/lab", flush=True)
                if console.process.wait() != 0:
                    raise RuntimeError("QEMU exited; see the UART log")
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Lab error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
