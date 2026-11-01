"""Site rules: one GitHub link, no broken internal links, required pages exist."""
import pathlib, re, sys

root = pathlib.Path(__file__).parent
pages = sorted(root.rglob("*.html"))
errors, github = [], 0
for page in pages:
    html = page.read_text(encoding="utf-8")
    github += html.count("github.com")
    for href in re.findall(r'(?:href|src)="(/[^"#?]*)', html):
        target = root / href.lstrip("/")
        if not (target.is_file() or (target / "index.html").is_file()):
            errors.append(f"{page.relative_to(root)}: broken link {href}")
for required in ("index.html", "docs/index.html", "privacy/index.html", "terms/index.html"):
    if not (root / required).is_file():
        errors.append(f"missing {required}")
if github != 1:
    errors.append(f"github.com appears {github} times; must be exactly once (the View on GitHub button)")
print("\n".join(errors) or "ok")
sys.exit(1 if errors else 0)
