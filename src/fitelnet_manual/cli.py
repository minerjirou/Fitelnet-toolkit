"""PDF -> page Markdown and source-aware search, inspired by ix-toolkit/manualbook."""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from importlib.resources import files
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from fitelnet_ssh.cli import use_utf8

ATTEMPTS = 3
MAX_RETRY_DELAY = 30


def manifest() -> dict:
    return json.loads(
        files("fitelnet_manual").joinpath("manifest.json").read_text(encoding="utf-8")
    )


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(data)
        Path(name).replace(path)
    finally:
        if name:
            Path(name).unlink(missing_ok=True)


def download_pdf(url: str) -> bytes:
    if not url.startswith("https://www.furukawaelectric.com/fitelnet/"):
        raise ValueError("only the official FITELnet HTTPS source is supported")
    # URLs come from the bundled catalog and are checked above.
    request = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": "fitelnet-toolkit/0.1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        data = response.read()
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"not a PDF: {url}")
    return data


def retry_delay(attempt: int, error: urllib.error.HTTPError) -> int:
    if attempt == ATTEMPTS - 1 or error.code not in {429, 500, 502, 503, 504}:
        raise error
    delay = 2 ** (attempt + 1)
    retry = error.headers.get("Retry-After", "")
    if retry.isdigit():
        delay = max(delay, int(retry))
    if delay > MAX_RETRY_DELAY:
        raise ValueError("Retry-After exceeds 30 seconds; try later") from error
    return delay


def fetch_pdf(url: str, dest: Path, force: bool = False) -> None:
    if dest.is_file() and not force:
        if not dest.read_bytes().startswith(b"%PDF-"):
            raise ValueError(f"invalid cached PDF: {dest}; use --force")
        return
    for attempt in range(ATTEMPTS):
        try:
            data = download_pdf(url)
        except urllib.error.HTTPError as exc:  # noqa: PERF203 -- bounded network retry
            time.sleep(retry_delay(attempt, exc))
        except (urllib.error.URLError, TimeoutError):
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(2 ** (attempt + 1))
        else:
            atomic_write(dest, data)
            return


def build_document(root: Path, doc: dict, source: Path, url: str) -> int:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    reader = PdfReader(source)
    records = []
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        path = root / "f221" / doc["id"] / f"page-{number:04}.md"
        md = (
            f"# {doc['title']} - PDF page {number}\n\n"
            f"Source: {url}#page={number}\n\nSHA-256: {digest}\n\n"
            "Text extraction: diagrams, tables and spacing require checking the original PDF.\n\n"
            + text
            + "\n"
        )
        atomic_write(path, md.encode("utf-8"))
        records.append(
            {
                "document": doc["id"],
                "title": doc["title"],
                "page": number,
                "source": f"{url}#page={number}",
                "sha256": digest,
                "path": path.relative_to(root).as_posix(),
                "text": text,
            }
        )
    # Publish each document's index only after all its pages are complete.
    index = root / "f221" / doc["id"] / "index.json"
    atomic_write(index, json.dumps(records, ensure_ascii=False).encode("utf-8"))
    return len(records)


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def search(root: Path, query: str, doc: str | None, limit: int) -> list[dict]:
    needle = normalize(query)
    if not needle:
        raise ValueError("query must not be blank")
    matches = []
    for index in sorted((root / "f221").glob("*/index.json")):
        if doc and index.parent.name != doc:
            continue
        for record in json.loads(index.read_text(encoding="utf-8")):
            if needle in normalize(record["text"]):
                excerpt = next(
                    (line for line in record["text"].splitlines() if needle in normalize(line)),
                    record["text"][:240],
                )
                matches.append(
                    {k: v for k, v in record.items() if k != "text"} | {"excerpt": excerpt[:400]}
                )
                if len(matches) >= limit:
                    return matches
    return matches


def parse_args(argv: list[str] | None, catalog: dict) -> argparse.Namespace:
    ids = [doc["id"] for doc in catalog["documents"]]
    parser = argparse.ArgumentParser(prog="fitelnet-manual")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(
            os.environ.get("FITELNET_MANUALS", "~/.fitelnet-toolkit/manuals")
        ).expanduser(),
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("fetch", "build"):
        command = sub.add_parser(action)
        command.add_argument("--doc", choices=ids, action="append")
        command.add_argument(
            "--pdf-dir", type=Path, help="use local PDFs with manifest filenames; never download"
        )
        command.add_argument("--force", action="store_true", help="refresh downloaded PDFs")
    command = sub.add_parser("search")
    command.add_argument("query")
    command.add_argument("--doc", choices=ids)
    command.add_argument("--limit", type=int, default=10)
    command.add_argument("--json", action="store_true")
    command = sub.add_parser("page")
    command.add_argument("document", choices=ids)
    command.add_argument("number", type=int)
    return parser.parse_args(argv)


def fetch_or_build(args: argparse.Namespace, catalog: dict, root: Path) -> None:
    for doc in catalog["documents"]:
        if args.doc and doc["id"] not in args.doc:
            continue
        url = catalog["base_url"] + doc["file"]
        pdf = (args.pdf_dir or root / "pdf") / doc["file"]
        if args.pdf_dir:
            if not pdf.is_file():
                raise ValueError(f"local PDF missing: {pdf}")
        else:
            fetch_pdf(url, pdf, args.force)
        count = build_document(root, doc, pdf, url) if args.action == "build" else 0
        print(f"{doc['id']}: {count} pages indexed" if count else f"{doc['id']}: {pdf}", flush=True)


def execute(args: argparse.Namespace, catalog: dict, root: Path) -> int:
    if args.action in {"fetch", "build"}:
        fetch_or_build(args, catalog, root)
    elif args.action == "search":
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        if not list((root / "f221").glob("*/index.json")):
            raise ValueError("manual index missing; run fitelnet-manual build first")
        matches = search(root, args.query, args.doc, args.limit)
        if args.json:
            print(json.dumps(matches, ensure_ascii=False, indent=2))
        else:
            for hit in matches:
                print(f"{hit['document']} PDF p.{hit['page']}: {hit['excerpt']}\n{hit['source']}")
        return 0 if matches else 1
    else:
        if args.number < 1:
            raise ValueError("page number must be positive")
        index = root / "f221" / args.document / "index.json"
        records = json.loads(index.read_text(encoding="utf-8"))
        record = next((r for r in records if r["page"] == args.number), None)
        if record is None:
            raise ValueError("page not present in the current document index")
        path = root / record["path"]
        print(path.read_text(encoding="utf-8"))
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8(sys.stdout)
    use_utf8(sys.stderr)
    catalog = manifest()
    args = parse_args(argv, catalog)
    root = args.root.expanduser().resolve()
    try:
        return execute(args, catalog, root)
    except (OSError, ValueError, PdfReadError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; completed documents and cached PDFs retained", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
