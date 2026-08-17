from __future__ import annotations

import json
import csv
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
    def _write(self, directory: Path, retained: list[str], vendor: list[str]) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "active-function-ids.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "nexus.marketplace-selection/v1",
                    "retained_existing_ids": retained,
                    "vendor_inspired_ids": vendor,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_selection_requires_exactly_80_retained_and_20_vendor_inspired_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            retained = [f"retained-{index:03d}" for index in range(80)]
            vendor = [f"vendor-{index:03d}" for index in range(20)]
            path = self._write(directory, retained, vendor)

            selection = loader.load_active_function_ids(path, set(retained + vendor))

            self.assertEqual(selection, tuple(retained + vendor))

    def test_selection_rejects_wrong_counts_duplicates_and_unknown_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            retained = [f"retained-{index:03d}" for index in range(80)]
            vendor = [f"vendor-{index:03d}" for index in range(20)]
            available = set(retained + vendor)

            cases = [
                (retained[:-1], vendor, "exactly 80"),
                (retained, vendor[:-1], "exactly 20"),
                (retained, [*vendor[:-1], retained[0]], "duplicate"),
                (retained, [*vendor[:-1], "not-installed"], "unknown"),
            ]
            for index, (selected_retained, selected_vendor, message) in enumerate(cases):
                with self.subTest(message=message):
                    path = self._write(directory / str(index), selected_retained, selected_vendor)
                    with self.assertRaisesRegex(ValueError, message):
                        loader.load_active_function_ids(path, available)

    def test_production_selection_is_the_scored_top_80_plus_exact_20_new_plugins(self):
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
        self.assertEqual(document["retained_existing_ids"], scored_top_80)
        self.assertEqual(len(document["vendor_inspired_ids"]), 20)

        report = ranking_report.read_text(encoding="utf-8")
        self.assertIn("# Nexus Vision commercial function ranking", report)
        self.assertIn("**Status:** Final selection record", report)
        self.assertNotIn("Advisory Draft", report)
        self.assertEqual(
            set(document["vendor_inspired_ids"]),
            {
                "hardhat-visibility-review",
                "high-visibility-vest-review",
                "smoke-flame-visual-review",
                "plate-watchlist-review",
                "vehicle-attribute-log",
                "parking-violation-dwell",
                "stopped-vehicle-lane",
                "traffic-queue-spillback",
                "unusual-dwell-baseline",
                "queue-abandonment-review",
                "pedestrian-vehicle-conflict",
                "forklift-pedestrian-proximity",
                "perimeter-climb-review",
                "vehicle-wrong-way",
                "occupancy-flow-anomaly",
                "floor-water-change-review",
                "unusual-motion-baseline",
                "object-removal-review",
                "assembly-stage-order-review",
                "shipping-label-presence-review",
            },
        )

    def test_default_registry_is_exactly_100_and_archive_is_explicit(self):
        active, active_errors = loader.load_all()
        archived, archived_errors = loader.load_all(include_archived=True)
        self.assertEqual(active_errors, {})
        self.assertEqual(archived_errors, {})
        self.assertEqual(len(active), 100)
        self.assertEqual(len(archived), 271)

        loader.load_all()
        self.assertEqual(len(loader.catalog()), 100)
        selected = loader.load_active_function_ids(
            SRC / "marketplace" / "active-function-ids.json", set(archived)
        )
        self.assertEqual(set(active), set(selected))

    def test_customer_facing_count_copy_matches_the_active_100(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        landing = (ROOT / "landing" / "index.html").read_text(encoding="utf-8")
        storefront = (ROOT / "storefront" / "index.html").read_text(encoding="utf-8")
        guide = (ROOT / "guide" / "index.html").read_text(encoding="utf-8")
        design = (ROOT / "design.md").read_text(encoding="utf-8")
        activation = (ROOT / "SELF-SERVICE-ACTIVATION.md").read_text(encoding="utf-8")
        seo_generator = (ROOT / "scripts" / "generate_seo_schema.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("**100 functions across 9 business categories**", readme)
        self.assertIn("**100 marketplace functions total**", readme)
        self.assertIn("Explore 100 modules", landing)
        self.assertIn("Browse 100 functions", landing)
        self.assertIn("<b>100</b> AI functions", landing)
        self.assertIn("Nexus Vision Marketplace — 100 AI Functions", storefront)
        self.assertIn("Browse 100 GPU video analytics functions", storefront)
        self.assertIn("100 marketplace functions", guide)
        self.assertIn("the 100 active module artworks", design)
        self.assertIn("100 active function implementations", activation)
        self.assertIn("271 source/archive contracts", activation)
        self.assertIn("renders its 100 functions client-side", seo_generator)
        stale_claim = re.compile(
            r"\b(?:120|130)\s+(?:GPU\s+video\s+analytics\s+functions|AI\s+Functions|"
            r"video\s+analytics\s+functions|marketplace\s+functions|active\s+functions)",
            re.IGNORECASE,
        )
        for source in (landing, storefront, design, activation):
            self.assertIsNone(stale_claim.search(source), stale_claim.search(source))


if __name__ == "__main__":
    unittest.main()