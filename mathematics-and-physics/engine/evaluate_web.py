"""Reproducible structural checks for generated static HTML/CSS.

These are quality checks, not a claim that the system can design arbitrary
websites. Visual screenshot comparison and execution tests remain future work.
"""
from html.parser import HTMLParser


class PageAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.links = []
        self.lang = False
        self.viewport = False
        self.external_scripts = []
        self.inline_scripts = False
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.tags.append(tag)
        if tag == "html":
            self.lang = bool(values.get("lang"))
        if tag == "meta" and values.get("name") == "viewport":
            self.viewport = True
        if tag == "a":
            self.links.append(values.get("href", ""))
        if tag == "script":
            self._in_script = True
            if values.get("src"):
                self.external_scripts.append(values["src"])
            else:
                self.inline_scripts = True
        if any(key.lower().startswith("on") for key in values):
            self.inline_scripts = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False


def inspect_frontend(html: str, css: str) -> dict:
    page = PageAudit()
    page.feed(html)
    checks = {
        "document_structure": all(tag in page.tags for tag in ("html", "head", "body", "main", "h1")),
        "semantic_sections": page.tags.count("section") >= 1,
        "has_language": page.lang,
        "mobile_viewport": page.viewport,
        "responsive_styles": "@media" in css,
        "keyboard_focus": ":focus" in css,
        "navigation": "nav" in page.tags and any(link.startswith("#") for link in page.links),
        "no_script_execution": not page.inline_scripts and not page.external_scripts,
        "no_remote_imports": "@import" not in css and "url(http" not in css,
    }
    return {"checks": checks, "passed": sum(checks.values()),
            "total": len(checks), "all_pass": all(checks.values()),
            "notice": "فحوص بنيوية للواجهة فقط، وليست قياسًا لجمالية التصميم أو أداء النموذج."}
