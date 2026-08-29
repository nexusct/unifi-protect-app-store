from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from marketplace import loader


class ActiveMarketplaceSelectionTests(unittest.TestCase):
    def _write(self, directory: Path, retained: list[str], super_skills: list[str]) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "active-function-ids.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "nexus.marketplace-selection/v2",
                    "retained_active_ids": retained,
                    "super_skill_ids": super_skills,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_selection_requires_exactly_75_retained_and_30_super_skill_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            retained = [f"retained-{index:03d}" for index in range(75)]
            super_skills = [f"super-{index:03d}" for index in range(30)]
            path = self._write(directory, retained, super_skills)

            selection = loader.load_active_function_ids(path, set(retained + super_skills))

            self.assertEqual(selection, tuple(retained + super_skills))

    def test_selection_rejects_wrong_counts_duplicates_and_unknown_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            retained = [f"retained-{index:03d}" for index in range(75)]
            super_skills = [f"super-{index:03d}" for index in range(30)]
            available = set(retained + super_skills)

            cases = [
                (retained[:-1], super_skills, "exactly 75"),
                (retained, super_skills[:-1], "exactly 30"),
                (retained, [*super_skills[:-1], retained[0]], "duplicate"),
                (retained, [*super_skills[:-1], "not-installed"], "unknown"),
            ]
            for index, (selected_retained, selected_super, message) in enumerate(cases):
                with self.subTest(message=message):
                    path = self._write(directory / str(index), selected_retained, selected_super)
                    with self.assertRaisesRegex(ValueError, message):
                        loader.load_active_function_ids(path, available)

    def test_production_selection_matches_the_audited_75_plus_exact_30_super_skills(self):
        selection_path = SRC / "marketplace" / "active-function-ids.json"
        document = json.loads(selection_path.read_text(encoding="utf-8"))
        ranking_csv = ROOT / "docs" / "commercial-function-ranking.csv"
        ranking_report = ROOT / "docs" / "commercial-function-ranking.md"
        self.assertTrue(ranking_csv.is_file(), "missing final commercial ranking CSV")
        self.assertTrue(ranking_report.is_file(), "missing final commercial ranking report")
        with ranking_csv.open(
            newline="", encoding="utf-8"
        ) as handle:
            rows = list(csv.DictReader(handle))
        scored_top_80 = [row["id"] for row in rows if row["top_80"] == "yes"]

        self.assertEqual(len(rows), 251)
        self.assertEqual(len(scored_top_80), 80)
        audit = json.loads((ROOT / "docs" / "super-skill-portfolio.json").read_text(encoding="utf-8"))
        retired_ids = {row["id"] for row in audit["retired"]}
        expected_retained = [function_id for function_id in scored_top_80 if function_id not in retired_ids]
        retained_ids = set(document["retained_active_ids"])
        baseline_ids = retained_ids | retired_ids
        baseline_digest = hashlib.sha256(
            "\n".join(sorted(baseline_ids)).encode("utf-8")
        ).hexdigest()
        self.assertEqual(len(document["retained_active_ids"]), 75)
        self.assertEqual(len(document["super_skill_ids"]), 30)
        self.assertEqual(len(retired_ids), 25)
        self.assertEqual(len(baseline_ids), 100)
        self.assertEqual(
            baseline_digest,
            audit["baseline"]["active_ids_sha256"],
            "retained IDs plus the exact retirements must reconstruct the audited 100-ID baseline",
        )
        self.assertEqual(retained_ids, baseline_ids - retired_ids)
        self.assertTrue(set(expected_retained).issubset(retained_ids))
        self.assertTrue(retired_ids.isdisjoint(retained_ids))

        report = ranking_report.read_text(encoding="utf-8")
        self.assertIn("# Nexus Vision commercial function ranking", report)
        self.assertIn("**Status:** Final selection record", report)
        self.assertNotIn("Advisory Draft", report)
        self.assertEqual(
            set(document["super_skill_ids"]),
            {row["id"] for row in audit["super_skills"]},
        )

    def test_default_registry_is_exactly_105_and_archive_is_explicit(self):
        active, active_errors = loader.load_all()
        archived, archived_errors = loader.load_all(include_archived=True)
        self.assertEqual(active_errors, {})
        self.assertEqual(archived_errors, {})
        self.assertEqual(len(active), 105)
        self.assertEqual(len(archived), 301)

        loader.load_all()
        self.assertEqual(len(loader.catalog()), 105)
        selected = loader.load_active_function_ids(
            SRC / "marketplace" / "active-function-ids.json", set(archived)
        )
        self.assertEqual(set(active), set(selected))

    def test_customer_facing_count_copy_matches_the_active_105(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        landing = (ROOT / "landing" / "index.html").read_text(encoding="utf-8")
        storefront = (ROOT / "storefront" / "index.html").read_text(encoding="utf-8")
        guide = (ROOT / "guide" / "index.html").read_text(encoding="utf-8")
        design = (ROOT / "design.md").read_text(encoding="utf-8")
        activation = (ROOT / "SELF-SERVICE-ACTIVATION.md").read_text(encoding="utf-8")
        seo_generator = (ROOT / "scripts" / "generate_seo_schema.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("**105 functions across 9 business categories**", readme)
        self.assertIn("**105 marketplace functions total**", readme)
        self.assertIn("Explore 105 modules", landing)
        self.assertIn("Browse 105 functions", landing)
        self.assertIn("<b>105</b> AI functions", landing)
        self.assertIn("Nexus Vision Marketplace — 105 AI Functions", storefront)
        self.assertIn("Browse 105 GPU video analytics functions", storefront)
        self.assertIn("105 marketplace functions", guide)
        self.assertIn("the 105 active module artworks", design)
        self.assertIn("105 active function implementations", activation)
        self.assertIn("301 source/archive contracts", activation)
        self.assertIn("renders its 105 functions client-side", seo_generator)
        stale_claim = re.compile(
            r"\b(?:120|130)\s+(?:GPU\s+video\s+analytics\s+functions|AI\s+Functions|"
            r"video\s+analytics\s+functions|marketplace\s+functions|active\s+functions)",
            re.IGNORECASE,
        )
        for source in (landing, storefront, design, activation):
            self.assertIsNone(stale_claim.search(source), stale_claim.search(source))


if __name__ == "__main__":
    unittest.main()