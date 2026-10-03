"""Download GitHub repos and keep only the source files of one language.

Usage: python fetch_corpus.py [--lang python] [--out DIR] [--repos owner/name ...]
Each repo lands in DIR/<owner>__<name>/ (DIR defaults to corpus/raw for Python and
corpus/<lang> otherwise). Repos already present are skipped. Only Python has a default repo
list; for other languages pass --repos.
"""
import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

from count import LANGUAGES

# Mix of web, CLI, data, tooling and app code so no single style dominates.
REPOS = [
    "psf/requests", "pallets/flask", "pallets/click", "pallets/jinja", "django/django",
    "fastapi/fastapi", "fastapi/typer", "encode/httpx", "aio-libs/aiohttp",
    "pydantic/pydantic", "python-attrs/attrs", "sqlalchemy/sqlalchemy",
    "Textualize/rich", "Textualize/textual", "tqdm/tqdm", "httpie/cli",
    "psf/black", "pytest-dev/pytest", "pypa/pip", "python-poetry/poetry",
    "pandas-dev/pandas", "scikit-learn/scikit-learn", "streamlit/streamlit",
    "scrapy/scrapy", "celery/celery", "ansible/ansible", "boto/boto3",
    "yt-dlp/yt-dlp", "home-assistant/core",
]

SKIP_PARTS = {"vendor", "_vendor", "vendored", "migrations", "node_modules", "build", "dist"}
MAX_FILE_BYTES = 300_000  # generated tables and fixtures are usually bigger


def fetch(repo: str, out: Path, extensions: tuple[str, ...]) -> None:
    dest = out / repo.replace("/", "__")
    if dest.exists():
        print(f"skip {repo} (already fetched)")
        return
    url = f"https://github.com/{repo}/archive/HEAD.zip"
    print(f"fetch {repo} ...", end=" ", flush=True)
    with urllib.request.urlopen(url, timeout=300) as resp:
        data = resp.read()
    kept = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts[1:]  # drop the "<repo>-<sha>/" root
            if (not parts or info.is_dir() or not info.filename.endswith(extensions)
                    or info.file_size > MAX_FILE_BYTES or SKIP_PARTS & set(parts)):
                continue
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            kept += 1
    print(f"{kept} files, {len(data) / 1e6:.1f} MB zip")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", choices=list(LANGUAGES), default="python")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--repos", nargs="+")
    args = ap.parse_args()
    if args.repos is None and args.lang != "python":
        ap.error(f"pass --repos for {args.lang}; only Python has a default list")
    out = args.out or Path("corpus/raw" if args.lang == "python" else f"corpus/{args.lang}")
    out.mkdir(parents=True, exist_ok=True)
    for repo in args.repos or REPOS:
        try:
            fetch(repo, out, LANGUAGES[args.lang].extensions)
        except Exception as exc:  # one bad repo shouldn't stop the rest
            print(f"FAILED: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
