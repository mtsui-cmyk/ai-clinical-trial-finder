import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from scripts import trial_radar
from trial_finder.ai_engine import build_ai_reading, build_trial_reading_prompt
from trial_finder.cache import FinderCache
from trial_finder.clinicaltrials_gov import build_search_params, normalize_for_finder
from trial_finder.geo import resolve_location
from trial_finder.service import create_app
from trial_finder.source_catalog import list_sources


ROOT = Path(__file__).resolve().parents[1]


def sample_study_with_geo():
    study = json.loads((ROOT / "tests/fixtures/sample_studies/NCT00000001.json").read_text())
    study["protocolSection"]["contactsLocationsModule"]["locations"] = [
        {
            "facility": "RenJi Hospital",
            "status": "RECRUITING",
            "city": "Shanghai",
            "state": "Shanghai Municipality",
            "zip": "200001",
            "country": "China",
            "geoPoint": {"lat": 31.22222, "lon": 121.45806},
            "contacts": [
                {
                    "name": "Study Desk",
                    "role": "CONTACT",
                    "phone": "+86-21-00000000",
                    "email": "study@example.org",
                }
            ],
        }
    ]
    return study


class TrialFinderTests(unittest.TestCase):
    def test_source_catalog_exposes_connected_and_planned_sources(self):
        sources = list_sources()
        by_id = {source["id"]: source for source in sources}

        self.assertEqual(by_id["clinicaltrials_gov"]["status"], "connected")
        self.assertTrue(by_id["clinicaltrials_gov"]["default_selected"])
        self.assertEqual(by_id["anzctr"]["status"], "planned")
        self.assertEqual(by_id["who_ictrp"]["status"], "planned")
        self.assertEqual(by_id["chictr"]["status"], "external_link_only")

    def test_finder_page_uses_source_selected_task_flow(self):
        page = (ROOT / "site/finder.html").read_text()

        self.assertIn("TrialCompass", page)
        self.assertIn("Source-selected trial finder", page)
        self.assertIn("Advanced sources", page)
        self.assertIn("City or postcode", page)
        self.assertIn("browser location permission is not required", page)
        self.assertIn("AI Research Radar appears after search", page)
        self.assertIn("AI Research Radar", page)
        self.assertIn("ClinicalTrials.gov selected", page)
        self.assertIn("Nearest listed site", page)
        self.assertIn("Trial status:", page)
        self.assertIn("Verify details in the official registry", page)
        self.assertIn("does not determine eligibility", page)
        self.assertNotIn("<aside>\n      <h2>Data sources</h2>", page)
        self.assertNotIn("best trial", page.lower())
        self.assertNotIn("eligible for you", page.lower())
        self.assertNotIn("recommended", page.lower())

    def test_clinicaltrials_query_uses_geo_filter_for_resolved_location(self):
        params = build_search_params("systemic lupus erythematosus", "Shanghai", 100)

        self.assertEqual(params["query.cond"], "systemic lupus erythematosus")
        self.assertEqual(params["filter.overallStatus"], "RECRUITING,NOT_YET_RECRUITING,ENROLLING_BY_INVITATION")
        self.assertIn("filter.geo", params)
        self.assertIn("distance(31.2304,121.4737", params["filter.geo"])

    def test_normalizer_preserves_location_geo_status_and_contacts(self):
        normalized = trial_radar.normalize_study(sample_study_with_geo())
        location = normalized["locations"][0]

        self.assertEqual(location["facility"], "RenJi Hospital")
        self.assertEqual(location["status"], "RECRUITING")
        self.assertEqual(location["zip"], "200001")
        self.assertEqual(location["geoPoint"], {"lat": 31.22222, "lon": 121.45806})
        self.assertEqual(location["contacts"][0]["email"], "study@example.org")

    def test_distance_sorting_adds_distance_at_query_time_only(self):
        normalized = normalize_for_finder([sample_study_with_geo()], "systemic lupus erythematosus", "Shanghai", 100)

        self.assertAlmostEqual(normalized[0]["distance_km"], 1.7, delta=0.5)
        self.assertAlmostEqual(normalized[0]["nearest_location"]["distance_km"], 1.7, delta=0.5)
        self.assertIn("does not determine eligibility", normalized[0]["finder_safety_note"])
        self.assertEqual(normalized[0]["research_radar"]["mode"], "Source-grounded AI reading aid")
        self.assertIn("official registry", " ".join(normalized[0]["research_radar"]["signals"]))
        self.assertEqual(normalized[0]["research_radar"]["prompt_contract"]["provider"], "local_deterministic_mvp")

    def test_ai_engine_builds_source_grounded_prompt_contract(self):
        normalized = normalize_for_finder([sample_study_with_geo()], "systemic lupus erythematosus", "Shanghai", 100)[0]
        prompt = build_trial_reading_prompt(normalized)
        reading = build_ai_reading(normalized)

        self.assertEqual(prompt["task"], "Explain this public clinical trial registry record as a patient-facing reading aid.")
        self.assertIn("recommend a trial", prompt["hard_rules"])
        self.assertEqual(prompt["source_fields"]["nearest_site"]["city"], "Shanghai")
        self.assertIn("must not recommend", reading["safety_note"])

    def test_cache_hashes_location_metadata_without_plaintext_location(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = FinderCache(directory)
            cache.set(
                "clinicaltrials_gov",
                "systemic lupus erythematosus",
                "Shanghai",
                100,
                ["RECRUITING"],
                raw={"studies": []},
                normalized=[],
            )
            with sqlite3.connect(Path(directory) / "metadata.sqlite3") as conn:
                rows = conn.execute("SELECT source_id, condition_hash, location_hash, radius_km FROM cache_entries").fetchall()
                columns = [info[1] for info in conn.execute("PRAGMA table_info(cache_entries)").fetchall()]

            self.assertEqual(rows[0][0], "clinicaltrials_gov")
            self.assertEqual(rows[0][3], 100)
            self.assertNotIn("location_text", columns)
            self.assertNotIn("Shanghai", str(rows))

    def test_api_search_respects_source_selection_and_detail_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(cache_root=directory)
            client = TestClient(app)

            with patch("trial_finder.service.fetch_search") as fetch_search:
                fetch_search.return_value = ([sample_study_with_geo()], {"data_timestamp": "2026-05-14"})
                response = client.post(
                    "/api/search",
                    json={
                        "condition_text": "systemic lupus erythematosus",
                        "location_text": "Shanghai",
                        "radius_km": 100,
                        "source_ids": ["clinicaltrials_gov", "anzctr"],
                        "statuses": ["RECRUITING"],
                        "limit": 10,
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["sources"][0]["status"], "connected")
            self.assertEqual(payload["sources"][1]["status"], "planned")
            self.assertIn("research_radar", payload["results"][0])
            self.assertIn("no user location profile is stored", payload["query"]["location_storage"])
            self.assertIn("does not determine eligibility", payload["safety_note"])

            detail_key = payload["results"][0]["canonical_trial_key"]
            detail = client.get(f"/api/trials/{detail_key}").json()["trial"]
            self.assertEqual(detail["nearest_location"]["facility"], "RenJi Hospital")
            self.assertIn("Verify details in the official registry", detail["finder_safety_note"])

            ai_response = client.get(f"/api/ai/read-trial/{detail_key}").json()
            self.assertEqual(ai_response["trial_id"], "NCT00000001")
            self.assertIn("prompt", ai_response)
            self.assertIn("does not recommend", ai_response["safety_note"])


class GeoTests(unittest.TestCase):
    def test_resolve_location_accepts_coordinates(self):
        location = resolve_location("31.2304, 121.4737")

        self.assertEqual(location["method"], "coordinates")
        self.assertEqual(location["lat"], 31.2304)
        self.assertEqual(location["lon"], 121.4737)

    def test_resolve_location_knows_hangzhou(self):
        location = resolve_location("Hangzhou")

        self.assertEqual(location["method"], "local_gazetteer")
        self.assertEqual(location["lat"], 30.2741)
        self.assertEqual(location["lon"], 120.1551)


if __name__ == "__main__":
    unittest.main()
