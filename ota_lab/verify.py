"""Exercise real firmware, virtual flash, and HTTP traffic under ESP32 QEMU."""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import threading
import time

from .build import APP_IMAGE, VERSIONS
from .server import LabState, run_server


FLASH_SIZE = 4 * 1024 * 1024


def make_flash(build, destination):
    manifest = json.loads((build / "flasher_args.json").read_text(encoding="utf-8"))
    flash = bytearray(b"\xff" * FLASH_SIZE)
    end = 0
    images = sorted((int(offset, 0), name) for offset, name in manifest["flash_files"].items())
    for offset, name in images:
        image = (build / name).read_bytes()
        if offset < end or offset + len(image) > FLASH_SIZE:
            raise ValueError(f"overlapping or out-of-bounds flash image: {name}")
        end = offset + len(image)
        flash[offset:end] = image
    destination.write_bytes(flash)


class Console:
    def __init__(self, process, echo):
        self.process = process
        self.echo = echo
        self.lines = []
        self.lock = threading.Lock()

    def read(self):
        for line in self.process.stdout:
            with self.lock:
                self.lines.append(line.strip())
            if self.echo:
                print(line.rstrip(), flush=True)

    def snapshot(self):
        with self.lock:
            return tuple(self.lines)

    def expect(self, text, *, after=0, timeout=45):
        def match():
            return next((line for line in self.snapshot()[after:] if text in line), None)

        line = self.wait(f"serial output containing {text!r}", match, timeout)
        print(line, flush=True)
        return line

    def wait(self, description, predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.process.poll() is None:
            value = predicate()
            if value:
                return value
            time.sleep(0.15)
        tail = "\n".join(self.snapshot()[-30:])
        raise RuntimeError(f"waiting for {description} failed (QEMU exit: {self.process.poll()})\n{tail}")


@contextmanager
def run_qemu(executable, flash, log, *, echo):
    command = [
        executable, "-machine", "esp32", "-nographic", "-monitor", "none",
        "-drive", f"file={flash.name},if=mtd,format=raw",
        "-nic", "user,model=open_eth",
        "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
    ]
    with subprocess.Popen(
        command, cwd=flash.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    ) as process:
        console = Console(process, echo)
        reader = threading.Thread(target=console.read, daemon=True)
        reader.start()
        try:
            yield console
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            reader.join(timeout=5)
            if log is not None:
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text("\n".join(console.snapshot()) + "\n", encoding="utf-8")


def matching_records(state, version):
    return [item for item in state.snapshot()["records"] if item["firmware"] == version]


@contextmanager
def device_lab(output, port, qemu, log, *, echo=False):
    images = {
        VERSIONS[role]: (output / role / APP_IMAGE).read_bytes() for role in ("healthy", "faulty")
    }
    state = LabState(images)
    with TemporaryDirectory(prefix="esp32-ota-") as directory:
        flash = Path(directory) / "flash.bin"
        make_flash(output / "baseline", flash)
        with run_server(state, port), run_qemu(qemu, flash, log, echo=echo) as console:
            yield state, console


def verify_all(output, port, qemu, log):
    base, healthy, faulty = (VERSIONS[key] for key in ("baseline", "healthy", "faulty"))
    with device_lab(output, port, qemu, log) as (state, console):
        console.expect(f"BOOT version={base} slot=ota_0", timeout=60)
        console.wait("baseline HTTP telemetry", lambda: len(matching_records(state, base)) >= 2)

        start = len(console.snapshot())
        state.configure({"offline": True})

        def queued_sequences():
            lines = console.snapshot()[start:]
            values = [
                int(match.group(1)) for line in lines
                if (match := re.search(r"ota_lab: QUEUED count=\d+ sequence=(\d+)", line))
            ]
            return values if len(values) >= 3 else None

        buffered = console.wait("three buffered readings during the outage", queued_sequences)
        restore_at = len(console.snapshot())
        state.configure({"offline": False, "drop_next_ack": True})
        console.expect("QUEUE_FLUSHED", after=restore_at)
        console.wait("deduplicated telemetry after a lost HTTP acknowledgement",
                     lambda: state.snapshot()["duplicates"] > 0)
        console.wait("all buffered readings at the server",
                     lambda: set(buffered) <= {item["sequence"] for item in state.snapshot()["records"]})
        print("PASS: offline queue, replay and idempotent HTTP acknowledgement", flush=True)

        state.configure({"offer": healthy, "truncate": True})
        console.expect(f"OTA_ABORT version={healthy}")
        if state.snapshot()["interrupted_downloads"] == 0 or matching_records(state, healthy):
            raise RuntimeError("interrupted image must leave the running version unchanged")
        state.configure({"truncate": False})
        console.expect(f"TRIAL_CONFIRMED version={healthy} slot=ota_1", timeout=90)
        console.expect(f"BOOT version={healthy} slot=ota_1")
        console.wait("healthy version HTTP telemetry", lambda: matching_records(state, healthy))
        print("PASS: interrupted download, retry and healthy image confirmation", flush=True)

        state.configure({"offer": faulty})
        console.expect(f"TRIAL_REJECTED version={faulty} slot=ota_0", timeout=90)
        returned = console.expect(f"rejected={faulty}")
        if f"BOOT version={healthy} slot=ota_1" not in returned:
            raise RuntimeError("rollback did not return to the confirmed version")
        count = len(matching_records(state, healthy))
        console.wait("telemetry after rollback", lambda: len(matching_records(state, healthy)) >= count + 4)
        snapshot = state.snapshot()
        if snapshot["downloads"].count(faulty) != 1 or matching_records(state, faulty):
            raise RuntimeError("a rejected image must not be reinstalled or publish telemetry")
        sequences = [item["sequence"] for item in snapshot["records"]]
        if sequences != list(range(sequences[0], sequences[-1] + 1)):
            raise RuntimeError("telemetry sequence was not continuous across reboots")
        print("PASS: bootloader rollback, rejected image suppression and NVS sequence continuity", flush=True)
