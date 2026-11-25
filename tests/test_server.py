from http.client import HTTPConnection, IncompleteRead, RemoteDisconnected
import json
import unittest

from ota_lab.server import LabState, run_server


class LabServerTest(unittest.TestCase):
    def setUp(self):
        self.image = bytes(50_000)
        self.state = LabState({"1.1.0": self.image})
        self.server = run_server(self.state, 0)
        self.http = HTTPConnection("127.0.0.1", self.server.__enter__(), timeout=3)
        self.addCleanup(self.server.__exit__, None, None, None)
        self.addCleanup(self.http.close)

    def request(self, method, path, body=None):
        payload = None if body is None else json.dumps(body)
        self.http.request(method, path, payload, {"Content-Type": "application/json"})
        response = self.http.getresponse()
        return response.status, response.read()

    def test_telemetry_deduplicates_replay_after_lost_response(self):
        row = {"device": "esp32-lab", "sequence": 1, "firmware": "1.0.0", "temperature_centi_c": 2207}
        self.state.configure({"drop_next_ack": True})
        with self.assertRaises(RemoteDisconnected):
            self.request("POST", "/api/telemetry", row)
        self.assertEqual(self.request("POST", "/api/telemetry", row)[0], 200)
        self.assertEqual(self.request("POST", "/api/telemetry", {**row, "temperature_centi_c": 999})[0], 409)
        self.assertEqual(self.request("POST", "/api/telemetry", {**row, "sequence": True})[0], 400)
        self.assertEqual(self.state.snapshot()["records"], [row])
        self.assertEqual(self.state.snapshot()["duplicates"], 1)

    def test_manifest_and_interrupted_image(self):
        self.assertEqual(json.loads(self.request("GET", "/api/manifest")[1]), {"version": None})
        self.assertEqual(self.request("GET", "/images/1.1.0.bin")[0], 404)
        self.assertEqual(self.request("POST", "/api/lab", {"offer": "1.3.0"})[0], 400)
        self.assertEqual(self.request("POST", "/api/lab", {"offer": "1.1.0", "truncate": True})[0], 200)
        self.assertEqual(json.loads(self.request("GET", "/api/manifest")[1]), {"version": "1.1.0"})
        with self.assertRaises(IncompleteRead):
            self.request("GET", "/images/1.1.0.bin")
        self.state.configure({"truncate": False})
        self.assertEqual(self.request("GET", "/images/1.1.0.bin"), (200, self.image))
        self.assertEqual(self.state.snapshot()["interrupted_downloads"], 1)


if __name__ == "__main__":
    unittest.main()
