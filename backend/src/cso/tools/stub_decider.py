"""A stand-in Decider server for screenshots and demos: `python -m cso.tools.stub_decider`.

It answers `GET /health` and `POST /v1/systemone` with fixed, plainly illustrative readings, so the
real application (replay mode, real worker, real policy and lane code) can run end to end without a
GPU or a model download. Nothing it says is a model output, and `/health` says so in the model name.
It binds to 127.0.0.1 only (invariant 7) and has no way to read evidence: the same answers go back
for every case.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOST = "127.0.0.1"
MODEL = "stub-decider (illustrative readings, not a model)"

# One synthetic story: a new account renaming a road. Probabilities for the yes/no probes.
READINGS: dict[str, float] = {
    "new_account_first_edits": 0.93,
    "mature_feature_deleted": 0.05,
    "nonsense_or_offensive_values": 0.12,
    "comment_matches_changes": 0.41,
    "conventions_followed": 0.38,
    "deleted_own_recent_additions": 0.04,
    "real_world_change_claimed": 0.57,
    "discussion_cites_source": 0.04,
    "mass_retag_single_key": 0.03,
    "evidence_sufficient": 0.90,
}
PREFERRED_CHOICES = ("likely_good_faith_mistake", "welcome_and_tips")
HEALTH: dict[str, Any] = {
    "status": "ok",
    "model": MODEL,
    "checkpoint": "none",
    "base_model": "none",
    "num_slots": 1,
    "max_length": 4096,
    "temperature": 1.0,
    "device": "cpu",
    "prefix_cache": False,
}


def _options(question: dict[str, Any]) -> list[str]:
    criteria = question.get("criteria", {})
    return [str(code) for code in criteria]


def answer_for(question: dict[str, Any], name: str) -> dict[str, Any]:
    """One answer for one question of a request."""
    if question.get("type") == "noul":
        return {"type": "noul", "noul": READINGS.get(name, 0.5)}
    options = _options(question)
    top = next((o for o in PREFERRED_CHOICES if o in options), options[0])
    rest = (1.0 - 0.46) / max(len(options) - 1, 1)
    probabilities = {o: (0.46 if o == top else rest) for o in options}
    if len(options) == 1:
        probabilities = {top: 1.0}
    return {"type": "choice", "choice": top, "probabilities": probabilities, "confidence": 0.3}


def respond(request: dict[str, Any]) -> dict[str, Any]:
    """A response shaped like the real server's, for any panel or permutation request."""
    questions = request.get("questions", {})
    return {
        "model": MODEL,
        "answers": {name: answer_for(q, name) for name, q in questions.items()},
        "usage": {"input_tokens": 700, "output_tokens": 0},
        "latency_ms": 5.0,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (name fixed by BaseHTTPRequestHandler)
        if self.path == "/health":
            self._send(200, HEALTH)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/systemone":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": "not json"})
            return
        self._send(200, respond(request if isinstance(request, dict) else {}))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # quiet: this runs next to a build script


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((HOST, args.port), Handler)
    print(f"stub decider on http://{HOST}:{args.port} (illustrative readings only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
