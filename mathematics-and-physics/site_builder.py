"""Local, deterministic responsive website prototype generator.

This is a reliable template generator rather than a trained AI designer.
Output requires human review and is never automatically committed to Gitea.
"""
from html import escape

STYLES = {
    "professional": {"bg": "#0c1629", "surface": "#142540",
                     "accent": "#60a5fa", "text": "#eff6ff"},
    "light": {"bg": "#f6f8fc", "surface": "#ffffff",
              "accent": "#2563eb", "text": "#18243a"},
    "emerald": {"bg": "#071c1b", "surface": "#12312e",
                "accent": "#5eead4", "text": "#e6fffa"},
}
SECTIONS = {"features", "about", "portfolio", "contact"}
NAMES = {
    "features": "المميزات",
    "about": "من نحن",
    "portfolio": "الأعمال",
    "contact": "تواصل معنا",
}


def build_website(title: str, description: str, style: str,
                  sections: list[str]) -> dict:
    title, description = title.strip(), description.strip()
    if not 3 <= len(title) <= 90 or not 10 <= len(description) <= 500:
        raise ValueError("Invalid website title or description")
    if style not in STYLES or not 1 <= len(sections) <= 4:
        raise ValueError("Unknown website design configuration")
    if len(set(sections)) != len(sections) or any(s not in SECTIONS for s in sections):
        raise ValueError("Invalid or duplicate sections")
    title_html = escape(title)
    desc_html = escape(description)
    navigation = "\n".join(
        f'<a href="#{part}">{NAMES[part]}</a>' for part in sections)
    content = "\n".join(
        '<section class="section" id="' + part + '">'
        '<div class="card"><span class="eyebrow">' + str(i + 1).zfill(2) +
        '</span><h2>' + NAMES[part] + '</h2><p>' +
        ('اكتب هنا التفاصيل الخاصة بهذا القسم من موقعك.' if part != "contact"
         else 'أضف وسيلة تواصل معتمدة وآمنة قبل نشر الموقع.') +
        '</p></div></section>' for i, part in enumerate(sections))
    page = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="{desc_html}">
  <title>{title_html}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <a class="skip" href="#main">الانتقال إلى المحتوى</a>
  <header class="header">
    <div class="container head-inner"><strong class="logo">{title_html}</strong>
    <nav aria-label="التنقل الرئيسي">{navigation}</nav></div>
  </header>
  <main id="main">
    <section class="hero container">
      <p class="eyebrow">موقع مصمم محليًا</p>
      <h1>{title_html}</h1>
      <p class="lead">{desc_html}</p>
      <a class="cta" href="#{sections[0]}">اكتشف المزيد</a>
    </section>
    <div class="container">{content}</div>
  </main>
  <footer class="footer"><div class="container">© {title_html} — نموذج أولي يحتاج مراجعة.</div></footer>
</body></html>
"""
    theme = STYLES[style]
    css = """*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;font-family:system-ui,'Segoe UI',Tahoma,sans-serif;background:var(--bg);color:var(--text);line-height:1.75}
:root{--bg:BG;--surface:SURFACE;--accent:ACCENT;--text:TEXT}
a{color:inherit}.container{max-width:1160px;padding:0 22px;margin:auto}
.skip{position:absolute;top:-100px;background:var(--accent);color:#081323;padding:8px}
.skip:focus{top:0}.header{border-bottom:1px solid var(--accent)}
.head-inner{display:flex;gap:25px;align-items:center;justify-content:space-between;min-height:80px}
.logo{font-size:1.4rem}.header nav{display:flex;gap:17px;flex-wrap:wrap}
.header nav a{text-decoration:none}.header nav a:hover,.header nav a:focus{text-decoration:underline}
.hero{padding-top:100px;padding-bottom:110px}.hero h1{font-size:clamp(2.4rem,6vw,5.2rem);line-height:1.2;max-width:850px}
.lead{font-size:1.2rem;max-width:740px;opacity:.88}.eyebrow{color:var(--accent);font-weight:700;letter-spacing:.08em}
.cta{display:inline-block;margin-top:26px;text-decoration:none;color:var(--bg);background:var(--accent);border-radius:10px;padding:12px 24px;font-weight:800}
.section{padding:24px 0 40px;scroll-margin-top:40px}
.card{background:var(--surface);border:1px solid var(--accent);border-radius:18px;padding:clamp(24px,5vw,60px)}
.card h2{font-size:clamp(1.5rem,3vw,2.2rem)}.footer{padding:45px 0;border-top:1px solid var(--accent);margin-top:55px}
a:focus-visible{outline:3px solid var(--accent);outline-offset:5px}
@media(max-width:650px){.head-inner{align-items:flex-start;flex-direction:column;padding:20px 22px}.hero{padding-top:65px;padding-bottom:65px}}
"""
    for key, value in (("BG", theme["bg"]), ("SURFACE", theme["surface"]),
                       ("ACCENT", theme["accent"]), ("TEXT", theme["text"])):
        css = css.replace(key, value)
    return {"files": [{"path": "index.html", "content": page},
                      {"path": "style.css", "content": css}],
            "mode": "deterministic-scaffold",
            "notice": "قالب مبدئي متجاوب، وليس تصميمًا مبتكرًا بواسطة نموذج مدرب. راجع النصوص وإمكانية الوصول قبل النشر.",
            "requires_approval": True}
