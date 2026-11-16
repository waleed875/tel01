"""Operator-only, disposable Docker runtimes for nine programming languages.

Never call this module from FastAPI. Docker is a powerful host capability:
only the trusted local operator may invoke this runner. No project volumes,
database credentials, internet, docker socket, or arbitrary image/command args.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import secrets
import selectors
import subprocess
import tempfile
import time


MAX_CODE_BYTES = 64 * 1024
MAX_INPUT_BYTES = 8 * 1024
MAX_OUTPUT_BYTES = 32 * 1024
RUN_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class Runtime:
    image: str
    filename: str
    command: str


# Shell expressions below are fixed, operator-reviewed literals.
# Neither generated code nor user-supplied paths are interpolated into them.
RUNTIMES = {
    "python": Runtime("python:3.12-alpine", "main.py",
                      "python -I /input/main.py < /input/stdin.txt"),
    "javascript": Runtime("node:22-alpine", "main.js",
                          "node /input/main.js < /input/stdin.txt"),
    "c": Runtime("gcc:14", "main.c",
                 "gcc /input/main.c -O0 -o /tmp/program && /tmp/program < /input/stdin.txt"),
    "cpp": Runtime("gcc:14", "main.cpp",
                   "g++ /input/main.cpp -std=c++17 -O0 -o /tmp/program && /tmp/program < /input/stdin.txt"),
    "go": Runtime("golang:1.24-alpine", "main.go",
                  "go build -o /tmp/program /input/main.go && /tmp/program < /input/stdin.txt"),
    "rust": Runtime("rust:1.86-alpine", "main.rs",
                    "rustc /input/main.rs -o /tmp/program && /tmp/program < /input/stdin.txt"),
    "java": Runtime("eclipse-temurin:21-jdk-alpine", "Main.java",
                    "javac -d /tmp /input/Main.java && java -cp /tmp Main < /input/stdin.txt"),
    "ruby": Runtime("ruby:3.3-alpine", "main.rb",
                    "ruby /input/main.rb < /input/stdin.txt"),
    "php": Runtime("php:8.3-cli-alpine", "main.php",
                   "php /input/main.php < /input/stdin.txt"),
}
EXTENSIONS = {".py": "python", ".js": "javascript", ".c": "c",
              ".cpp": "cpp", ".cc": "cpp", ".go": "go",
              ".rs": "rust", ".java": "java", ".rb": "ruby",
              ".php": "php"}


def language_for(path: Path) -> str:
    language = EXTENSIONS.get(path.suffix.lower())
    if language is None:
        raise ValueError("Unsupported source language")
    return language


def _bounded_output(command: list[str], *, container_name: str, timeout: int):
    start = time.monotonic()
    out, err = bytearray(), bytearray()
    truncated, timed_out = False, False
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with selectors.DefaultSelector() as selector:
            for channel in (process.stdout, process.stderr):
                os.set_blocking(channel.fileno(), False)
                selector.register(channel, selectors.EVENT_READ,
                                  "stdout" if channel is process.stdout else "stderr")
            while selector.get_map():
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = out if key.data == "stdout" else err
                    available = MAX_OUTPUT_BYTES - len(out) - len(err)
                    if len(chunk) > available:
                        target.extend(chunk[:max(0, available)])
                        truncated = True
                        break
                    target.extend(chunk)
                if truncated:
                    break
            if not timed_out and not truncated:
                process.wait(timeout=max(0.1, timeout - (time.monotonic() - start)))
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        if timed_out or truncated:
            # The Docker CLI and its daemon container are separate processes.
            # Explicitly stop only the uniquely named container we created.
            try:
                subprocess.run(["docker", "rm", "-f", container_name],
                               timeout=5, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
        process.stdout.close()
        process.stderr.close()
    return {
        "exit_code": process.returncode if not timed_out and not truncated else None,
        "stdout": out.decode("utf-8", "replace"),
        "stderr": err.decode("utf-8", "replace"),
        "timed_out": timed_out,
        "output_limited": truncated,
        "elapsed_seconds": round(time.monotonic() - start, 3),
    }


def execute(language: str, code: str, stdin: str = "",
            *, timeout: int = RUN_TIMEOUT_SECONDS) -> dict:
    if language not in RUNTIMES:
        raise ValueError("Unsupported language; use --languages to inspect the allowlist")
    if not isinstance(code, str) or not isinstance(stdin, str):
        raise ValueError("Source and standard input must be text")
    if not code.strip() or len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError("Source must be nonempty and at most 64 KiB")
    if len(stdin.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Standard input may not exceed 8 KiB")
    if type(timeout) is not int or not 1 <= timeout <= RUN_TIMEOUT_SECONDS:
        raise ValueError("Time limit must be 1..20 seconds")
    runtime = RUNTIMES[language]
    name = "lab-code-" + secrets.token_hex(8)
    with tempfile.TemporaryDirectory(prefix="lab-code-input-") as tmp:
        folder = Path(tmp)
        source = folder / runtime.filename
        input_file = folder / "stdin.txt"
        source.write_text(code, encoding="utf-8")
        input_file.write_text(stdin, encoding="utf-8")
        source.chmod(0o444)
        input_file.chmod(0o444)
        folder.chmod(0o555)
        args = [
            "docker", "run", "--rm", "--name", name,
            "--pull=never", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--ipc=none", "--pids-limit=64", "--memory=512m",
            "--memory-swap=512m", "--cpus=1",
            "--ulimit=nofile=64:64", "--user=65534:65534",
            "--tmpfs=/tmp:rw,nosuid,nodev,exec,size=128m,mode=1777",
            "--mount=type=bind,src=" + str(folder.resolve()) + ",dst=/input,readonly",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "GOTOOLCHAIN=local", "-e", "GOPROXY=off",
            "-e", "GOSUMDB=off", "-e", "CGO_ENABLED=0",
            "-e", "GOCACHE=/tmp/go-cache",
            "-e", "HOME=/tmp",
            "--workdir=/tmp",
            "--entrypoint=/bin/sh", runtime.image,
            "-c", runtime.command,
        ]
        try:
            result = _bounded_output(args, container_name=name, timeout=timeout)
        except FileNotFoundError as exc:
            raise RuntimeError("Docker is not installed on this trusted host") from exc
    return {"language": language, "image": runtime.image,
            "success": result["exit_code"] == 0
                       and not result["timed_out"]
                       and not result["output_limited"],
            **result,
            "notice": "نجاح تنفيذ البرنامج لا يعني صحة الحل أو أمان الكود."}
