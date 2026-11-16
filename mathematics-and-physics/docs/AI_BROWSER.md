# AI internet research browser — Issue #22

The Engineering AI Lab may optionally consult public websites for source
material. This is a **retrieval component**, not an external AI model and
not a replacement for training our own neural network. No MinIO, paid search
API, OpenAI API or pretrained model weights are required.

## Architecture

- `web`: existing Arabic authenticated app with PostgreSQL and Gitea access.
- `ai-browser`: independent Python reader service. It accepts internal
  research requests, fetches **public HTTPS** only, and extracts plain text
  from HTML without running JavaScript.
- `searxng`: local open-source metasearch aggregator; queries may be sent to
  public search engines configured by SearXNG. Search privacy therefore
  depends on those engines.
- `research` network: outgoing research connections, isolated from Gitea and
  PostgreSQL containers. Neither browser nor SearXNG has credentials,
  volumes, Docker socket, Git access or access to local model checkpoints.
- `internal` network: app databases, Gitea, trainer and web. It is marked
  internal so only explicitly connected services can reach the Internet.

## Local Docker installation

Add an independent random secret in `.env`:

```env
SEARXNG_SECRET=<a-new-random-64-character-hex-string>
```

Generate it locally with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Then, from `mathematics-and-physics`:

```bash
docker compose up --build -d
```

Sign in at `http://localhost:8000` and select **متصفح أبحاث AI**.
Enter a query, choose **قراءة الصفحة** to see extracted text and click the
source URL to verify claims in your own browser. For optional web evidence in
chat, tick **الاستعانة بمصادر الإنترنت** before submitting a question. Source
links appear alongside the response.

If the model checkpoint is missing, standalone search still works; model chat
still requires a trained local checkpoint. Internet access does **not**
automatically make the tiny language model capable or reliable.

## Security boundaries

The reader rejects private IPs, localhost, internal hostnames, IP-literal URLs,
credentials in URLs, arbitrary ports and non-HTTPS schemes. DNS is checked at
connection time and each redirect is revalidated. Max HTML/page payload is
512 KiB, max text extract is 10 KiB, and short timeouts apply. Search returns
at most eight results; chat fetches at most two pages. The research service
does not execute page JavaScript, open binary downloads, follow unbounded
redirects or write Gitea projects.

Web pages and search snippets are **untrusted text**, not commands. They can
contain malicious instructions, inaccurate data, fabricated citations or
outdated documentation. The model currently receives a warning plus bounded
plain-text evidence, but prompt-injection resistance is **not proven**. Never
connect research results directly to shell execution or Git-writing tools.
Confirm important engineering instructions independently.

This is a **read-only text research browser**, not a graphical Chromium /
Playwright browser. Modern client-side sites may not yield useful text until
a future strictly isolated rendering service is implemented.

## Known limitations and future tests

- Search engine rate-limits, CAPTCHAs and site blocking may reduce results.
- Tests cover URL/DNS filtering, source extraction, ownership and basic
  integration; target-host networking needs live verification.
- DNS rebinding, request smuggling, redirects, and unusual content encodings
  need ongoing security review before public deployment.
- Model quality improvement must be benchmarked against the same questions
  with and without retrieval, under Issue #18.
- Keep Docker published ports bound to loopback; do not expose this early
  research service to untrusted networks.
