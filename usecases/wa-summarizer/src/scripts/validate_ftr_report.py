#!/usr/bin/env python3
"""Validate deterministic FTR reports against their source JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import generate_ftr_report


REQUIRED_SECTION_IDS = generate_ftr_report.SECTION_IDS
DEFECTIVE_INDICATORS = (
    "context length constraints",
    "remaining findings have been summarized",
    "APPENDIX_FINDINGS_END",
)
KNOWN_INVENTED_PLACEHOLDERS = (
    "company.com",
    "555-",
    "AKIAOLD",
    "KEY_ID",
    "ANALYZER_ARN",
    "john.doe",
)
SECRET_PATTERNS = (
    re.compile(r"\bA(?:KIA|SIA)[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\baws_secret_access_key\b"),
    re.compile(r"(?i)\baws_session_token\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
)


class ReportHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.id_text: dict[str, str] = {}
        self._capture_id_stack: list[str] = []
        self.appendix_entries = 0
        self.tables: dict[str, list[list[str]]] = {}
        self._table_id: str | None = None
        self._in_row = False
        self._in_cell = False
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        element_id = attr.get("id")
        if element_id:
            self.ids.append(element_id)
            self._capture_id_stack.append(element_id)
        else:
            self._capture_id_stack.append("")

        if attr.get("data-appendix-entry") == "true":
            self.appendix_entries += 1

        if tag == "table" and element_id:
            self._table_id = element_id
            self.tables.setdefault(element_id, [])
        elif tag == "tr" and self._table_id:
            self._in_row = True
            self._current_row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            text = " ".join("".join(self._current_cell).split())
            self._current_row.append(text)
            self._current_cell = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._table_id and self._current_row:
                self.tables.setdefault(self._table_id, []).append(self._current_row)
            self._current_row = []
            self._in_row = False
        elif tag == "table":
            self._table_id = None

        if self._capture_id_stack:
            self._capture_id_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)
        for element_id in self._capture_id_stack:
            if element_id:
                self.id_text[element_id] = self.id_text.get(element_id, "") + data


def parse_report(path: Path) -> tuple[str, ReportHTMLParser]:
    text = path.read_text(encoding="utf-8")
    parser = ReportHTMLParser()
    parser.feed(text)
    return text, parser


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def int_text(parser: ReportHTMLParser, element_id: str) -> int | None:
    raw = parser.id_text.get(element_id, "").strip()
    match = re.search(r"-?\d+", raw)
    if not match:
        return None
    return int(match.group(0))


def validate_hash(input_path: Path, parser: ReportHTMLParser, errors: list[str]) -> None:
    actual_hash = generate_ftr_report.sha256_file(input_path)
    reported_hash = " ".join(parser.id_text.get("input-sha256", "").split())
    require(reported_hash == actual_hash, "input JSON SHA-256 shown in report does not match actual input", errors)


def validate_required_sections(parser: ReportHTMLParser, errors: list[str]) -> None:
    id_counts = {item: parser.ids.count(item) for item in set(parser.ids)}
    for section_id in REQUIRED_SECTION_IDS:
        require(id_counts.get(section_id, 0) == 1, f"required section id {section_id!r} must appear exactly once", errors)
    duplicates = sorted(item for item, count in id_counts.items() if count > 1)
    require(not duplicates, f"HTML id attributes must be unique; duplicates: {', '.join(duplicates)}", errors)


def validate_appendix(parser: ReportHTMLParser, counts: dict[str, Any], errors: list[str]) -> None:
    expected = counts["non_compliant_check_findings"]
    require(parser.appendix_entries == expected, f"appendix entry count {parser.appendix_entries} != computed finding count {expected}", errors)
    shown = int_text(parser, "appendix-count")
    require(shown == expected, f"displayed appendix count {shown} != computed finding count {expected}", errors)


def validate_category_totals(parser: ReportHTMLParser, counts: dict[str, Any], errors: list[str]) -> None:
    rows = parser.tables.get("category-summary-table", [])
    expected_rows = counts["category_rows"]
    data_rows = [row for row in rows if row and row[0] not in ("Category", "Total")]
    require(len(data_rows) == len(expected_rows), f"category row count {len(data_rows)} != computed category count {len(expected_rows)}", errors)

    by_name = {row["category"]: row for row in expected_rows}
    for table_row in data_rows:
        require(len(table_row) == 9, f"category table row has {len(table_row)} cells instead of 9: {table_row}", errors)
        if len(table_row) != 9:
            continue
        name = table_row[0]
        expected = by_name.get(name)
        require(expected is not None, f"unexpected category row in report: {name}", errors)
        if not expected:
            continue
        numbers = [int(value) for value in table_row[1:]]
        expected_numbers = [
            expected["requirement_count"],
            expected["compliant_requirements"],
            expected["need_attention_requirements"],
            expected["unavailable_requirements"],
            expected["row_total_requirements"],
            expected["evaluated_check_instances"],
            expected["non_compliant_check_findings"],
            expected["non_compliant_resource_references"],
        ]
        require(numbers == expected_numbers, f"category row {name!r} numbers {numbers} != computed {expected_numbers}", errors)
        require(numbers[1] + numbers[2] + numbers[3] == numbers[4], f"category row {name!r} requirement arithmetic does not reconcile", errors)
        require(numbers[0] == numbers[4], f"category row {name!r} requirement row total does not match status total", errors)

    expected_totals = {
        "category-total-requirement-rows": counts["requirement_count"],
        "category-total-compliant": counts["summary"]["compliant_requirements"],
        "category-total-need-attention": counts["summary"]["need_attention_requirements"],
        "category-total-unavailable": counts["summary"]["unavailable_requirements"],
        "category-total-reconciled": counts["summary"]["total_requirements"],
        "category-total-evaluated-checks": counts["evaluated_check_instances"],
        "category-total-findings": counts["non_compliant_check_findings"],
        "category-total-resource-refs": counts["non_compliant_resource_references"],
    }
    for element_id, expected_value in expected_totals.items():
        actual = int_text(parser, element_id)
        require(actual == expected_value, f"{element_id} value {actual} != computed {expected_value}", errors)


def validate_severity_totals(parser: ReportHTMLParser, counts: dict[str, Any], errors: list[str]) -> None:
    rows = parser.tables.get("severity-summary-table", [])
    data_rows = [row for row in rows if row and row[0] != "Severity"]
    label_to_key = {
        generate_ftr_report.normalize_severity("H"): "H",
        generate_ftr_report.normalize_severity("M"): "M",
        generate_ftr_report.normalize_severity("L"): "L",
        generate_ftr_report.normalize_severity(""): "Not provided",
    }
    actual: dict[str, int] = {}
    for row in data_rows:
        require(len(row) == 2, f"severity row has {len(row)} cells instead of 2: {row}", errors)
        if len(row) == 2:
            key = label_to_key.get(row[0], row[0])
            actual[key] = int(row[1])
    expected = counts["severity_totals"]
    require(actual == expected, f"severity totals {actual} != computed {expected}", errors)
    require(sum(actual.values()) == counts["non_compliant_check_findings"], "severity totals do not sum to non-compliant finding count", errors)


def validate_forbidden_text(text: str, errors: list[str]) -> None:
    lowered = text.lower()
    for indicator in DEFECTIVE_INDICATORS:
        require(indicator.lower() not in lowered, f"defective-generation indicator found: {indicator}", errors)
    for placeholder in KNOWN_INVENTED_PLACEHOLDERS:
        require(placeholder.lower() not in lowered, f"known invented placeholder found: {placeholder}", errors)
    require(text.count("APPENDIX_FINDINGS_START") <= 1, "duplicate APPENDIX_FINDINGS_START boundary markers found", errors)
    require(text.count("APPENDIX_FINDINGS_END") <= 1, "duplicate APPENDIX_FINDINGS_END boundary markers found", errors)
    for pattern in SECRET_PATTERNS:
        require(not pattern.search(text), f"secret-like value found by pattern: {pattern.pattern}", errors)


def build_audit_manifest(
    input_path: Path,
    report_path: Path,
    counts: dict[str, Any],
    validation_result: str,
) -> dict[str, Any]:
    return {
        "input_path": str(input_path),
        "input_sha256": generate_ftr_report.sha256_file(input_path),
        "output_path": str(report_path),
        "summary_counts": {
            "ftr_requirement_summary_outcomes": counts["summary"],
            "ftr_requirement_rows": counts["requirement_count"],
            "evaluated_check_instances": counts["evaluated_check_instances"],
            "non_compliant_check_finding_instances": counts["non_compliant_check_findings"],
            "non_compliant_resource_references": counts["non_compliant_resource_references"],
            "severity_totals_check_level_findings": counts["severity_totals"],
        },
        "category_count": counts["category_count"],
        "appendix_entry_count": counts["non_compliant_check_findings"],
        "validation_result": validation_result,
        "generator": generate_ftr_report.GENERATOR_VERSION,
    }


def validate(input_path: Path, report_path: Path) -> list[str]:
    errors: list[str] = []
    require(report_path.exists(), f"generated report does not exist: {report_path}", errors)
    if errors:
        return errors
    require(report_path.stat().st_size > 0, f"generated report is empty: {report_path}", errors)
    data = generate_ftr_report.load_json(input_path)
    counts = generate_ftr_report.compute_counts(data)
    text, parser = parse_report(report_path)

    validate_hash(input_path, parser, errors)
    validate_required_sections(parser, errors)
    validate_appendix(parser, counts, errors)
    validate_category_totals(parser, counts, errors)
    validate_severity_totals(parser, counts, errors)
    validate_forbidden_text(text, errors)
    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate deterministic FTR HTML report output.")
    parser.add_argument("--input", required=True, type=Path, help="Path to source ftr_results JSON.")
    parser.add_argument("--report", required=True, type=Path, help="Path to generated HTML report.")
    parser.add_argument("--audit-output", type=Path, help="Optional path to write compact audit JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    errors = validate(args.input, args.report)
    validation_result = "passed" if not errors else "failed"
    if args.audit_output:
        data = generate_ftr_report.load_json(args.input)
        counts = generate_ftr_report.compute_counts(data)
        manifest = build_audit_manifest(args.input, args.report, counts, validation_result)
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"validation passed: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
