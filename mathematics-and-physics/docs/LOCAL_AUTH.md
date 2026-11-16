# Local authentication and data ownership

This development build replaces anonymous access to private Gitea projects,
model-training datasets and chat history with named, authenticated local
accounts. It does not use Telegram, OpenAI or third-party login services.

## Bootstrap the first administrator

Ensure `.env` contains valid PostgreSQL credentials, then run:

```bash
docker compose up --build -d
docker compose exec web python -m auth bootstrap
```

You will be prompted interactively for a username and a unique password
of 14–128 characters. This command succeeds only when **no local account**
exists. Passwords are stored as salted scrypt hashes in PostgreSQL and are not
printed or added to version control. Keep the terminal and Docker host
restricted to authorized administrators.

To create another local account from the trusted machine:

```bash
docker compose exec web python -m auth create-user
```

This command also prompts for a username and password. No public sign-up or
password-reset endpoint is implemented.

## Log in

Open http://localhost:8000 and enter the local account credentials. Requests
to projects, model-training datasets and conversations require a valid
authenticated cookie. Sessions expire after 7 days, can be invalidated by
logging out and use HttpOnly and SameSite=Strict cookies. State-changing
requests require a separate CSRF token and reject cross-origin requests.

**Deployment restriction:** The site remains bound to 127.0.0.1:8000. Do not
publish the site beyond a trusted local workstation until HTTPS, a reverse
proxy, network authentication, administration and browser penetration testing
are added. For localhost HTTP, `COOKIE_SECURE=false` is necessary; set it to
true behind properly configured HTTPS before any remote deployment.

## Preserve projects from older anonymous sessions

Older deployments used a browser cookie named `engai_session`. After login,
an authorized local user can explicitly **claim legacy data** from the same
browser. This operation transfers all rows owned by that specific negative
session ID (including Gitea repository mappings, training examples, jobs,
chat history and quizzes) to the authenticated account in one SQL
transaction. It does **not** move Git bytes; Git repositories remain in Gitea
with unchanged names. It will refuse to merge into a populated account or
while an old training job is running.

Keep a backup of both databases and the Gitea repository volume before
claiming data. If the old cookie is missing, an administrator must assess
manual recovery; the application does not guess ownership.

## Current limits

- Login failures are counted transactionally and a username is locked for
  15 minutes after six unsuccessful attempts. This is not a replacement for
  network rate limiting or reverse-proxy security.
- Password reset, MFA, detailed audit trails and administrative role
  management are not implemented.
- An authenticated account cannot be deleted via the web API yet, to avoid
  orphaning training and Gitea artifacts. See Issues #5 and #8.
- All local accounts currently have the same project/data scope; no shared
  project permissions or RBAC for user-created repositories are implemented.
- Use a trusted local admin shell for `create-user`; no browser registration.

These limits remain tracked in Issue #9 until reviewed and tested.
