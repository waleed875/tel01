"""Public-only web research and authenticated gateway regressions."""
import unittest
from unittest.mock import AsyncMock, patch
import socket

from fastapi.testclient import TestClient
from ai_browser import public_url, resolve_public_addresses, TextExtractor, app as reader_app
from webapp import app, session_user


class PublicURLTests(unittest.TestCase):
    def test_allow_only_public_https(self):
        self.assertEqual(public_url("https://example.com/guide?x=1"),
                         "https://example.com/guide?x=1")
        for value in (
            "http://example.com", "https://localhost/", "https://127.0.0.1/",
            "https://[::1]/", "https://192.168.1.10/secret",
            "https://metadata.google.internal/latest", "https://gitea:3000/",
            "https://example.local", "https://example.com:8080/",
            "https://user:password@example.com/", "file:///etc/passwd",
            "https://example.com/#fragment", "https://example.com/\nheader",
            "https://-bad.example/", "https://x..example/", "javascript:alert(1)"
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                public_url(value)

    def test_dns_rebinding_private_or_reserved_ip_rejected(self):
        def rows_for(*ips):
            return [(socket.AF_INET6 if ":" in ip else socket.AF_INET,
                     socket.SOCK_STREAM, 0, "", (ip, 443))
                    for ip in ips]
        with patch("ai_browser.socket.getaddrinfo",
                   return_value=rows_for("93.184.215.14")):
            result = resolve_public_addresses("example.com", 443)
            self.assertEqual(result[0]["host"], "93.184.215.14")
        for addresses in [
            ["127.0.0.1"], ["10.4.1.1"], ["192.168.2.1"],
            ["169.254.169.254"], ["::1"], ["93.184.215.14", "10.0.0.2"],
        ]:
            with self.subTest(addresses=addresses), \
                 patch("ai_browser.socket.getaddrinfo", return_value=rows_for(*addresses)):
                with self.assertRaises(ValueError):
                    resolve_public_addresses("example.com", 443)

    def test_html_is_inert_plain_text(self):
        parsed = TextExtractor().extract(
            '<html><head><title>Engineering Guide</title>'
            '<style>secret()</style></head><body><nav>Menu</nav>'
            '<main><h1>Ohm Law</h1><p>V = I * R</p>'
            '<script>alert("danger")</script></main></body></html>')
        self.assertEqual(parsed["title"], "Engineering Guide")
        self.assertIn("V = I * R", parsed["text"])
        self.assertNotIn("secret()", parsed["text"])
        self.assertNotIn("alert", parsed["text"])


class AuthenticatedResearchTests(unittest.TestCase):
    def test_private_research_api_enforces_auth_and_passes_url_as_data(self):
        client = TestClient(app)
        # No override: authentication cannot be bypassed.
        with patch("webapp.auth_store", None):
            self.assertEqual(client.post("/api/research/search",
                         json={"query": "electronics tutorials"}).status_code, 503)
        app.dependency_overrides[session_user] = lambda: 77
        try:
            with patch("webapp.research_request", new_callable=AsyncMock) as request:
                request.return_value = {"results": [{"url": "https://example.com/",
                                                      "title": "Guide"}]}
                result = client.post("/api/research/search",
                                     json={"query": "electronics tutorials"})
                self.assertEqual(result.status_code, 200)
                request.assert_awaited_with(
                    "/search", {"query": "electronics tutorials"})
                request.return_value = {"text": "Example", "url": "https://example.com/"}
                self.assertEqual(client.post("/api/research/read",
                    json={"url": "https://example.com/"}).status_code, 200)
                request.assert_awaited_with("/read", {"url": "https://example.com/"})
        finally:
            app.dependency_overrides.clear()

    def test_untrusted_research_page_rejects_localhost(self):
        reader = TestClient(reader_app)
        self.assertEqual(reader.post("/read", json={
            "url": "http://localhost:3000"}).status_code, 422)
        self.assertEqual(reader.post("/read", json={
            "url": "https://127.0.0.1/admin"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
