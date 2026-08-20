"""AWS FTR/AdminLTE presentation template for the deterministic report.

The local AWS FTR HTML is the presentation reference for this module.  The
template adapts its shell and detail-table DOM while taking every report value
from ``generate_ftr_report``'s JSON-derived model.
"""

from __future__ import annotations

import base64
import re
from html import escape
from pathlib import Path
from typing import Any, Iterable

import generate_ftr_report as model


REPO_ROOT = Path(__file__).resolve().parents[4]
AWS_RES_ROOT = REPO_ROOT / "adminlte" / "aws" / "res"
AWS_REFERENCE = REPO_ROOT / "report-full-2026-08-03" / "aws" / "360929242476" / "FTR.html"

CSS_ASSETS = (
    "plugins/datatables-bs4/css/dataTables.bootstrap4.min.css",
    "plugins/datatables-responsive/css/responsive.bootstrap4.min.css",
    "plugins/datatables-buttons/css/buttons.bootstrap4.min.css",
    "plugins/fontawesome-free/css/all.min.css",
    "plugins/icheck-bootstrap/icheck-bootstrap.min.css",
    "dist/css/adminlte.min.css",
    "plugins/overlayScrollbars/css/OverlayScrollbars.min.css",
    "plugins/select2/css/select2.min.css",
)


def html_text(value: Any) -> str:
    text = model.as_text(value)
    return escape(text if text else model.NOT_PROVIDED, quote=True)


def html_optional_text(value: Any) -> str:
    return escape(model.as_text(value), quote=True)


def html_url(value: Any) -> str:
    return escape(model.as_text(value), quote=True)


def data_uri(path: Path, mime_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def load_embedded_css() -> str:
    """Inline the checked-in AdminLTE/DataTables CSS and local FontAwesome fonts."""

    blocks: list[str] = []
    font_css = AWS_RES_ROOT / "plugins" / "fontawesome-free" / "css" / "all.min.css"
    font_root = AWS_RES_ROOT / "plugins" / "fontawesome-free" / "webfonts"
    for relative_path in CSS_ASSETS:
        path = AWS_RES_ROOT / relative_path
        css = path.read_text(encoding="utf-8")
        if path == font_css:
            for font_name in ("fa-brands-400", "fa-regular-400", "fa-solid-900"):
                font_path = font_root / f"{font_name}.woff2"
                uri = data_uri(font_path, "font/woff2")
                css = re.sub(
                    rf"url\((?:['\"])?\.\./webfonts/{re.escape(font_name)}\.(?:eot|woff2|woff|ttf|svg)(?:#[^)]*)?(?:['\"])?\)",
                    f"url({uri})",
                    css,
                )
        blocks.append(f"/* embedded {relative_path} */\n{css}")
    return "\n\n".join(blocks)


def render_sidebar() -> str:
    """Reuse the canonical AWS sidebar DOM and localize its image assets/links."""

    reference = AWS_REFERENCE.read_text(encoding="utf-8")
    start = reference.index('  <aside class="main-sidebar')
    end = reference.index("</aside>", start) + len("</aside>")
    sidebar = reference[start:end]
    sidebar = sidebar.replace(
        "../res/dist/img/AdminLTELogo.png",
        data_uri(AWS_RES_ROOT / "dist" / "img" / "AdminLTELogo.png", "image/png"),
    )
    sidebar = sidebar.replace(
        "https://a0.awsstatic.com/libra-css/images/logos/aws_smile-header-desktop-en-white_59x35.png",
        data_uri(AWS_RES_ROOT / "dist" / "img" / "aws.png", "image/png"),
    )
    sidebar = re.sub(r"data-count=(['\"]).*?\1", "data-count=''", sidebar)

    def local_link(match: re.Match[str]) -> str:
        quote_char, href = match.group(1), match.group(2)
        destination = "#report-metadata" if href.lower() == "index.html" else "#FTR"
        return f"href={quote_char}{destination}{quote_char}"

    sidebar = re.sub(r"href=(['\"])([^'\"]+\.html)\1", local_link, sidebar, flags=re.IGNORECASE)
    return sidebar


def render_navbar() -> str:
    return """  <!-- Navbar -->
  <nav class="main-header navbar navbar-expand navbar-white navbar-light">
    <ul class="navbar-nav">
      <li class="nav-item"><a class="nav-link" data-widget="pushmenu" href="#" role="button"><i class="fas fa-bars"></i></a></li>
      <li class="nav-item d-none d-sm-inline-block"><a href="https://github.com/aws-samples/service-screener-v2" target="_blank" rel="noopener noreferrer" class="nav-link">Visit Github</a></li>
    </ul>
    <ul class="navbar-nav ml-auto">
      <li class="nav-item d-none d-sm-inline-block"><span class="nav-link">Change Account ID: </span></li>
      <li class="nav-item"><select class="form-control" id="changeAcctId"><option value="" selected>Not provided in source data</option></select></li>
      <li class="nav-item"><a class="nav-link" data-widget="fullscreen" href="#" role="button"><i class="fas fa-expand-arrows-alt"></i></a></li>
    </ul>
  </nav>
  <!-- /.navbar -->"""


def render_summary_doughnut(summary: dict[str, int]) -> str:
    values = [
        ("Not available", summary["unavailable_requirements"], "#17a2b8"),
        ("Compliant", summary["compliant_requirements"], "#28a745"),
        ("Need Attention", summary["need_attention_requirements"], "#dc3545"),
    ]
    total = max(sum(value for _, value, _ in values), 1)
    circumference = 2 * 3.141592653589793 * 54
    offset = 0.0
    circles: list[str] = []
    for label, value, color in values:
        length = circumference * value / total
        circles.append(
            f'<circle cx="60" cy="60" r="54" fill="none" stroke="{color}" stroke-width="22" '
            f'stroke-dasharray="{length:.3f} {circumference - length:.3f}" stroke-dashoffset="{-offset:.3f}">'
            f"<title>{escape(label)}: {value}</title></circle>"
        )
        offset += length
    return (
        '<div class="deterministic-doughnut-wrap" aria-label="Requirement outcome summary">'
        '<svg id="doughnut-chart" class="deterministic-doughnut" viewBox="0 0 120 120" role="img">'
        '<circle cx="60" cy="60" r="54" fill="none" stroke="#e9ecef" stroke-width="22"></circle>'
        + "".join(circles)
        + '<circle cx="60" cy="60" r="40" fill="#fff"></circle>'
        + f'<text x="60" y="58" text-anchor="middle" class="deterministic-chart-total">{sum(value for _, value, _ in values)}</text>'
        + '<text x="60" y="72" text-anchor="middle" class="deterministic-chart-label">requirements</text>'
        + "</svg></div>"
    )


def render_summary_bar_chart(rows: list[dict[str, Any]]) -> str:
    max_value = max((row["row_total_requirements"] for row in rows), default=1)
    chart_width = 980
    chart_height = 230
    plot_left = 34
    plot_bottom = 190
    plot_height = 150
    bar_width = max(12, int((chart_width - plot_left - 8) / max(len(rows), 1) - 6))
    groups: list[str] = []
    for index, row in enumerate(rows):
        x = plot_left + index * (bar_width + 6)
        scale = plot_height / max_value
        values = (
            (row["unavailable_requirements"], "#17a2b8"),
            (row["compliant_requirements"], "#28a745"),
            (row["need_attention_requirements"], "#dc3545"),
        )
        y = plot_bottom
        rects: list[str] = []
        for value, color in values:
            height = value * scale
            y -= height
            if height:
                rects.append(f'<rect x="{x}" y="{y:.2f}" width="{bar_width}" height="{height:.2f}" fill="{color}"><title>{escape(row["category"])}: {value}</title></rect>')
        label = escape(row["category"][:12])
        groups.append(
            f'<g class="deterministic-bar">{"".join(rects)}<text x="{x + bar_width / 2:.2f}" y="207" text-anchor="middle">{label}</text></g>'
        )
    return (
        '<div class="deterministic-bar-wrap" aria-label="Requirement outcomes by category">'
        f'<svg id="bar-chart" class="deterministic-bar-chart" viewBox="0 0 {chart_width} {chart_height}" role="img">'
        f'<line x1="{plot_left}" y1="{plot_bottom}" x2="{chart_width - 4}" y2="{plot_bottom}" stroke="#adb5bd"></line>'
        + "".join(groups)
        + "</svg></div>"
    )


def status_class(status: str) -> str:
    return {
        "Compliant": "bg-success",
        "Need Attention": "bg-danger",
        "Not available": "bg-info",
    }.get(status, "bg-secondary")


def render_resource(resource: str) -> str:
    value = model.as_text(resource)
    match = re.match(r"^(\[[^]]+\])\s*-\s*(.*)$", value)
    if match:
        return f"<b>{html_optional_text(match.group(1))}</b> {html_optional_text(match.group(2))}"
    return html_text(value)


def render_check_details(checks: Iterable[dict[str, Any]]) -> str:
    items: list[str] = []
    for check in checks:
        status = model.as_text(check.get("status"))
        if status == "compliant":
            css_class, icon = "text-success", "fa-check"
        elif status == "not_compliant":
            css_class, icon = "text-danger", "fa-times"
        else:
            css_class, icon = "text-muted", "fa-minus"
        check_id = html_text(check.get("checkId"))
        description = model.as_text(check.get("shortDescription"))
        suffix = f" - {html_optional_text(description)}" if description else ""
        items.append(f"<dt class='{css_class}'><i class='fas {icon}'></i> [{check_id}]{suffix}</dt>")
        resources = check.get("resources") if isinstance(check.get("resources"), list) else []
        if resources:
            items.append("<dd><ul>" + "".join(f"<li>{render_resource(item)}</li>" for item in resources) + "</ul></dd>")
    return "<dl>" + "".join(items) + "</dl>" if items else ""


def render_references(references: Iterable[str]) -> str:
    links = []
    for reference in references:
        value = model.as_text(reference)
        if value:
            href = html_url(value)
            links.append(f"<a href='{href}'>{html_optional_text(value)}</a>")
    return "<br>".join(links)


def render_framework_table(categories: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for category in categories:
        category_name = model.as_text(category.get("categoryName")) or model.NOT_PROVIDED
        rule_id = model.as_text(category.get("ruleId")) or model.NOT_PROVIDED
        requirement_status = model.as_text(category.get("complianceStatus")) or model.NOT_PROVIDED
        checks = category.get("checks") if isinstance(category.get("checks"), list) else []
        references = category.get("reference") if isinstance(category.get("reference"), list) else []
        details = render_check_details(check for check in checks if isinstance(check, dict))
        rows.append(
            "<tr>"
            f"<td>{html_optional_text(category_name)}</td>"
            f"<td>{html_optional_text(rule_id)}</td>"
            f"<td class='{status_class(requirement_status)} color-palette'>{html_optional_text(requirement_status)}</td>"
            f"<td>{details}</td>"
            f"<td>{render_references(references)}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_category_summary(rows: list[dict[str, Any]], footer: dict[str, int]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<th scope='row'>{html_text(row['category'])}</th>"
            f"<td>{row['requirement_count']}</td><td>{row['compliant_requirements']}</td>"
            f"<td>{row['need_attention_requirements']}</td><td>{row['unavailable_requirements']}</td>"
            f"<td>{row['row_total_requirements']}</td><td>{row['evaluated_check_instances']}</td>"
            f"<td>{row['non_compliant_check_findings']}</td><td>{row['non_compliant_resource_references']}</td>"
            "</tr>"
        )
    return "".join(body) + (
        "<tr><th scope='row'>Total</th>"
        f"<td id='category-total-requirement-rows'>{footer['requirement_count']}</td>"
        f"<td id='category-total-compliant'>{footer['compliant_requirements']}</td>"
        f"<td id='category-total-need-attention'>{footer['need_attention_requirements']}</td>"
        f"<td id='category-total-unavailable'>{footer['unavailable_requirements']}</td>"
        f"<td id='category-total-reconciled'>{footer['row_total_requirements']}</td>"
        f"<td id='category-total-evaluated-checks'>{footer['evaluated_check_instances']}</td>"
        f"<td id='category-total-findings'>{footer['non_compliant_check_findings']}</td>"
        f"<td id='category-total-resource-refs'>{footer['non_compliant_resource_references']}</td></tr>"
    )


def render_severity_summary(severity_totals: dict[str, int]) -> str:
    order = ["H", "M", "L", "Not provided"]
    keys = [key for key in order if key in severity_totals]
    keys.extend(key for key in sorted(severity_totals) if key not in keys)
    if not keys:
        keys = ["Not provided"]
    return "".join(
        f"<tr><th scope='row'>{html_text(model.normalize_severity('' if key == 'Not provided' else key))}</th><td>{severity_totals.get(key, 0)}</td></tr>"
        for key in keys
    )


def render_appendix(findings: list[model.Finding]) -> str:
    parts: list[str] = []
    used_ids: set[str] = set()
    for finding in findings:
        base_id = f"finding-{finding.index}-{re.sub(r'[^a-z0-9]+', '-', finding.rule_id.lower()).strip('-')}-{re.sub(r'[^a-z0-9]+', '-', finding.check_id.lower()).strip('-')}"
        finding_id = base_id or f"finding-{finding.index}"
        suffix = 2
        while finding_id in used_ids:
            finding_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(finding_id)
        resources = finding.resources or (model.NOT_PROVIDED,)
        resource_list = "<ul>" + "".join(f"<li>{html_text(item)}</li>" for item in resources) + "</ul>"
        reference_list = render_references(finding.references) or f"<p>{html_text(model.NOT_PROVIDED)}</p>"
        commands = "".join(f"<pre><code>{html_text(command)}</code></pre>" for command in finding.commands)
        if not commands:
            commands = "<p>Remediation commands require manual validation and are not generated because no command was provided by the source JSON.</p>"
        parts.append(
            f"<article class='card card-warning finding' id='{finding_id}' data-appendix-entry='true'>"
            f"<div class='card-header'><h3 class='card-title'>Finding {finding.index}: {html_text(finding.title)}</h3></div>"
            "<div class='card-body'><dl class='row'>"
            f"<dt class='col-sm-3'>Category</dt><dd class='col-sm-9'>{html_text(finding.category)}</dd>"
            f"<dt class='col-sm-3'>Rule identifier</dt><dd class='col-sm-9'>{html_text(finding.rule_id)}</dd>"
            f"<dt class='col-sm-3'>Check identifier</dt><dd class='col-sm-9'>{html_text(finding.check_id)}</dd>"
            f"<dt class='col-sm-3'>Severity</dt><dd class='col-sm-9'>{html_text(model.normalize_severity(finding.criticality))}</dd>"
            f"<dt class='col-sm-3'>Status</dt><dd class='col-sm-9'>{html_text(model.normalize_status(finding.status))}</dd>"
            f"<dt class='col-sm-3'>Service</dt><dd class='col-sm-9'>{html_text(finding.service)}</dd>"
            f"<dt class='col-sm-3'>Well-Architected pillar</dt><dd class='col-sm-9'>{html_text(finding.wa_pillar)}</dd>"
            "</dl>"
            f"<h4>Description</h4><p>{html_text(finding.description)}</p>"
            f"<h4>Affected resources</h4>{resource_list}"
            f"<h4>Remediation guidance</h4><p>{html_text(finding.remediation)}</p>"
            f"<h4>Remediation commands</h4>{commands}"
            f"<h4>References</h4>{reference_list}"
            "</div></article>"
        )
    return "".join(parts) or f"<p>{html_text(model.NOT_PROVIDED)}</p>"


def render_report(
    data: dict[str, Any],
    input_path: Path,
    input_hash: str,
    generated_at: str,
) -> tuple[str, dict[str, Any]]:
    ftr = model.get_ftr(data)
    categories = ftr["categories"]
    counts = model.compute_counts(data)
    summary = counts["summary"]
    total_requirements = summary["total_requirements"] or 1
    compliance_rate = round(summary["compliant_requirements"] / total_requirements * 100, 1)
    footer = {
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
    summary_title = (
        f"Summary: [Not available:{summary['unavailable_requirements']}] | "
        f"[Compliant:{summary['compliant_requirements']}] | "
        f"[Need Attention:{summary['need_attention_requirements']}]"
    )
    embedded_css = load_embedded_css()
    deterministic_css = """
/* Deterministic additions: the AdminLTE theme above remains authoritative. */
.deterministic-meta-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px 20px; }
.deterministic-meta-grid dt { font-weight: 700; }
.deterministic-meta-grid dd { margin: 0 0 6px; overflow-wrap: anywhere; }
.deterministic-doughnut-wrap, .deterministic-bar-wrap { min-height: 250px; height: 250px; max-height: 250px; max-width: 100%; display: flex; align-items: center; justify-content: center; overflow-x: auto; }
.deterministic-doughnut { width: 220px; height: 220px; transform: rotate(-90deg); }
.deterministic-doughnut text { transform: rotate(90deg); transform-origin: 60px 60px; }
.deterministic-chart-total { font-size: 16px; font-weight: 700; fill: #343a40; }
.deterministic-chart-label { font-size: 6px; fill: #6c757d; }
.deterministic-bar-chart { width: 100%; min-width: 720px; height: 230px; font-size: 8px; fill: #495057; }
.finding { break-inside: avoid; }
.finding h4 { margin-top: 1rem; }
.deterministic-note { border-left: 4px solid #ffc107; padding-left: 12px; }
@media print { .main-sidebar, .main-header { display: none; } .content-wrapper { margin-left: 0 !important; } }
"""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Service Screener | FTR</title>
  <style>{embedded_css}\n{deterministic_css}</style>
</head>
<body class="hold-transition sidebar-mini layout-fixed">
<div class="wrapper">
{render_navbar()}
{render_sidebar()}
<div class="content-wrapper">
  <div class="content-header">
    <div class="container-fluid">
      <div class="row mb-2">
        <div class="col-sm-6"><h1 class="m-0">FTR</h1></div>
        <div class="col-sm-6"><ol class="breadcrumb float-sm-right"><li class="breadcrumb-item"><a href="#">Home</a></li><li class="breadcrumb-item active">FTR</li></ol></div>
      </div>
    </div>
  </div>
  <section class="content">
    <div class="container-fluid">
      <div class="row" data-context="Brief">
        <div class="col-md-6">
          <section id="report-metadata" data-section="required">
            <div id="Framework" class="card card-warning">
              <div class="card-header"><h3 class="card-title">Foundational Technical Review</h3><div class="card-tools"><button type="button" class="btn btn-tool" data-card-widget="collapse"><i class="fas fa-minus"></i></button></div></div>
              <div class="card-body">{html_text('Framework details and narrative are not provided in source data.')}</div>
            </div>
          </section>
        </div>
        <div class="col-md-6">
          <div id="FTR-SummaryDoughnut" class="card card-warning">
            <div class="card-header"><h3 class="card-title">{summary_title}</h3><div class="card-tools"><button type="button" class="btn btn-tool" data-card-widget="collapse"><i class="fas fa-minus"></i></button></div></div>
            <div class="card-body"><div class="chart">{render_summary_doughnut(summary)}</div></div>
          </div>
        </div>
      </div>
      <div id="metrics" class="row" data-section="required">
        <div class="col-md-12">
          <div class="card card-warning">
            <div class="card-header"><h3 class="card-title">Deterministic report metadata</h3></div>
            <div class="card-body"><dl class="deterministic-meta-grid">
              <dt>Input JSON</dt><dd>{html_text(input_path)}</dd>
              <dt>Input SHA-256</dt><dd id="input-sha256"><code>{html_text(input_hash)}</code></dd>
              <dt>Generated at</dt><dd id="generated-at">{html_text(generated_at)}</dd>
              <dt>Generator</dt><dd id="generator"><code>{html_text(model.GENERATOR_VERSION)}</code></dd>
              <dt>Requirement rows</dt><dd id="metric-requirement-rows">{counts['requirement_count']}</dd>
              <dt>Distinct categories</dt><dd id="metric-category-count">{counts['category_count']}</dd>
              <dt>Evaluated check instances</dt><dd id="metric-evaluated-checks">{counts['evaluated_check_instances']}</dd>
              <dt>Non-compliant check findings</dt><dd id="metric-findings">{counts['non_compliant_check_findings']}</dd>
              <dt>Non-compliant resource references</dt><dd id="metric-resource-refs">{counts['non_compliant_resource_references']}</dd>
              <dt>Requirement compliance rate</dt><dd id="metric-compliance-rate">{compliance_rate}%</dd>
            </dl></div>
          </div>
        </div>
      </div>
      <div id="count-semantics" class="row" data-section="required">
        <div class="col-md-12"><div class="card card-warning"><div class="card-header"><h3 class="card-title">Count semantics</h3></div><div class="card-body deterministic-note"><ul>
          <li>Requirement outcomes are category rows and the source <code>framework.ftr.summary</code>.</li>
          <li>Evaluated check instances are objects in each category's <code>checks[]</code> array.</li>
          <li>Appendix entries are one-for-one with check-level objects whose source status is <code>not_compliant</code>.</li>
          <li>Resource references are counted separately from finding instances.</li>
          <li>Category count is the number of distinct source <code>categoryName</code> values.</li>
        </ul></div></div></div>
      </div>
      <div class="row" data-context="summaryChart">
        <div class="col-md-12">
          <div id="FTR-SummaryBarChart" class="card card-warning">
            <div class="card-header"><h3 class="card-title">Breakdown</h3><div class="card-tools"><button type="button" class="btn btn-tool" data-card-widget="collapse"><i class="fas fa-minus"></i></button></div></div>
            <div class="card-body"><div class="chart">{render_summary_bar_chart(counts['category_rows'])}</div></div>
          </div>
        </div>
      </div>
      <div id="category-summary" class="row" data-section="required" data-context="detail">
        <div class="col-md-12">
          <div id="FTR" class="card card-warning">
            <div class="card-header"><h3 class="card-title">Framework. Foundational Technical Review <span class="detailCategory" data-span-category="FTR"></span></h3></div>
            <div class="card-body"><table id="screener-framework" class="table table-bordered table-striped"><thead><tr><th>Category</th><th>Rule ID</th><th>Compliance Status</th><th>Description</th><th>Reference</th></tr></thead><tbody>{render_framework_table(categories)}</tbody></table></div>
          </div>
        </div>
        <div class="col-md-12">
          <div class="card card-warning"><div class="card-header"><h3 class="card-title">Category arithmetic</h3></div><div class="card-body"><table id="category-summary-table" class="table table-bordered table-striped"><thead><tr><th>Category</th><th>Requirement rows</th><th>Compliant requirements</th><th>Need Attention requirements</th><th>Unavailable requirements</th><th>Requirement total check</th><th>Evaluated check instances</th><th>Non-compliant check findings</th><th>Non-compliant resource references</th></tr></thead><tbody>{render_category_summary(counts['category_rows'], footer)}</tbody></table></div></div>
        </div>
      </div>
      <div id="severity-summary" class="row" data-section="required"><div class="col-md-12"><div class="card card-warning"><div class="card-header"><h3 class="card-title">Severity totals</h3></div><div class="card-body"><p>Severity totals are based only on non-compliant check-level findings.</p><table id="severity-summary-table" class="table table-bordered table-striped"><thead><tr><th>Severity</th><th>Finding count</th></tr></thead><tbody>{render_severity_summary(counts['severity_totals'])}</tbody></table></div></div></div></div>
      <div id="remediation-safety" class="row" data-section="required"><div class="col-md-12"><div class="card card-warning"><div class="card-header"><h3 class="card-title">Remediation safety</h3></div><div class="card-body"><p class="text-danger">No remediation command should be run without human review, environment validation, change approval, and rollback planning. This report does not invent AWS CLI commands.</p><p>Missing source fields are displayed as <q>{html_text(model.NOT_PROVIDED)}</q>.</p></div></div></div></div>
      <div id="appendix" class="row" data-section="required"><div class="col-md-12"><div class="card card-warning"><div class="card-header"><h3 class="card-title">Detailed appendix</h3></div><div class="card-body"><p id="appendix-count">Appendix entry count: {counts['non_compliant_check_findings']}</p>{render_appendix(counts['findings'])}</div></div></div></div>
    </div>
  </section>
</div>
<footer class="main-footer"><div class="float-right d-none d-sm-inline-block"><strong>Service Screener</strong>, <b>Version</b> 2.5.0 is distributed under the <strong><a target="_blank" rel="noopener noreferrer" href="https://www.apache.org/licenses/LICENSE-2.0">Apache 2.0 License</a>, powered by <a target="_blank" rel="noopener noreferrer" href="https://adminlte.io">AdminLTE.io</a></strong></div></footer>
</div>
</body>
</html>
"""
    return html, audit_counts
