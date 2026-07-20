import io
import json
from pathlib import Path

import requests
from pypdf import PdfReader, PdfWriter

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
SRC_PDF = PROJECT_ROOT / "data" / "2026-1학기_수강편람.pdf"
OUTPUT_DIR = PROJECT_ROOT / "cache" / "output"
SECRETS_PATH = PROJECT_ROOT / "secrets.json"

START_PAGE, END_PAGE = 3, 70  # 1-indexed, inclusive, original PDF page numbers

API_URL = "https://api.upstage.ai/v1/document-digitization"


def load_api_key() -> str:
    secrets = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    return secrets["UPSTAGE_API_KEY"]


def build_subset_pdf() -> bytes:
    reader = PdfReader(str(SRC_PDF))
    writer = PdfWriter()
    for i in range(START_PAGE - 1, END_PAGE):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def call_document_parse(pdf_bytes: bytes, api_key: str) -> dict:
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        files={"document": ("subset.pdf", pdf_bytes, "application/pdf")},
        data={
            "model": "document-parse",
            "output_formats": '["markdown"]',
        },
        timeout=600,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    api_key = load_api_key()
    subset_pdf_bytes = build_subset_pdf()
    result = call_document_parse(subset_pdf_bytes, api_key)

    (OUTPUT_DIR / "raw_response_p3_70.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    document_md = result["content"]["markdown"]
    (OUTPUT_DIR / "document.md").write_text(document_md, encoding="utf-8")

    print(f"Saved {OUTPUT_DIR / 'document.md'} ({len(document_md)} chars)")


if __name__ == "__main__":
    main()
