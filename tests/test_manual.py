import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from fitelnet_manual.cli import build_document, fetch_pdf, main, search

URL = "https://www.furukawaelectric.com/fitelnet/test.pdf"


class ManualTests(unittest.TestCase):
    def test_pdf_to_markdown_provenance_and_empty_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "test.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.write(pdf)
            count = build_document(root, {"id": "config", "title": "Test"}, pdf, URL)
            self.assertEqual(count, 1)
            records = json.loads((root / "f221/config/index.json").read_text(encoding="utf-8"))
            self.assertEqual(records[0]["source"], URL + "#page=1")
            self.assertEqual(len(records[0]["sha256"]), 64)
            self.assertIn("SHA-256:", (root / records[0]["path"]).read_text(encoding="utf-8"))

    def test_search_ignores_pdf_spacing_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "f221/operation/index.json"
            index.parent.mkdir(parents=True)
            index.write_text(
                json.dumps(
                    [
                        {
                            "text": "show lte-module\n status",
                            "page": 578,
                            "source": URL,
                            "document": "operation",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            hit = search(root, "SHOW lte-module status", "operation", 1)
            self.assertEqual(hit[0]["page"], 578)
            self.assertEqual(hit[0]["source"], URL)
            self.assertEqual(search(root, "missing", None, 10), [])

    def test_cache_reused_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "test.pdf"
            dest.write_bytes(b"%PDF-old")
            with patch("fitelnet_manual.cli.download_pdf") as download:
                fetch_pdf(URL, dest)
                download.assert_not_called()

    def test_failed_refresh_preserves_previous_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "test.pdf"
            dest.write_bytes(b"%PDF-old")
            with (
                patch(
                    "fitelnet_manual.cli.download_pdf", side_effect=urllib.error.URLError("offline")
                ),
                patch("fitelnet_manual.cli.time.sleep"),
                self.assertRaises(urllib.error.URLError),
            ):
                fetch_pdf(URL, dest, force=True)
            self.assertEqual(dest.read_bytes(), b"%PDF-old")

    def test_transient_failure_retried_then_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "test.pdf"
            with (
                patch(
                    "fitelnet_manual.cli.download_pdf",
                    side_effect=[urllib.error.URLError("offline"), b"%PDF-new"],
                ) as download,
                patch("fitelnet_manual.cli.time.sleep"),
            ):
                fetch_pdf(URL, dest)
            self.assertEqual(download.call_count, 2)
            self.assertEqual(dest.read_bytes(), b"%PDF-new")

    def test_cli_reports_missing_index(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()) as errors,
        ):
            result = main(["--root", tmp, "search", "commit"])
            self.assertEqual(result, 2)
            self.assertIn("index missing", errors.getvalue())
