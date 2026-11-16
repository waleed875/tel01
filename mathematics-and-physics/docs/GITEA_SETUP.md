# Local Gitea workspace setup

This project deliberately does not use Telegram, OpenAI, or a pretrained AI model.

## 1. Prepare local environment

Use Docker Desktop/Engine + Docker Compose. From `mathematics-and-physics`:

```bash
cp .env.example .env
```

On Windows PowerShell use `Copy-Item .env.example .env`.

Set two **different strong random passwords** for `POSTGRES_PASSWORD` and
`GITEA_DB_PASSWORD` in `.env`. Avoid characters reserved in URL syntax
(`:`, `/`, `@`, `?`, `#`, `%`) in this simple PostgreSQL connection-string
example; a production deployment should use proper URL-encoding or secret mounts.

Start the stack:

```bash
docker compose up --build -d
docker compose ps
```

The lab web app runs on **http://localhost:8000** and Gitea runs on
**http://localhost:3001**. Both are loopback-bound for local development. No
public TCP ports are needed for PostgreSQL. Gitea repository/attachment data is
stored in the `gitea_data` volume; its separate PostgreSQL data is in
`gitea_postgres_data`.

## 2. Finish Gitea first-run installation

1. Open http://localhost:3001 and complete Gitea's first-run installation
   wizard. Database settings inside Docker: host `gitea-db:5432`, database
   `gitea`, user `gitea`, password from `.env` (the container's environment
   already provides these values).
2. Create an administrator/service account for the private Git repositories.
   As configured, public self-registration is disabled. If the first-run UI
   offers administrator creation, use it; otherwise use the documented Gitea
   administrative user creation process inside its container.
3. Under that Gitea account, open user **Settings → Applications → Generate
   New Token**, with **write:repository** and **write:user** scopes (the latter is needed
   for creating repositories via the `/user/repos` endpoint in this Gitea
   version). Do not grant full administrator scopes to the application token. Do not paste the token in ChatGPT.
4. Set `GITEA_OWNER` to that Gitea username, and `GITEA_API_TOKEN` to the
   service-account token in the *local, untracked* `.env` file.
5. Apply settings: `docker compose up -d --force-recreate web`.

The Git repository names are randomly generated (e.g.
`engineering-<24-hex-chars>`). The human-readable project title is stored in
the Lab's PostgreSQL database. Every repository is requested as **private**.

## 3. Work from the Lab interface

Navigate to **المشاريع العملية**. Create a software or engineering project, open
it, and browse files. To edit a UTF-8 text file, click it, change content, and
press **حفظ Git Commit**. The editor includes the blob SHA read from Gitea;
if someone else has saved a newer version, Gitea should reject the stale
update, so refresh the file and reconcile the changes.

New text files may be created from a path and content. The upload form supports
binary files up to 2 MiB, including images and electronic CAD project files.
Binary files are downloadable but not edited as source text. Each write/delete
creates a commit in the private Gitea repository. The latest commits are shown
in the project explorer.

## Security and deployment limits

- This is for a **trusted local workstation only**. Browser cookies are
  session identifiers, not accounts. Do not expose the web app or Gitea to the
  internet until proper authentication, TLS, authorization and CSRF defense
  are designed and tested.
- Store the Gitea token only in `.env` on the server; never commit it or
  give it to browsers. All REST calls use fixed `http://gitea:3000`.
- File contents and Git history live in Gitea; PostgreSQL stores project mappings.
  To delete a project, use **حذف المستودع** from the project list. This first
  marks the mapping as deleting, then deletes the remote Git repository, then
  removes the mapping. If Gitea is unavailable, the project stays in a retryable
  deleting state. This is **destructive**: back up repositories before deleting.
- Deleting the browser session is **blocked** while any Gitea projects are
  mapped to it; delete the projects first. If you lose your browser session
  cookie, an administrator may need to recover the repositories manually.
- Project archival/restore and full cross-system backup verification are still
  tracked in GitHub Issue #8. Training checkpoint deletion is separate (#5).
- Download and upload file limit: 2 MiB per file. For larger schematics, CAD
  archives, media, or Git LFS, add a separate design with resource limits.
- No autonomous AI write access is granted. All edits are explicitly initiated
  by a user through the interface.
- Run `docker compose down` to stop containers without deleting data.
  **Never run `docker compose down -v` unless you deliberately want to erase
  PostgreSQL, Gitea and model volumes.**
- Back up the named volumes consistently. Restoring Gitea requires both its
  Git data and database metadata.

This integration uses Gitea's documented contents API, including base64 file
payloads, blob SHA for updates, and separate create/update/delete operations.

## Project search, previews and renames

Use the **بحث في أسماء الملفات والمجلدات الفرعية** field inside a Gitea
project to find source files across nested folders. Git tree scanning is
bounded; results may be partial for very large repositories.

The built-in file preview supports selected safe file types: UTF-8 Markdown
(displayed as text-only, limited headings/lists/code formatting), text,
PNG/JPEG/GIF/WebP images, and PDFs. The server checks both extensions and
file signatures for binary types, limits reads to 2 MiB, forces no-sniff
responses, and sends sandbox headers for rendered content. Embedded SVG,
HTML and executable content are not previewed. PDF viewer availability
depends on browser support for sandboxed documents; download remains
available.

To rename/move a file, first choose its latest version in the explorer,
enter a new relative path and press **نقل بعملية Git واحدة**. Gitea
performs the rename in one commit using the existing file blob SHA.
An old SHA or existing destination is rejected; refresh the file and
retry rather than overwriting others' changes. This feature moves a
**single file**, not whole directory trees.

These operations remain available only in the localhost-only prototype.
Authentication, full audit logs and public hosting remain separate tasks.
