import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "trial_radar.py"


def load_module():
    spec = importlib.util.spec_from_file_location("trial_radar", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TrialRadarTests(unittest.TestCase):
    def test_normalize_sample_study(self):
        trial_radar = load_module()
        study = json.loads((ROOT / "tests/fixtures/sample_studies/NCT00000001.json").read_text())
        normalized = trial_radar.normalize_study(study)

        self.assertEqual(normalized["trial_id"], "NCT00000001")
        self.assertEqual(normalized["phase"], "Phase 2")
        self.assertEqual(normalized["status"], "RECRUITING")
        self.assertEqual(normalized["relevance"], "current")
        self.assertEqual(normalized["intervention_types"], ["biological"])
        self.assertEqual(normalized["countries"], ["Spain", "United Kingdom"])
        self.assertEqual(normalized["regions"], ["Europe"])
        self.assertEqual(normalized["canonical_trial_key"], "clinicaltrials-gov:nct00000001")
        self.assertIn("patient_summary", normalized["patient_reading"])
        self.assertIn("may_be_looking_for", normalized["patient_reading"])
        self.assertIn("not medical advice", normalized["plain_language_summary"])
        self.assertIn("Phase 2 research", normalized["plain_language_summary"])

    def test_cli_generates_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(ROOT / "configs/lupus.json"),
                    "--out",
                    str(tmp_path),
                    "--offline-raw",
                    str(ROOT / "tests/fixtures/sample_studies"),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Wrote 2 normalized trials", result.stdout)
            self.assertTrue((tmp_path / "data/current/lupus.trials.json").exists())
            self.assertTrue((tmp_path / "data/current/lupus.trials.csv").exists())
            self.assertTrue((tmp_path / "reports/latest.md").exists())
            self.assertTrue((tmp_path / "site/index.html").exists())
            self.assertTrue((tmp_path / "site/explorer.html").exists())
            self.assertTrue((tmp_path / "site/topics/cell-therapy.html").exists())
            self.assertTrue((tmp_path / "site/trials/NCT00000001.html").exists())
            self.assertTrue((tmp_path / "site/interventions/examplemab.html").exists())
            self.assertTrue((tmp_path / "site/changes.html").exists())
            self.assertTrue((tmp_path / "site/glossary.html").exists())
            self.assertTrue((tmp_path / "site/diseases.html").exists())
            self.assertTrue((tmp_path / "data/ai-cache/lupus/rewrite_prompts.jsonl").exists())
            self.assertTrue((tmp_path / "data/ai-cache/lupus/rewrite_prompts_current_open.jsonl").exists())
            self.assertTrue((tmp_path / "data/ai-cache/lupus/weekly_brief_prompt.json").exists())
            self.assertTrue((tmp_path / "reports/ai-coverage.md").exists())

            report = (tmp_path / "reports/latest.md").read_text()
            self.assertIn("Lupus Research Radar Weekly Radar", report)
            self.assertIn("Examplemab", report)
            self.assertIn("Example Wearable Sensor", report)

            site = (tmp_path / "site/index.html").read_text()
            self.assertIn("TrialCompass", site)
            self.assertIn("Find trials near a location", site)
            self.assertIn("AI clinical trial finder for patients", site)
            self.assertIn('href="finder.html">Find</a>', site)
            self.assertIn('href="explorer.html">Learn</a>', site)
            self.assertIn("AI research tools", site)
            self.assertIn("AI record reader", site)
            self.assertIn("AI explained records:", site)
            self.assertIn('name="condition"', site)
            self.assertIn("Research areas", site)
            self.assertIn("topics/cell-therapy.html", site)

            topic = (tmp_path / "site/topics/cell-therapy.html").read_text()
            self.assertIn("Cell therapy / CAR-T", topic)
            self.assertIn("Questions for a clinician", topic)
            self.assertIn("../explorer.html?topic=cell-therapy", topic)
            self.assertIn("View in explorer", topic)
            self.assertIn("status=recruiting", topic)

            explorer = (tmp_path / "site/explorer.html").read_text()
            self.assertIn("Explore public records and research context", explorer)
            self.assertIn("Learn from TrialCompass", explorer)
            self.assertIn("Research library filters", explorer)
            self.assertIn('href="finder.html">Find</a>', explorer)
            self.assertIn('href="#explorer">Learn</a>', explorer)
            self.assertIn("Ask the research index", explorer)
            self.assertIn("applyGuidedSearch", explorer)
            self.assertIn("assistant-query", explorer)
            self.assertIn("Search records", explorer)
            self.assertIn("Advanced filters", explorer)
            self.assertIn("filter-rail", explorer)
            self.assertIn('id="search-button"', explorer)
            self.assertIn("initialParams.get('query')", explorer)
            self.assertIn("guide-topic", explorer)
            self.assertIn("CAR-T / cell therapy", explorer)
            self.assertIn("lupusLane", explorer)
            self.assertIn("Status and phase are research context", explorer)
            self.assertIn("Current/open research", explorer)
            self.assertNotIn("Start By Research Topic", explorer)
            self.assertNotIn("Practical Views", explorer)
            self.assertIn("radar-data", explorer)
            self.assertIn("result-summary", explorer)
            self.assertIn("PubMed-linked", explorer)
            self.assertIn("queryIntent", explorer)
            self.assertIn("Examplemab", explorer)
            self.assertIn("Read detail", explorer)
            self.assertIn('href="trials/${escapeAttr(trial.trial_id)}.html"', explorer)
            self.assertIn("Recent changes", explorer)
            self.assertIn("renderInterventionTable", explorer)
            self.assertIn("Outside United States", explorer)
            self.assertIn("regions-table", explorer)

            detail = (tmp_path / "site/trials/NCT00000001.html").read_text()
            self.assertIn("Questions to discuss with a clinician", detail)
            self.assertIn("Official registry", detail)
            self.assertIn("Verify first", detail)
            self.assertIn("Research context", detail)
            self.assertIn("does not determine eligibility", detail)
            self.assertIn("Example Bio", detail)
            self.assertIn("../interventions/examplemab.html", detail)
            self.assertIn("What terms may be confusing?", detail)
            self.assertIn("Registry summary only", detail)
            self.assertIn("Key fields", detail)

            weekly_brief = (tmp_path / "site/weekly-brief.html").read_text()
            self.assertIn("Build-Time AI Brief Workspace", weekly_brief)
            self.assertIn("weekly_brief_prompt.json", weekly_brief)

            intervention = (tmp_path / "site/interventions/examplemab.html").read_text()
            self.assertIn("Intervention research landscape", intervention)
            self.assertIn("Related Trial Records", intervention)
            self.assertIn("Pipeline Signals In This Radar", intervention)

            changes = (tmp_path / "site/changes.html").read_text()
            self.assertIn("What Changed This Week", changes)

            disease_index = (tmp_path / "site/diseases.html").read_text()
            self.assertIn("Disease Radars", disease_index)


if __name__ == "__main__":
    unittest.main()
