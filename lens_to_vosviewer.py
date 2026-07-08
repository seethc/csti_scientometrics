#!/usr/bin/env python3
"""Convert a Lens.org patent CSV export into raw VOSviewer corpus inputs.

This script intentionally does not calculate a co-occurrence network, layout, or
clusters. VOSviewer should do those steps itself from the exported corpus.
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_TEXT_FIELDS = ["Title", "Abstract"]
DEFAULT_SCORE_FIELDS = [
    ("score<Pub. year>", "Publication Year", "int"),
    ("score<Application year>", "Application Date", "year"),
    ("score<Earliest priority year>", "Earliest Priority Date", "year"),
    ("score<Cited by patents>", "Cited by Patent Count", "int"),
    ("score<Cites patents>", "Cites Patent Count", "int"),
    ("score<Simple family size>", "Simple Family Size", "int"),
    ("score<Extended family size>", "Extended Family Size", "int"),
    ("score<NPL citations>", "NPL Citation Count", "int"),
]
BOILERPLATE_TERMS = [
    "apparatus",
    "configured",
    "device",
    "devices",
    "embodiment",
    "embodiments",
    "example",
    "first",
    "method",
    "methods",
    "plurality",
    "provided",
    "second",
    "system",
    "systems",
    "wherein",
]


def clean_text(value: str) -> str:
    value = value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def split_multi(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(";;") if part.strip()]


def to_int(value: Any) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def year_from_date(value: str | None) -> int:
    if not value:
        return 0
    text = str(value).strip()
    if re.match(r"^\d{4}$", text):
        return int(text)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).year
        except ValueError:
            pass
    match = re.search(r"(19|20)\d{2}", text)
    return int(match.group(0)) if match else 0


def score_value(row: dict[str, str], field: str, kind: str) -> int:
    if kind == "year":
        return year_from_date(row.get(field))
    return to_int(row.get(field))


def row_text(row: dict[str, str], fields: list[str], append_classes: bool) -> str:
    parts = [row.get(field, "") for field in fields]
    if append_classes:
        parts.extend(split_multi(row.get("CPC Classifications")))
        parts.extend(split_multi(row.get("IPCR Classifications")))
    return clean_text(". ".join(part for part in parts if part))


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8-sig")


def convert(args: argparse.Namespace) -> dict[str, Path | int]:
    csv_path = Path(args.csv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or csv_path.stem
    text_fields = args.text_fields or DEFAULT_TEXT_FIELDS

    corpus_lines: list[str] = []
    score_rows: list[list[int]] = []
    metadata_rows: list[dict[str, str]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"No header row found in {csv_path}")

        for index, row in enumerate(reader, start=1):
            text = row_text(row, text_fields, args.append_classifications)
            if not text and args.skip_empty_text:
                continue
            corpus_lines.append(text)
            score_rows.append([
                score_value(row, source_field, kind)
                for _score_header, source_field, kind in DEFAULT_SCORE_FIELDS
            ])
            metadata_rows.append({
                "corpus_line": str(len(corpus_lines)),
                "source_row": str(index),
                "display_key": row.get("Display Key", ""),
                "lens_id": row.get("Lens ID", ""),
                "title": row.get("Title", ""),
                "publication_year": row.get("Publication Year", ""),
                "jurisdiction": row.get("Jurisdiction", ""),
                "document_type": row.get("Document Type", ""),
                "legal_status": row.get("Legal Status", ""),
                "applicants": row.get("Applicants", ""),
                "url": row.get("URL", ""),
            })

    corpus_path = out_dir / f"{prefix}_vos_corpus.txt"
    scores_path = out_dir / f"{prefix}_vos_scores.txt"
    metadata_path = out_dir / f"{prefix}_vos_metadata.csv"
    instructions_path = out_dir / f"{prefix}_vos_README.txt"

    write_lines(corpus_path, corpus_lines)

    with scores_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow([header for header, _field, _kind in DEFAULT_SCORE_FIELDS])
        writer.writerows(score_rows)

    with metadata_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "corpus_line",
            "source_row",
            "display_key",
            "lens_id",
            "title",
            "publication_year",
            "jurisdiction",
            "document_type",
            "legal_status",
            "applicants",
            "url",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(metadata_rows)

    thesaurus_path = None
    if args.write_thesaurus:
        thesaurus_path = out_dir / f"{prefix}_vos_thesaurus_terms.txt"
        with thesaurus_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(["label", "replace by"])
            for term in BOILERPLATE_TERMS:
                writer.writerow([term, ""])

    instructions = [
        "Lens patent CSV to VOSviewer conversion",
        "",
        "Use these files in VOSviewer to let VOSviewer calculate term extraction, co-occurrence, layout, and clustering.",
        "",
        "Recommended VOSviewer workflow:",
        "1. Create > Create a map based on text data.",
        "2. Choose the corpus file generated here.",
        "3. Choose the scores file generated here if you want overlay scores such as publication year.",
        "4. Use binary counting if you want each patent to count once per term.",
        "5. Choose your minimum occurrence threshold and number of terms inside VOSviewer.",
        "6. Use the metadata CSV only outside VOSviewer to trace corpus lines back to patents.",
        "",
        f"Corpus: {corpus_path.name}",
        f"Scores: {scores_path.name}",
        f"Metadata: {metadata_path.name}",
    ]
    if thesaurus_path:
        instructions.append(f"Optional thesaurus: {thesaurus_path.name}")
    write_lines(instructions_path, instructions)

    result: dict[str, Path | int] = {
        "records": len(corpus_lines),
        "corpus": corpus_path,
        "scores": scores_path,
        "metadata": metadata_path,
        "instructions": instructions_path,
    }
    if thesaurus_path:
        result["thesaurus"] = thesaurus_path
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Lens.org patent CSV export to raw VOSviewer corpus/scores files."
    )
    parser.add_argument("--csv", required=True, help="Path to the Lens.org patent CSV export.")
    parser.add_argument("--out-dir", default="vosviewer_exports", help="Output directory.")
    parser.add_argument("--prefix", default="", help="Output file prefix. Defaults to the CSV stem.")
    parser.add_argument(
        "--text-fields",
        nargs="+",
        default=DEFAULT_TEXT_FIELDS,
        help="CSV fields to concatenate into each VOSviewer corpus line.",
    )
    parser.add_argument(
        "--append-classifications",
        action="store_true",
        help="Append CPC/IPCR codes to the corpus text. Leave off for a cleaner title/abstract term map.",
    )
    parser.add_argument(
        "--write-thesaurus",
        action="store_true",
        help="Also write an optional VOSviewer thesaurus file that ignores common patent boilerplate terms.",
    )
    parser.add_argument(
        "--skip-empty-text",
        action="store_true",
        help="Skip rows where the selected text fields are empty.",
    )
    return parser.parse_args()


def main() -> int:
    result = convert(parse_args())
    print(f"Converted {result['records']} patent records")
    for key, value in result.items():
        if key != "records":
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
