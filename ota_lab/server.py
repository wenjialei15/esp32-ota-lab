"""Serve known firmware images and collect telemetry on the local machine."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading


VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){2}")
DEVICE_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,32}")


def valid_version(value):
    return isinstance(value, str) and VERSION_PATTERN.fullmatch(value) is not None


class LabState:
    def __init__(self, images=None):
        self.images = dict(images or {})
        if any(not valid_version(version) for version in self.images):
            raise ValueError("image versions must use MAJOR.MINOR.PATCH (0–999 per field)")
        self.records = {}
        self.lock = threading.Lock()
        self.offer = None
        self.offline = False
        self.truncate = False
        self.interrupted_downloads = 0
        self.downloads = []
        self.drop_next_ack = False
        self.duplicates = 0

    def configure(self, changes):
        if not isinstance(changes, dict) or not changes.keys() <= {"offer", "offline", "truncate", "drop_next_ack"}:
            raise ValueError("use offer, offline, truncate or drop_next_ack")
        for key in changes.keys() & {"offline", "truncate", "drop_next_ack"}:
            if type(changes[key]) is not bool:
                raise ValueError(f"{key} must be true or false")
        if "offer" in changes:
            version = changes["offer"]
            if version is not None and (not valid_version(version) or version not in self.images):
                raise ValueError("offer must be a known version or null")
        with self.lock:
            for key, value in changes.items():
                setattr(self, key, value)

    def snapshot(self):
        with self.lock:
            return {
                "offer": self.offer,
                "offline": self.offline,
                "truncate": self.truncate,
                "duplicates": self.duplicates,
                "interrupted_downloads": self.interrupted_downloads,
                "downloads": list(self.downloads),
                "records": list(self.records.values()),
            }

    def manifest(self):
        with self.lock:
            return None if self.offline else {"version": self.offer}

    def image(self, version):
        with self.lock:
            if self.offline or version != self.offer:
                return None, False
            self.downloads.append(version)
            if self.truncate:
                self.interrupted_downloads += 1
            return self.images[version], self.truncate

    def telemetry(self, body):
        if not isinstance(body, dict):
            raise ValueError("telemetry must be a JSON object")
        device = body.get("device")
        sequence = body.get("sequence")
        temperature = body.get("temperature_centi_c")
        version = body.get("firmware")
        if (not isinstance(device, str) or not DEVICE_PATTERN.fullmatch(device) or
            type(sequence) is not int or not 1 <= sequence <= 0xffffffff or
            type(temperature) is not int or not -4000 <= temperature <= 12500 or
            not valid_version(version)):
            raise ValueError("invalid device, sequence, temperature or firmware version")
        key = (device, sequence)
        with self.lock:
            if self.offline:
                return None
            existing = self.records.get(key)
            if existing is not None:
                if existing["temperature_centi_c"] != temperature:
                    return 409
                self.duplicates += 1
                return 200
            self.records[key] = {
                "device": device, "sequence": sequence,
                "temperature_centi_c": temperature, "firmware": version,
            }
            if self.drop_next_ack:
                self.drop_next_ack = False
                return None
            return 201


class LabHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *args):
        pass

    def send_payload(self, status, payload, content_type="application/json", limit=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload[:limit])

    def send_json(self, status, value):
        self.send_payload(status, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 1 <= length <= 1024:
            raise ValueError("request must contain between 1 and 1024 bytes")
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/api/lab":
            self.send_json(200, self.server.state.snapshot())
        elif self.path == "/api/manifest":
            manifest = self.server.state.manifest()
            if manifest is not None:
                self.send_json(200, manifest)
        elif self.path.startswith("/images/") and self.path.endswith(".bin"):
            image, truncate = self.server.state.image(self.path[8:-4])
            if image is None:
                self.send_json(404, {"error": "image is not currently offered"})
            else:
                self.send_payload(200, image, "application/octet-stream", 24_576 if truncate else None)
        else:
            self.send_json(404, {"error": "unknown route"})

    def do_POST(self):
        try:
            if self.path == "/api/lab":
                self.server.state.configure(self.read_json())
                self.send_json(200, self.server.state.snapshot())
            elif self.path == "/api/telemetry":
                status = self.server.state.telemetry(self.read_json())
                if status is not None:
                    self.send_json(status, {"accepted": status != 409})
            else:
                self.send_json(404, {"error": "unknown route"})
        except (ValueError, UnicodeError) as error:
            self.send_json(400, {"error": str(error)})


@contextmanager
def run_server(state, port):
    with ThreadingHTTPServer(("127.0.0.1", port), LabHandler) as server:
        server.state = state
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join()
