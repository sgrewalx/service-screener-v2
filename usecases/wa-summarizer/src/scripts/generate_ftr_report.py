#!/usr/bin/env python3
"""Deterministic FTR HTML report generator.

Count semantics used by this generator:
- FTR requirement outcomes are the entries in framework.ftr.categories. Their
  complianceStatus values are summarized as Compliant, Need Attention, and
  Not available.
- Evaluated check instances are individual objects in each category's checks
  array. A requirement with no checks is counted as an unavailable requirement,
  not as an evaluated check.
- Non-compliant finding instances are check-level instances where
  status == "not_compliant". Appendix entries are one-for-one with these
  check-level finding instances.
- Resource-level non-compliant references are the resource strings listed under
  each non-compliant check. They are reported separately and are not appendix
  entry units.
- Category groups are distinct categoryName values.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Iterable


SCRIPT_RELATIVE_PATH = "usecases/wa-summarizer/src/scripts/generate_ftr_report.py"
GENERATOR_VERSION = f"{SCRIPT_RELATIVE_PATH}:2"
NOT_PROVIDED = "Not provided in source data"

STATUS_LABELS = {
    "compliant": "Compliant",
    "not_compliant": "Non-compliant",
}

REQUIREMENT_STATUS_LABELS = {
    "Compliant": "Compliant",
    "Need Attention": "Need Attention",
    "Not available": "Not Available",
}

SEVERITY_LABELS = {
    "H": "High",
    "M": "Medium",
    "L": "Low",
}

SECTION_IDS = (
    "report-metadata",
    "metrics",
    "count-semantics",
    "category-summary",
    "severity-summary",
    "appendix",
    "remediation-safety",
)


@dataclass(frozen=True)
class Finding:
    index: int
    category: str
    rule_id: str
    check_id: str
    title: str
    status: str
    criticality: str
    wa_pillar: str
    service: str
    description: str
    resources: tuple[str, ...]
    references: tuple[str, ...]
    remediation: str
    commands: tuple[str, ...]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_ftr(data: dict[str, Any]) -> dict[str, Any]:
    try:
        ftr = data["framework"]["ftr"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Input JSON must contain framework.ftr") from exc
    if not isinstance(ftr, dict):
        raise ValueError("framework.ftr must be an object")
    if not isinstance(ftr.get("categories"), list):
        raise ValueError("framework.ftr.categories must be an array")
    if not isinstance(ftr.get("summary"), dict):
        raise ValueError("framework.ftr.summary must be an object")
    return ftr


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def as_text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(as_text(item) for item in value if as_text(item))


def normalize_status(status: str) -> str:
    return STATUS_LABELS.get(status, status or NOT_PROVIDED)


def normalize_requirement_status(status: str) -> str:
    return REQUIREMENT_STATUS_LABELS.get(status, status or NOT_PROVIDED)


def normalize_severity(value: str) -> str:
    if not value:
        return NOT_PROVIDED
    label = SEVERITY_LABELS.get(value, value)
    if label == value:
        return label
    return f"{label} ({value})"


def extract_source_commands(check: dict[str, Any]) -> tuple[str, ...]:
    """Return commands only when explicit command fields exist in source JSON.

    The current FTR JSON does not expose a command field. This deliberately
    avoids synthesizing AWS CLI commands from descriptions or references.
    """

    commands: list[str] = []
    for key in ("commands", "remediationCommands", "cliCommands"):
        raw = check.get(key)
        if isinstance(raw, str) and raw.strip():
            commands.append(raw.strip())
        elif isinstance(raw, list):
            commands.extend(as_text(item) for item in raw if as_text(item))
    return tuple(commands)


def iter_checks(categories: Iterable[dict[str, Any]]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for category in categories:
        checks = category.get("checks")
        if not isinstance(checks, list):
            continue
        for check in checks:
            if isinstance(check, dict):
                yield category, check


def build_findings(categories: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for category, check in iter_checks(categories):
        if check.get("status") != "not_compliant":
            continue
        findings.append(
            Finding(
                index=len(findings) + 1,
                category=as_text(category.get("categoryName")) or NOT_PROVIDED,
                rule_id=as_text(category.get("ruleId")) or NOT_PROVIDED,
                check_id=as_text(check.get("checkId")) or NOT_PROVIDED,
                title=as_text(check.get("shortDescription")) or NOT_PROVIDED,
                status=as_text(check.get("status")) or NOT_PROVIDED,
                criticality=as_text(check.get("criticality")) or "",
                wa_pillar=as_text(check.get("waRelatedPillar")) or NOT_PROVIDED,
                service=as_text(check.get("service")) or NOT_PROVIDED,
                description=as_text(check.get("extendedDescription")) or NOT_PROVIDED,
                resources=as_text_tuple(check.get("resources")),
                references=as_text_tuple(category.get("reference")),
                remediation=as_text(check.get("remediation")) or NOT_PROVIDED,
                commands=extract_source_commands(check),
            )
        )
    return findings


def compute_counts(data: dict[str, Any]) -> dict[str, Any]:
    ftr = get_ftr(data)
    categories = ftr["categories"]
    summary = ftr["summary"]
    findings = build_findings(categories)
    requirement_status = Counter(as_text(c.get("complianceStatus")) or "<missing>" for c in categories)
    check_status = Counter()
    severity = Counter()
    all_check_count = 0
    non_compliant_resource_refs = 0

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "requirement_count": 0,
            "compliant_requirements": 0,
            "need_attention_requirements": 0,
            "unavailable_requirements": 0,
            "evaluated_check_instances": 0,
            "compliant_check_instances": 0,
            "non_compliant_check_findings": 0,
            "non_compliant_resource_references": 0,
        }
    )

    for category in categories:
        category_name = as_text(category.get("categoryName")) or NOT_PROVIDED
        category_status = as_text(category.get("complianceStatus"))
        group = grouped[category_name]
        group["category"] = category_name
        group["requirement_count"] += 1
        if category_status == "Compliant":
            group["compliant_requirements"] += 1
        elif category_status == "Need Attention":
            group["need_attention_requirements"] += 1
        elif category_status == "Not available":
            group["unavailable_requirements"] += 1

        checks = category.get("checks") if isinstance(category.get("checks"), list) else []
        all_check_count += len(checks)
        group["evaluated_check_instances"] += len(checks)
        for check in checks:
            if not isinstance(check, dict):
                continue
            status = as_text(check.get("status")) or "<missing>"
            check_status[status] += 1
            if status == "compliant":
                group["compliant_check_instances"] += 1
            if status == "not_compliant":
                crit = as_text(check.get("criticality")) or "Not provided"
                severity[crit] += 1
                group["non_compliant_check_findings"] += 1
                resources = check.get("resources") if isinstance(check.get("resources"), list) else []
                group["non_compliant_resource_references"] += len(resources)
                non_compliant_resource_refs += len(resources)

    summary_counts = {
        "compliant_requirements": int(summary.get("compliantCount", 0) or 0),
        "need_attention_requirements": int(summary.get("notCompliantCount", 0) or 0),
        "unavailable_requirements": int(summary.get("notAvailableCount", 0) or 0),
    }
    summary_counts["total_requirements"] = sum(summary_counts.values())

    computed_requirement_total = len(categories)
    if summary_counts["total_requirements"] != computed_requirement_total:
        summary_counts["source_summary_mismatch"] = True
    else:
        summary_counts["source_summary_mismatch"] = False

    category_rows = [grouped[name] for name in sorted(grouped)]
    for row in category_rows:
        row["row_total_requirements"] = (
            row["compliant_requirements"]
            + row["need_attention_requirements"]
            + row["unavailable_requirements"]
        )

    return {
        "summary": summary_counts,
        "requirement_status": dict(requirement_status),
        "check_status": dict(check_status),
        "category_count": len(grouped),
        "requirement_count": computed_requirement_total,
        "evaluated_check_instances": all_check_count,
        "non_compliant_check_findings": len(findings),
        "non_compliant_resource_references": non_compliant_resource_refs,
        "severity_totals": dict(sorted(severity.items())),
        "category_rows": category_rows,
        "findings": findings,
    }


def html_text(value: Any) -> str:
    text = as_text(value)
    return escape(text if text else NOT_PROVIDED, quote=True)


def html_url(value: str) -> str:
    return escape(value, quote=True)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def render_list(items: Iterable[str]) -> str:
    material = [item for item in items if item]
    if not material:
        return f"<p>{escape(NOT_PROVIDED)}</p>"
    return "<ul>" + "".join(f"<li>{html_text(item)}</li>" for item in material) + "</ul>"


def render_references(items: Iterable[str]) -> str:
    material = [item for item in items if item]
    if not material:
        return f"<p>{escape(NOT_PROVIDED)}</p>"
    links = []
    for item in material:
        href = html_url(item)
        label = html_text(item)
        links.append(f'<li><a href="{href}">{label}</a></li>')
    return "<ul>" + "".join(links) + "</ul>"


def render_commands(commands: tuple[str, ...]) -> str:
    if not commands:
        return (
            "<p>Remediation commands require manual validation and are not generated "
            "because no command was provided by the source JSON.</p>"
        )
    blocks = "".join(f"<pre><code>{html_text(command)}</code></pre>" for command in commands)
    return blocks


def render_category_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<th scope=\"row\">{html_text(row['category'])}</th>"
            f"<td>{row['requirement_count']}</td>"
            f"<td>{row['compliant_requirements']}</td>"
            f"<td>{row['need_attention_requirements']}</td>"
            f"<td>{row['unavailable_requirements']}</td>"
            f"<td>{row['row_total_requirements']}</td>"
            f"<td>{row['evaluated_check_instances']}</td>"
            f"<td>{row['non_compliant_check_findings']}</td>"
            f"<td>{row['non_compliant_resource_references']}</td>"
            "</tr>"
        )
    return "\n".join(body)


def render_severity_table(severity_totals: dict[str, int]) -> str:
    order = ["H", "M", "L", "Not provided"]
    keys = [key for key in order if key in severity_totals]
    keys.extend(sorted(key for key in severity_totals if key not in keys))
    if not keys:
        keys = ["Not provided"]
    rows = []
    for key in keys:
        rows.append(
            "<tr>"
            f"<th scope=\"row\">{html_text(normalize_severity('' if key == 'Not provided' else key))}</th>"
            f"<td>{severity_totals.get(key, 0)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_appendix(findings: list[Finding]) -> str:
    parts = []
    used_ids: set[str] = set()
    for finding in findings:
        base_id = f"finding-{finding.index}-{slugify(finding.rule_id)}-{slugify(finding.check_id)}"
        finding_id = base_id
        suffix = 2
        while finding_id in used_ids:
            finding_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(finding_id)
        resources = finding.resources or (NOT_PROVIDED,)
        parts.append(
            f'<article class="finding" id="{finding_id}" data-appendix-entry="true">'
            f"<h3>Finding {finding.index}: {html_text(finding.title)}</h3>"
            "<dl class=\"finding-fields\">"
            f"<dt>Category</dt><dd>{html_text(finding.category)}</dd>"
            f"<dt>Rule identifier</dt><dd>{html_text(finding.rule_id)}</dd>"
            f"<dt>Check identifier</dt><dd>{html_text(finding.check_id)}</dd>"
            f"<dt>Severity</dt><dd>{html_text(normalize_severity(finding.criticality))}</dd>"
            f"<dt>Status</dt><dd>{html_text(normalize_status(finding.status))}</dd>"
            f"<dt>Service</dt><dd>{html_text(finding.service)}</dd>"
            f"<dt>Well-Architected pillar</dt><dd>{html_text(finding.wa_pillar)}</dd>"
            "</dl>"
            "<h4>Description</h4>"
            f"<p>{html_text(finding.description)}</p>"
            "<h4>Affected resources</h4>"
            f"{render_list(resources)}"
            "<h4>Remediation guidance</h4>"
            f"<p>{html_text(finding.remediation)}</p>"
            "<h4>Remediation commands</h4>"
            f"{render_commands(finding.commands)}"
            "<h4>References</h4>"
            f"{render_references(finding.references)}"
            "</article>"
        )
    return "\n".join(parts) or f"<p>{escape(NOT_PROVIDED)}</p>"


def render_report(
    data: dict[str, Any],
    input_path: Path,
    input_hash: str,
    generated_at: str,
) -> tuple[str, dict[str, Any]]:
    # Keep the data model and deterministic count semantics in this module,
    # while delegating presentation to a template built from the local AWS FTR
    # reference report and its checked-in AdminLTE assets.
    from aws_ftr_template import render_report as render_aws_report

    return render_aws_report(data, input_path, input_hash, generated_at)

    # The original renderer is retained below as a historical fallback while
    # the AWS-derived template is exercised and verified. It is unreachable by
    # design; keeping it here minimizes unrelated model churn in this fix.
    counts = compute_counts(data)
    summary = counts["summary"]
    total_requirements = summary["total_requirements"] or 1
    compliance_rate = round(summary["compliant_requirements"] / total_requirements * 100, 1)
    category_total_footer = {
        "requirement_count": sum(row["requirement_count"] for row in counts["category_rows"]),
        "compliant_requirements": sum(row["compliant_requirements"] for row in counts["category_rows"]),
        "need_attention_requirements": sum(row["need_attention_requirements"] for row in counts["category_rows"]),
        "unavailable_requirements": sum(row["unavailable_requirements"] for row in counts["category_rows"]),
        "row_total_requirements": sum(row["row_total_requirements"] for row in counts["category_rows"]),
        "evaluated_check_instances": sum(row["evaluated_check_instances"] for row in counts["category_rows"]),
        "non_compliant_check_findings": sum(row["non_compliant_check_findings"] for row in counts["category_rows"]),
        "non_compliant_resource_references": sum(row["non_compliant_resource_references"] for row in counts["category_rows"]),
    }
    audit_counts = {
        "ftr_requirement_summary_outcomes": summary,
        "ftr_requirement_rows": counts["requirement_count"],
        "category_count": counts["category_count"],
        "evaluated_check_instances": counts["evaluated_check_instances"],
        "non_compliant_check_finding_instances": counts["non_compliant_check_findings"],
        "non_compliant_resource_references": counts["non_compliant_resource_references"],
        "severity_totals_check_level_findings": counts["severity_totals"],
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AWS Foundational Technical Review Deterministic Report</title>
  <style>
    :root {{
      --ink: #1b1f24;
      --muted: #5f6b7a;
      --line: #d5d9d9;
      --panel: #f7f8f8;
      --accent: #0073bb;
      --danger: #b42318;
      --warning: #b54708;
      --success: #1d8102;
      --white: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--white);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.5;
    }}
    a {{ color: var(--accent); overflow-wrap: anywhere; }}
    header {{
      padding: 32px min(5vw, 56px);
      border-bottom: 4px solid var(--accent);
      background: #eef7fb;
    }}
    main {{ padding: 24px min(5vw, 56px) 48px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(1.75rem, 4vw, 2.7rem); letter-spacing: 0; }}
    h2 {{ margin-top: 36px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }}
    h3 {{ margin-top: 0; }}
    .note, .warning {{
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      background: var(--panel);
      margin: 16px 0;
    }}
    .warning {{ border-left-color: var(--danger); }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 18px 0;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 16px;
      background: var(--white);
      min-height: 96px;
    }}
    .metric strong {{ display: block; font-size: 1.9rem; line-height: 1.1; }}
    .metric span {{ color: var(--muted); }}
    .table-wrap {{ overflow-x: auto; margin: 16px 0; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    caption {{ text-align: left; font-weight: 700; margin-bottom: 8px; }}
    th, td {{ border: 1px solid var(--line); padding: 9px 10px; vertical-align: top; }}
    th {{ background: var(--panel); text-align: left; }}
    tfoot th, tfoot td {{ font-weight: 700; }}
    code, pre {{ font-family: Consolas, Monaco, monospace; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; border: 1px solid var(--line); padding: 12px; background: #f3f4f6; }}
    .finding {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 18px;
      margin: 18px 0;
      break-inside: avoid;
    }}
    .finding-fields {{
      display: grid;
      grid-template-columns: minmax(150px, 220px) 1fr;
      gap: 6px 14px;
    }}
    .finding-fields dt {{ font-weight: 700; color: var(--muted); }}
    .finding-fields dd {{ margin: 0; overflow-wrap: anywhere; }}
    .visually-hidden {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    @media (max-width: 720px) {{
      header, main {{ padding-left: 18px; padding-right: 18px; }}
      .finding-fields {{ grid-template-columns: 1fr; }}
      .finding-fields dt {{ margin-top: 6px; }}
      table {{ min-width: 680px; }}
    }}
    @media print {{
      header {{ background: var(--white); }}
      a::after {{ content: " (" attr(href) ")"; font-size: 0.9em; color: var(--muted); }}
      .finding {{ page-break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>AWS Foundational Technical Review Deterministic Report</h1>
    <p>Generated from Service Screener FTR JSON without external network resources or generated remediation commands.</p>
  </header>
  <main>
    <section id="report-metadata" data-section="required">
      <h2>Report Metadata</h2>
      <dl class="finding-fields">
        <dt>Input path</dt><dd id="input-path">{html_text(str(input_path))}</dd>
        <dt>Input SHA-256</dt><dd id="input-sha256">{html_text(input_hash)}</dd>
        <dt>Generated at</dt><dd id="generated-at">{html_text(generated_at)}</dd>
        <dt>Generator</dt><dd id="generator-version">{html_text(GENERATOR_VERSION)}</dd>
      </dl>
    </section>

    <section id="metrics" data-section="required">
      <h2>Metrics</h2>
      <p class="note">All values in this section are calculated directly from <code>framework.ftr</code>. Requirement outcomes, evaluated check instances, check-level findings, resource references, and category groups are separate units.</p>
      <div class="metric-grid">
        <div class="metric"><strong id="metric-requirement-rows">{counts["requirement_count"]}</strong><span>FTR requirement rows</span></div>
        <div class="metric"><strong id="metric-category-count">{counts["category_count"]}</strong><span>distinct category names</span></div>
        <div class="metric"><strong id="metric-evaluated-checks">{counts["evaluated_check_instances"]}</strong><span>evaluated check instances</span></div>
        <div class="metric"><strong id="metric-findings">{counts["non_compliant_check_findings"]}</strong><span>non-compliant check-level findings</span></div>
        <div class="metric"><strong id="metric-resource-refs">{counts["non_compliant_resource_references"]}</strong><span>affected resource references in non-compliant findings</span></div>
        <div class="metric"><strong id="metric-compliance-rate">{compliance_rate}%</strong><span>requirement compliance rate including unavailable rows in denominator</span></div>
      </div>
    </section>

    <section id="count-semantics" data-section="required">
      <h2>Count Semantics</h2>
      <ul>
        <li>FTR requirement or summary outcomes are category row outcomes from <code>framework.ftr.categories[].complianceStatus</code> and the source <code>framework.ftr.summary</code>.</li>
        <li>Evaluated check instances are objects in <code>framework.ftr.categories[].checks[]</code>.</li>
        <li>Appendix finding instances are check-level objects where <code>status</code> is <code>not_compliant</code>.</li>
        <li>Resource-level references are strings in each non-compliant check's <code>resources</code> list and are reported separately.</li>
        <li>Category count is the number of distinct <code>categoryName</code> values, not the number of requirement rows.</li>
      </ul>
    </section>

    <section id="category-summary" data-section="required">
      <h2>Category Summary</h2>
      <div class="table-wrap">
        <table id="category-summary-table">
          <caption>Category arithmetic by explicit unit</caption>
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col">Requirement rows</th>
              <th scope="col">Compliant requirements</th>
              <th scope="col">Need Attention requirements</th>
              <th scope="col">Unavailable requirements</th>
              <th scope="col">Requirement total check</th>
              <th scope="col">Evaluated check instances</th>
              <th scope="col">Non-compliant check findings</th>
              <th scope="col">Non-compliant resource references</th>
            </tr>
          </thead>
          <tbody>
            {render_category_table(counts["category_rows"])}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Total</th>
              <td id="category-total-requirement-rows">{category_total_footer["requirement_count"]}</td>
              <td id="category-total-compliant">{category_total_footer["compliant_requirements"]}</td>
              <td id="category-total-need-attention">{category_total_footer["need_attention_requirements"]}</td>
              <td id="category-total-unavailable">{category_total_footer["unavailable_requirements"]}</td>
              <td id="category-total-reconciled">{category_total_footer["row_total_requirements"]}</td>
              <td id="category-total-evaluated-checks">{category_total_footer["evaluated_check_instances"]}</td>
              <td id="category-total-findings">{category_total_footer["non_compliant_check_findings"]}</td>
              <td id="category-total-resource-refs">{category_total_footer["non_compliant_resource_references"]}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>

    <section id="severity-summary" data-section="required">
      <h2>Severity Totals</h2>
      <p>Severity totals are based only on check-level non-compliant findings with source-provided criticality values.</p>
      <div class="table-wrap">
        <table id="severity-summary-table">
          <caption>Non-compliant check-level findings by severity</caption>
          <thead><tr><th scope="col">Severity</th><th scope="col">Finding count</th></tr></thead>
          <tbody>
            {render_severity_table(counts["severity_totals"])}
          </tbody>
        </table>
      </div>
    </section>

    <section id="remediation-safety" data-section="required">
      <h2>Remediation Safety</h2>
      <p class="warning">No remediation command should be run without human review, environment validation, change approval, and rollback planning. This report does not invent AWS CLI commands.</p>
      <p>When a finding lacks source-provided remediation guidance or commands, the report states <q>{escape(NOT_PROVIDED)}</q> or that remediation commands require manual validation.</p>
    </section>

    <section id="appendix" data-section="required">
      <h2>Detailed Appendix</h2>
      <p id="appendix-count">Appendix entry count: {counts["non_compliant_check_findings"]}</p>
      {render_appendix(counts["findings"])}
    </section>
  </main>
</body>
</html>
"""
    return html, audit_counts


def write_report(input_path: Path, output_path: Path, generated_at: str | None = None) -> dict[str, Any]:
    data = load_json(input_path)
    input_hash = sha256_file(input_path)
    timestamp = generated_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    html, audit_counts = render_report(data, input_path, input_hash, timestamp)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return {
        "input_path": str(input_path),
        "input_sha256": input_hash,
        "output_path": str(output_path),
        "generated_at": timestamp,
        "summary_counts": audit_counts,
        "category_count": audit_counts["category_count"],
        "appendix_entry_count": audit_counts["non_compliant_check_finding_instances"],
        "generator": GENERATOR_VERSION,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a deterministic FTR HTML report from Service Screener JSON.")
    parser.add_argument("--input", required=True, type=Path, help="Path to ftr_results JSON.")
    parser.add_argument("--output", required=True, type=Path, help="Path to write the self-contained HTML report.")
    parser.add_argument(
        "--generated-at",
        help="Optional ISO-8601 timestamp for deterministic tests. Defaults to current UTC time.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        manifest = write_report(args.input, args.output, args.generated_at)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
