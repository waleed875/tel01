"""Bootstrap an isolated CI Gitea container and run the live smoke test.

This tool intentionally operates on disposable CI Gitea only, never on a user
installation. Password and generated token are not printed.
"""
import base64
import json
import os
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    root = "http://127.0.0.1:3000"
    password = secrets.token_urlsafe(28)
    for attempt in range(90):
        try:
            with urlopen(root + "/api/v1/version", timeout=3) as res:
                if res.status == 200:
                    break
        except (HTTPError, URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(2)
    else:
        raise RuntimeError("Gitea did not start within 180 seconds")

    # Gitea CLI must run as git, not root. No password is logged.
    subprocess.run([
        "docker", "exec", "-u", "git", "gitea-ci",
        "gitea", "admin", "user", "create",
        "--username", "ci-engineer",
        "--password", password,
        "--email", "ci-engineer@example.invalid",
        "--must-change-password=false",
        "--admin",
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    credential = base64.b64encode(f"ci-engineer:{password}".encode()).decode()
    request = Request(root + "/api/v1/users/ci-engineer/tokens",
                      data=json.dumps({"name": "ci-workspace-smoke",
                                       "scopes": ["write:repository", "write:user"]}).encode(),
                      headers={"Authorization": "Basic " + credential,
                               "Content-Type": "application/json"},
                      method="POST")
    with urlopen(request, timeout=15) as response:
        token = json.loads(response.read())["sha1"]
    if not token:
        raise RuntimeError("Gitea did not issue an API token")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    env.update({
        "GITEA_OWNER": "ci-engineer",
        "GITEA_API_TOKEN": token,
        "GITEA_INTERNAL_URL": "http://gitea:3000",
    })
    print("Gitea disposable CI account ready; running real Git API smoke tests", flush=True)
    subprocess.run([sys.executable, "tests/gitea_live_smoke.py"], cwd=os.getcwd(),
                   env=env, check=True)


if __name__ == "__main__":
    main()
