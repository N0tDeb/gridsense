"""Check the actual source-release inventory, local links and repository hygiene."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from release_support import selected_files

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "SETUP.md",
    "DEVELOPMENT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "NOTICE",
    ".gitignore",
    ".gitattributes",
    "pyproject.toml",
    "requirements-dev.lock",
    "backend/gridsense/api.py",
    "backend/gridsense/cli.py",
    "backend/gridsense/circuits/feeder.json",
    "backend/gridsense/circuits/ieee13/model.dss",
    "backend/gridsense/circuits/ieee13/License.txt",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/src/App.tsx",
    "frontend/THIRD_PARTY_NOTICES.txt",
    ".github/workflows/checks.yml",
    "docs/API.md",
    "docs/ARCHITECTURE.md",
    "docs/DATA_MODEL.md",
    "docs/REFERENCE_VALIDATION.md",
    "docs/VERIFICATION.md",
)
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
}
PRIVATE_PATH = re.compile(r"/(?:workspace|Users|home|root|tmp|opt)/[^\s\"'<>),]+")
MERGE_MARKER = re.compile(r"^(?:<{7} |={7}$|>{7} )", re.MULTILINE)
LINK = re.compile(r"!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".txt",
    ".toml",
    ".lock",
    ".yml",
    ".yaml",
    ".ts",
    ".tsx",
    ".mjs",
    ".css",
    ".html",
    ".dss",
    ".csv",
    ".svg",
}


def markdown_text(text):
    """Ignore fenced examples when checking actual rendered document links."""
    return re.sub(r"(?ms)^```[^\n]*\n.*?^```[^\n]*$", "", text)


def anchors(text):
    result = set()
    seen = {}
    for title in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", markdown_text(text)):
        slug = re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def check_links(root, documents, delivered):
    errors = []
    checked = 0
    root = Path(root).resolve()
    for document in documents:
        for raw in LINK.findall(markdown_text(document.read_text(encoding="utf-8"))):
            parts = urlsplit(raw)
            if parts.scheme or parts.netloc:
                continue
            checked += 1
            target = (document.parent / unquote(parts.path)).resolve() if parts.path else document
            label = document.relative_to(root).as_posix()
            if not target.is_relative_to(root) or target not in delivered:
                errors.append(f"{label}: local link is missing or outside the release: {raw}")
            elif parts.fragment and target.suffix == ".md":
                if unquote(parts.fragment) not in anchors(target.read_text(encoding="utf-8")):
                    errors.append(f"{label}: missing Markdown heading: {raw}")
    return checked, errors


def scan_text(path, root):
    """Return labels and locations only; never echo suspected credential values."""
    errors = []
    text = path.read_text(encoding="utf-8", errors="replace")
    label = path.relative_to(root).as_posix()
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            errors.append(f"{label}: suspected {name}")
    if PRIVATE_PATH.search(text):
        errors.append(f"{label}: machine-specific absolute path")
    if MERGE_MARKER.search(text):
        errors.append(f"{label}: unresolved merge marker")
    return errors


def inspect(root):
    root = Path(root).resolve()
    paths = list(selected_files(root))
    delivered = {path.resolve() for path in paths}
    names = {path.relative_to(root).as_posix() for path in paths}
    errors = ["Missing required source file: " + name for name in REQUIRED if name not in names]
    for folder in ("backend/tests", "frontend/tests", "examples", "experiments/protocols"):
        if not any(name.startswith(folder + "/") for name in names):
            errors.append("Missing required source directory contents: " + folder)
    documents = [path for path in paths if path.suffix == ".md"]
    link_count, link_errors = check_links(root, documents, delivered)
    errors.extend(link_errors)
    for path in paths:
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", "NOTICE"}:
            errors.extend(scan_text(path, root))
    return {
        "passed": not errors,
        "source_files": len(paths),
        "markdown_documents": len(documents),
        "local_links_checked": link_count,
        "secret_scan": "known credential/private-key patterns; not a comprehensive security audit",
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = inspect(args.root)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
