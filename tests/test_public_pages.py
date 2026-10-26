from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    "landing": ROOT / "landing" / "index.html",
    "storefront": ROOT / "storefront" / "index.html",
    "guide": ROOT / "guide" / "index.html",
}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: list[dict[str, str | None]] = []
        self.links: list[tuple[str, str]] = []
        self.ids: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self.json_ld: list[str] = []
        self.landmarks = {"main": 0, "nav": 0}
        self.faqs: list[dict[str, str]] = []
        self._title_depth = 0
        self._heading_level: int | None = None
        self._heading_text: list[str] = []
        self._json_depth = 0
        self._json_text: list[str] = []
        self._faq: dict[str, str] | None = None
        self._faq_field: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self._title_depth += 1
        if re.fullmatch(r"h[1-6]", tag):
            self._heading_level = int(tag[1])
            self._heading_text = []
        if tag == "meta":
            self.meta.append(values)
        if tag in {"a", "link", "script", "img"}:
            reference = values.get("href") or values.get("src")
            if reference:
                self.links.append((tag, reference))
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag in self.landmarks:
            self.landmarks[tag] += 1
        if tag == "script" and values.get("type") == "application/ld+json":
            self._json_depth = 1
            self._json_text = []
        elif self._json_depth:
            self._json_depth += 1
        classes = (values.get("class") or "").split()
        if tag == "details" and "faq" in classes:
            self._faq = {"question": "", "answer": ""}
        elif self._faq is not None and tag == "summary":
            self._faq_field = "question"
        elif self._faq is not None and tag == "p":
            self._faq_field = "answer"

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._title_depth = max(0, self._title_depth - 1)
        if self._heading_level is not None and tag == f"h{self._heading_level}":
            self.headings.append((self._heading_level, normalize("".join(self._heading_text))))
            self._heading_level = None
            self._heading_text = []
        if self._json_depth:
            self._json_depth -= 1
            if self._json_depth == 0:
                self.json_ld.append("".join(self._json_text))
        if self._faq is not None and tag in {"summary", "p"}:
            self._faq_field = None
        if self._faq is not None and tag == "details":
            self._faq = {key: normalize(value) for key, value in self._faq.items()}
            self.faqs.append(self._faq)
            self._faq = None

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title += data
        if self._heading_level is not None:
            self._heading_text.append(data)
        if self._json_depth:
            self._json_text.append(data)
        if self._faq is not None and self._faq_field:
            self._faq[self._faq_field] += data


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def meta_content(parser: PageParser, key: str, value: str) -> str | None:
    return next(
        (str(item.get("content")) for item in parser.meta if item.get(key) == value and item.get("content")),
        None,
    )


def local_target(source: Path, reference: str) -> tuple[Path, str]:
    split = urlsplit(reference)
    raw_path = unquote(split.path)
    if raw_path.startswith("/"):
        target = ROOT / raw_path.lstrip("/")
    elif raw_path:
        target = source.parent / raw_path
    else:
        target = source
    target = target.resolve()
    if target.is_dir() or raw_path.endswith("/"):
        target /= "index.html"
    return target, split.fragment


class PublicPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parsed = {name: parse(path) for name, path in PAGES.items()}

    def test_metadata_is_unique_complete_and_within_length_budgets(self):
        titles = []
        descriptions = []
        expected_canonicals = {"landing": "./", "storefront": "./", "guide": "./"}
        for name, parser in self.parsed.items():
            title = normalize(parser.title)
            description = meta_content(parser, "name", "description")
            canonicals = [reference for tag, reference in parser.links if tag == "link" and reference in {"../", "./"}]
            self.assertGreaterEqual(len(title), 40, name)
            self.assertLessEqual(len(title), 60, name)
            self.assertIsNotNone(description, name)
            self.assertGreaterEqual(len(description or ""), 140, name)
            self.assertLessEqual(len(description or ""), 160, name)
            self.assertEqual(canonicals, [expected_canonicals[name]], name)
            self.assertEqual(meta_content(parser, "name", "twitter:card"), "summary_large_image", name)
            self.assertIsNotNone(meta_content(parser, "property", "og:image"), name)
            self.assertIsNotNone(meta_content(parser, "name", "twitter:image"), name)
            titles.append(title)
            descriptions.append(description)
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(len(descriptions), len(set(descriptions)))

    def test_heading_and_landmark_structure(self):
        for name, parser in self.parsed.items():
            h1s = [text for level, text in parser.headings if level == 1]
            self.assertEqual(len(h1s), 1, name)
            self.assertIn("UniFi Protect", h1s[0], name)
            self.assertEqual(parser.landmarks["main"], 1, name)
            self.assertEqual(parser.landmarks["nav"], 1, name)
            for previous, current in zip(parser.headings, parser.headings[1:]):
                self.assertLessEqual(current[0] - previous[0], 1, f"{name}: {previous} -> {current}")

    def test_json_ld_is_valid_and_faq_schema_matches_visible_copy(self):
        expected_types = {
            "landing": {"SoftwareApplication", "FAQPage"},
            "storefront": {"CollectionPage", "SoftwareApplication", "ItemList"},
            "guide": {"TechArticle", "HowTo"},
        }
        for name, parser in self.parsed.items():
            documents = [json.loads(source) for source in parser.json_ld]
            # A document is either a single entity or an @graph of entities.
            nodes = [node for document in documents for node in document.get("@graph", [document])]
            self.assertEqual({node["@type"] for node in nodes}, expected_types[name], name)

        landing = self.parsed["landing"]
        faq_schema = next(json.loads(source) for source in landing.json_ld if json.loads(source)["@type"] == "FAQPage")
        schema_pairs = [
            {
                "question": item["name"],
                "answer": normalize(item["acceptedAnswer"]["text"]),
            }
            for item in faq_schema["mainEntity"]
        ]
        self.assertEqual(schema_pairs, landing.faqs)

    def test_static_ids_and_internal_references_are_valid(self):
        for name, parser in self.parsed.items():
            self.assertEqual(len(parser.ids), len(set(parser.ids)), f"duplicate id on {name}")
            source = PAGES[name]
            for tag, reference in parser.links:
                split = urlsplit(reference)
                if split.scheme or split.netloc or reference.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                target, fragment = local_target(source, reference)
                self.assertTrue(target.is_file(), f"{name}: broken {tag} reference {reference} -> {target}")
                if fragment:
                    anchor_target = ROOT / "landing" / "index.html" if target == ROOT / "index.html" else target
                    self.assertIn(fragment, parse(anchor_target).ids, f"{name}: missing anchor {reference}")

    def test_social_preview_image_exists(self):
        local_asset = ROOT / "assets" / "hero-banner.jpg"
        self.assertTrue(local_asset.is_file())
        for name, parser in self.parsed.items():
            for meta_key in ("og:image", "twitter:image"):
                key = "property" if meta_key.startswith("og:") else "name"
                reference = meta_content(parser, key, meta_key)
                self.assertIsNotNone(reference, name)
                split = urlsplit(reference or "")
                self.assertEqual(split.scheme, "https", name)
                self.assertTrue(split.netloc, name)
                self.assertTrue(split.path.endswith("/assets/hero-banner.jpg"), name)

    def test_forbidden_public_claim_phrases_do_not_return(self):
        forbidden = (
            "BIPA-safe",
            "HIPAA-compliant",
            "PCI-compliant",
            "video never leaves",
            "guaranteed uptime",
            "SLA target",
            "99.99%",
            "measured, every time",
            "catches it within a minute",
            "five-figure OSHA fine",
            "fall detection",
            "bed-exit prediction",
            "quiet hours built in",
            "slack/teams/whatever",
            "slack / teams / generic webhook",
            "slip & fall clips",
            "clip preserved",
            "clip retention",
            "email + webhook alerts",
            "weekly analytics digest",
            "daily digests",
            "clip/snapshot retention",
        )
        public_sources = [path.read_text(encoding="utf-8") for path in PAGES.values()]
        public_sources.append((ROOT / "storefront" / "catalog.json").read_text(encoding="utf-8"))
        public_sources.append((ROOT / "README.md").read_text(encoding="utf-8"))
        public_sources.append((ROOT / ".env.example").read_text(encoding="utf-8"))
        combined = "\n".join(public_sources).casefold()
        for phrase in forbidden:
            self.assertNotIn(phrase.casefold(), combined, phrase)

    def test_storefront_loads_local_design_tokens_before_overrides(self):
        source = PAGES["storefront"].read_text(encoding="utf-8")
        font_preload = '<link rel="preload" as="font" type="font/woff2" href="../assets/fonts/archivo-variable.woff2" crossorigin />'
        tokens = '<link rel="stylesheet" href="../assets/tokens.css" />'
        overrides = '<link rel="stylesheet" href="../assets/marketplace.css" />'

        self.assertIn(font_preload, source)
        self.assertIn(tokens, source)
        self.assertLess(source.index(tokens), source.index(overrides))

    def test_storefront_uses_compact_filter_command_bar_and_feature_shelf(self):
        source = PAGES["storefront"].read_text(encoding="utf-8")
        stylesheet = (ROOT / "assets" / "marketplace.css").read_text(encoding="utf-8")

        self.assertIn('class="controls-primary"', source)
        self.assertIn('class="filter-rails"', source)
        self.assertGreaterEqual(source.count('class="filter-label"'), 2)
        self.assertIn("grid-auto-flow: column", stylesheet)
        self.assertIn("scroll-snap-type: x mandatory", stylesheet)

    def test_storefront_service_art_is_unboxed_and_contained(self):
        stylesheet = (ROOT / "assets" / "marketplace.css").read_text(encoding="utf-8")
        for selector in (".feature-art", ".app-icon", ".app-art"):
            match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", stylesheet)
            self.assertIsNotNone(match, selector)
            declarations = match.group(1) if match else ""
            self.assertIn("object-fit: contain", declarations, selector)
            self.assertIn("background: transparent", declarations, selector)
            self.assertNotIn("border-radius", declarations, selector)

    def test_storefront_runtime_config_and_semantics_are_explicit(self):
        source = PAGES["storefront"].read_text(encoding="utf-8")
        self.assertIn('\"    detectors: [\"', source)
        self.assertIn('\"detector_settings:\"', source)
        self.assertNotIn('\"    functions: [\"', source)
        self.assertNotIn('\"function_settings:\"', source)
        self.assertIn('<caption class="sr-only">', source)
        self.assertIn('<th scope="col">Setting</th>', source)
        self.assertIn('<th scope="col">Description</th>', source)
        self.assertIn('<th scope="col">YAML location</th>', source)
        self.assertIn('f.camera_zones || {}', source)
        self.assertIn('...zoneYamlLines(fns)', source)
        self.assertIn('timezone: "America/Chicago"  # REQUIRED:', source)
        self.assertNotIn('role="heading"', source)

    def test_landing_mobile_signup_grid_children_can_shrink(self):
        stylesheet = (ROOT / "assets" / "marketplace.css").read_text(encoding="utf-8")
        self.assertIn("body.page-landing .signup-wrap > * { min-width: 0; }", stylesheet)

    def test_landing_selection_state_and_guide_tables_are_accessible(self):
        landing = PAGES["landing"].read_text(encoding="utf-8")
        self.assertIn('button.setAttribute("aria-pressed", "false")', landing)

        guide = PAGES["guide"].read_text(encoding="utf-8")
        self.assertEqual(guide.count("<table>"), 2)
        self.assertEqual(guide.count('<caption class="sr-only">'), 2)
        self.assertEqual(guide.count("<thead>"), 2)
        self.assertEqual(guide.count("<tbody>"), 2)
        self.assertEqual(guide.count('scope="col"'), 6)


if __name__ == "__main__":
    unittest.main()
