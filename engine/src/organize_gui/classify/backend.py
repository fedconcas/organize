"""Loopback-only model backends.

OllamaBackend talks to an Ollama server that this engine starts itself on
127.0.0.1:<free port>. It uses http.client directly (never urllib, so proxy
variables are ignored), follows no redirects, and only calls /api/embed,
/api/chat and /api/tags. Pulling models is never done.
"""

import http.client
import json
import os
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Sequence

OLLAMA_CANDIDATES = (
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
    "/Applications/Ollama.app/Contents/Resources/ollama",
)
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
ALLOWED_PATHS = {"/api/embed", "/api/chat", "/api/tags"}
EMBED_BATCH = 32


class BackendUnavailable(Exception):
    """The local model server or a model is not available."""


def model_matches(installed: str, wanted: str) -> bool:
    def norm(value: str) -> str:
        return value if ":" in value else value + ":latest"
    return norm(installed) == norm(wanted)


class OllamaBackend:
    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = 120.0) -> None:
        if host not in LOOPBACK:
            raise BackendUnavailable("Only a loopback model server is allowed.")
        self.host = "127.0.0.1" if host == "localhost" else host
        self.port = int(port)
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                 timeout: Optional[float] = None) -> Dict[str, Any]:
        if path not in ALLOWED_PATHS:
            raise BackendUnavailable("Endpoint not allowed: %s" % path)
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout or self.timeout)
        try:
            body = json.dumps(payload).encode() if payload is not None else None
            connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read(64 * 1024 * 1024)
            if response.status != 200:
                raise BackendUnavailable("Model server answered %d" % response.status)
            return json.loads(data or b"{}")
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise BackendUnavailable(str(exc)) from exc
        finally:
            connection.close()

    def models(self) -> List[str]:
        return [str(item.get("name", "")) for item in self._request("GET", "/api/tags", timeout=10).get("models", [])]

    def has_model(self, name: str) -> bool:
        return any(model_matches(item, name) for item in self.models())

    def embed(self, model: str, texts: Sequence[str], unload: bool = True) -> List[List[float]]:
        vectors: List[List[float]] = []
        batches = [list(texts[start:start + EMBED_BATCH]) for start in range(0, len(texts), EMBED_BATCH)]
        for index, batch in enumerate(batches):
            last = index == len(batches) - 1
            result = self._request("POST", "/api/embed", {
                "model": model, "input": batch, "truncate": True,
                "keep_alive": 0 if (last and unload) else "2m",
            })
            embeddings = result.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise BackendUnavailable("Unexpected embedding response")
            vectors.extend([float(value) for value in vector] for vector in embeddings)
        return vectors

    def chat_json(self, model: str, system: str, user: str, schema: Dict[str, Any],
                  timeout: float = 60.0) -> Dict[str, Any]:
        result = self._request("POST", "/api/chat", {
            "model": model, "stream": False, "format": schema, "keep_alive": "1m",
            "options": {"temperature": 0, "seed": 42, "num_ctx": 2048},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, timeout=timeout)
        content = (result.get("message") or {}).get("content", "")
        try:
            parsed = json.loads(content)
        except ValueError as exc:
            raise BackendUnavailable("Model returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise BackendUnavailable("Model returned invalid JSON")
        return parsed

    def unload(self, model: str) -> None:
        try:
            self._request("POST", "/api/chat", {"model": model, "messages": [], "keep_alive": 0}, timeout=15)
        except BackendUnavailable:
            pass


class OllamaServer:
    """`ollama serve` owned by this engine: loopback, one model, one request at a time."""

    def __init__(self, binary: Optional[str] = None) -> None:
        self.binary = binary or find_ollama()
        self.process: Optional[subprocess.Popen] = None
        self.port: Optional[int] = None

    @staticmethod
    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def start(self, wait: float = 30.0) -> OllamaBackend:
        if not self.binary:
            raise BackendUnavailable("Ollama is not installed.")
        self.port = self.free_port()
        environment = {
            "HOME": os.environ.get("HOME", ""),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "OLLAMA_HOST": "127.0.0.1:%d" % self.port,
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_KEEP_ALIVE": "0",
        }
        for key in ("OLLAMA_MODELS", "TMPDIR"):
            if os.environ.get(key):
                environment[key] = os.environ[key]
        self.process = subprocess.Popen(
            [self.binary, "serve"], env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        )
        backend = OllamaBackend(self.port)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                backend.models()
                return backend
            except BackendUnavailable:
                time.sleep(0.25)
        self.stop()
        raise BackendUnavailable("The local model server did not start.")

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def find_ollama() -> Optional[str]:
    for candidate in OLLAMA_CANDIDATES:
        if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class FakeBackend:
    """Deterministic in-process backend for tests: bag-of-words hashing embeddings."""

    def __init__(self, dims: int = 768, names: Optional[Dict[str, Dict[str, Any]]] = None,
                 models: Sequence[str] = ("nomic-embed-text:latest", "qwen2.5:3b-instruct"),
                 fail_chat: bool = False, chat_reply: Optional[Any] = None) -> None:
        self.dims = dims
        self.names = names or {}
        self.installed = list(models)
        self.fail_chat = fail_chat
        self.chat_reply = chat_reply
        self.embed_calls = 0
        self.chat_calls: List[str] = []
        self.unloaded: List[str] = []

    def models(self) -> List[str]:
        return list(self.installed)

    def has_model(self, name: str) -> bool:
        return any(model_matches(item, name) for item in self.installed)

    def embed(self, model: str, texts: Sequence[str], unload: bool = True) -> List[List[float]]:
        import hashlib
        import re

        self.embed_calls += 1
        vectors = []
        for text in texts:
            vector = [0.0] * self.dims
            for word in re.findall(r"[a-z]{3,}", text.lower()):
                if word in {"clustering", "file", "folder", "type"}:
                    continue
                digest = hashlib.sha256(word.encode()).digest()
                for offset in range(0, 6, 2):
                    index = int.from_bytes(digest[offset:offset + 2], "big") % self.dims
                    vector[index] += 1.0 if digest[offset + 1] % 2 else -1.0
            norm = sum(value * value for value in vector) ** 0.5 or 1.0
            vectors.append([value / norm for value in vector])
        if unload:
            self.unloaded.append(model)
        return vectors

    def chat_json(self, model: str, system: str, user: str, schema: Dict[str, Any],
                  timeout: float = 60.0) -> Dict[str, Any]:
        self.chat_calls.append(user)
        if self.fail_chat:
            raise BackendUnavailable("timeout")
        if self.chat_reply is not None:
            reply = self.chat_reply(user) if callable(self.chat_reply) else self.chat_reply
            if not isinstance(reply, dict):
                raise BackendUnavailable("Model returned invalid JSON")
            return reply
        for keyword, reply in self.names.items():
            if keyword in user.lower():
                return dict(reply)
        return {"name": "Mixed files", "folderName": "Mixed files", "description": "Various files"}

    def unload(self, model: str) -> None:
        self.unloaded.append(model)
