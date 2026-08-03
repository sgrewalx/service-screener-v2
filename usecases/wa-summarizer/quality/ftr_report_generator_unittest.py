import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = REPO_ROOT / "usecases" / "wa-summarizer" / "src" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_ftr_report
import validate_ftr_report


class AppendixCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries = 0

    def handle_starttag(self, tag, attrs):
        if dict(attrs).get("data-appendix-entry") == "true":
            self.entries += 1


def sample_ftr_json():
    return {
        "framework": {
            "ftr": {
                "summary": {
                    "compliantCount": 1,
                    "notCompliantCount": 2,
                    "notAvailableCount": 1,
                },
                "categories": [
                    {
                        "categoryName": "Identity <Admin>",
                        "ruleId": "IAM-001",
                        "complianceStatus": "Need Attention",
                        "checks": [
                            {
                                "checkId": "safeCheck",
                                "shortDescription": "Already compliant",
                                "status": "compliant",
                                "resources": [],
                            },
                            {
                                "checkId": "bad<Check>",
                                "shortDescription": "Escape <script>alert(1)</script>",
                                "status": "not_compliant",
                                "resources": ["[GLOBAL] - User::<root>&admin"],
                                "extendedDescription": "Description with <b>markup</b> & chars",
                                "criticality": "H",
                                "waRelatedPillar": "S",
                                "service": "iam",
                            },
                        ],
                        "reference": ["https://docs.example.test/ftr?a=1&b=2"],
                    },
                    {
                        "categoryName": "Identity <Admin>",
                        "ruleId": "IAM-002",
                        "complianceStatus": "Need Attention",
                        "checks": [
                            {
                                "checkId": "missingOptional",
                                "shortDescription": "",
                                "status": "not_compliant",
                                "resources": [],
                            }
                        ],
                        "reference": [],
                    },
                    {
                        "categoryName": "Architecture",
                        "ruleId": "ARC-001",
                        "complianceStatus": "Compliant",
                        "checks": [
                            {
                                "checkId": "archOk",
                                "shortDescription": "Reviewed",
                                "status": "compliant",
                                "resources": [],
                            }
                        ],
                        "reference": [],
                    },
                    {
                        "categoryName": "Support",
                        "ruleId": "SUP-001",
                        "complianceStatus": "Not available",
                        "checks": [],
                        "reference": [],
                    },
                ],
            }
        }
    }


class FTRReportTests(unittest.TestCase):
    def write_json(self, directory: Path, data=None) -> Path:
        path = directory / "ftr.json"
        path.write_text(json.dumps(data or sample_ftr_json(), indent=2, sort_keys=True), encoding="utf-8")
        return path

    def generate(self, directory: Path):
        input_path = self.write_json(directory)
        output_path = directory / "report.html"
        manifest = generate_ftr_report.write_report(
            input_path,
            output_path,
            generated_at="2026-08-03T15:00:00+00:00",
        )
        return input_path, output_path, manifest

    def test_count_reconciliation(self):
        counts = generate_ftr_report.compute_counts(sample_ftr_json())
        self.assertEqual(counts["summary"]["total_requirements"], 4)
        self.assertEqual(counts["category_count"], 3)
        self.assertEqual(counts["evaluated_check_instances"], 4)
        self.assertEqual(counts["non_compliant_check_findings"], 2)
        self.assertEqual(counts["non_compliant_resource_references"], 1)
        self.assertEqual(counts["severity_totals"], {"H": 1, "Not provided": 1})

    def test_one_appendix_entry_per_non_compliant_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path, output_path, _ = self.generate(Path(tmp))
            parser = AppendixCounter()
            parser.feed(output_path.read_text(encoding="utf-8"))
            counts = generate_ftr_report.compute_counts(generate_ftr_report.load_json(input_path))
            self.assertEqual(parser.entries, counts["non_compliant_check_findings"])
            self.assertEqual(validate_ftr_report.validate(input_path, output_path), [])

    def test_html_escaping(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, output_path, _ = self.generate(Path(tmp))
            report = output_path.read_text(encoding="utf-8")
            self.assertIn("Identity &lt;Admin&gt;", report)
            self.assertIn("Escape &lt;script&gt;alert(1)&lt;/script&gt;", report)
            self.assertIn("[GLOBAL] - User::&lt;root&gt;&amp;admin", report)
            self.assertNotIn("Escape <script>alert(1)</script>", report)

    def test_missing_optional_source_fields_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, output_path, _ = self.generate(Path(tmp))
            report = output_path.read_text(encoding="utf-8")
            self.assertIn(generate_ftr_report.NOT_PROVIDED, report)
            self.assertIn("Remediation commands require manual validation and are not generated", report)

    def test_duplicate_id_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path, output_path, _ = self.generate(Path(tmp))
            report = output_path.read_text(encoding="utf-8")
            output_path.write_text(report.replace("</main>", '<div id="metrics"></div></main>'), encoding="utf-8")
            errors = validate_ftr_report.validate(input_path, output_path)
            self.assertTrue(any("metrics" in error or "unique" in error for error in errors))

    def test_placeholder_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path, output_path, _ = self.generate(Path(tmp))
            with output_path.open("a", encoding="utf-8") as handle:
                handle.write("\ncompany.com\n")
            errors = validate_ftr_report.validate(input_path, output_path)
            self.assertTrue(any("company.com" in error for error in errors))

    def test_deterministic_output_with_controlled_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = self.write_json(tmp_path)
            first = tmp_path / "first.html"
            second = tmp_path / "second.html"
            generate_ftr_report.write_report(input_path, first, generated_at="2026-08-03T15:00:00+00:00")
            generate_ftr_report.write_report(input_path, second, generated_at="2026-08-03T15:00:00+00:00")
            self.assertEqual(first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
