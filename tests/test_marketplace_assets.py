from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from xml.parsers import expat

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from marketplace import loader
from marketplace.contract import validate_manifest
from marketplace.runtime import build_camera_detectors
from api import detector_status_payload


def load_script(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


catalog_builder = load_script("catalog_builder", ROOT / "scripts" / "build_marketplace_catalog.py")
icon_generator = load_script("icon_generator", ROOT / "scripts" / "generate_marketplace_icons.py")


class ManifestContractTests(unittest.TestCase):
    def test_all_source_manifests_are_literal_unique_and_valid(self):
        manifests = []
        for path in sorted((SRC / "marketplace" / "functions").glob("*.py")):
            if path.name.startswith("_"):
                continue
            manifest = catalog_builder.manifest_from_file(path)
            self.assertEqual(validate_manifest(manifest), [], path.name)
            manifests.append(manifest)

        ids = [manifest["id"] for manifest in manifests]
        self.assertEqual(len(manifests), 150)
        self.assertEqual(len(ids), len(set(ids)))

    def test_manifest_rejects_unsafe_ids_and_multiline_copy(self):
        base = {
            "name": "Safe name",
            "tagline": "Safe tagline",
            "category": "Intelligence",
            "tier": "starter",
        }
        for unsafe_id in ("../escape", "Uppercase", "space id", "/absolute", "x.svg"):
            errors = validate_manifest({**base, "id": unsafe_id})
            self.assertTrue(any("id must" in error for error in errors), unsafe_id)

        errors = validate_manifest({**base, "id": "safe-id", "tagline": "line one\nline two"})
        self.assertTrue(any("single-line" in error for error in errors))

        for unsafe_character in ("\x00", "\x1f", "\x85", "\u2028", "\u2029", "\ufffe"):
            errors = validate_manifest({**base, "id": "safe-id", "tagline": f"unsafe{unsafe_character}text"})
            self.assertTrue(any("single-line" in error for error in errors), repr(unsafe_character))

    def test_loader_rejects_duplicate_ids(self):
        module_template = '''from marketplace.contract import MarketplaceFunction
MANIFEST = {
    "id": "duplicate-id",
    "name": "%s",
    "tagline": "Test module",
    "category": "Intelligence",
    "tier": "starter",
}
class Function(MarketplaceFunction):
    pass
'''
        original_dir = loader.FUNCTIONS_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                (directory / "a.py").write_text(module_template % "First", encoding="utf-8")
                (directory / "b.py").write_text(module_template % "Second", encoding="utf-8")
                loader.FUNCTIONS_DIR = directory
                registry, errors = loader.load_all()
                self.assertEqual(list(registry), ["duplicate-id"])
                self.assertIn("b", errors)
                self.assertIn("duplicate id", errors["b"])
        finally:
            loader.FUNCTIONS_DIR = original_dir
            loader.REGISTRY.clear()

    def test_loader_rejects_non_contract_function_class(self):
        source = '''MANIFEST = {
    "id": "invalid-class",
    "name": "Invalid class",
    "tagline": "Test module",
    "category": "Intelligence",
    "tier": "starter",
}
class Function:
    pass
'''
        original_dir = loader.FUNCTIONS_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                (directory / "invalid.py").write_text(source, encoding="utf-8")
                loader.FUNCTIONS_DIR = directory
                registry, errors = loader.load_all()
                self.assertEqual(registry, {})
                self.assertEqual(errors["invalid"], "Function must subclass MarketplaceFunction")
        finally:
            loader.FUNCTIONS_DIR = original_dir
            loader.REGISTRY.clear()

    def test_catalog_builder_rejects_non_contract_function_class(self):
        source = '''MANIFEST = {
    "id": "invalid-class",
    "name": "Invalid class",
    "tagline": "Test module",
    "category": "Intelligence",
    "tier": "starter",
}
class Function:
    pass
'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.py"
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approved marketplace base"):
                catalog_builder.manifest_from_file(path)


class GeneratedAssetTests(unittest.TestCase):
    def test_catalog_atomic_write_installs_public_readable_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "catalog.json"
            catalog_builder.atomic_write(path, "[]\n")

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_vendor_art_generator_covers_exact_20_with_unique_transparent_images(self):
        path = ROOT / "scripts" / "generate_vendor_module_art.py"
        self.assertTrue(path.is_file(), "vendor art generator is missing")
        generator = load_script("vendor_art_generator", path)
        selection = json.loads(
            (SRC / "marketplace" / "active-function-ids.json").read_text(
                encoding="utf-8"
            )
        )
        expected = set(selection["vendor_inspired_ids"])
        self.assertEqual(set(generator.SCENES), expected)
        hashes = set()
        for module_id in sorted(expected):
            self.assertEqual(
                set(generator.SCENES[module_id]),
                {"subject", "context", "signal", "composition"},
            )
            image = generator.draw_art({"id": module_id})
            self.assertEqual(image.size, (320, 320))
            self.assertEqual(image.mode, "RGBA")
            self.assertTrue(
                all(image.getpixel(point)[3] == 0 for point in ((0, 0), (319, 0), (0, 319), (319, 319)))
            )
            self.assertIsNotNone(image.getchannel("A").getbbox())
            hashes.add(hashlib.sha256(image.tobytes()).hexdigest())
        self.assertEqual(len(hashes), 20)

    def test_catalog_json_and_javascript_are_identical(self):
        catalog = json.loads((ROOT / "storefront" / "catalog.json").read_text(encoding="utf-8"))
        script = (ROOT / "storefront" / "catalog.js").read_text(encoding="utf-8")
        assignment = script.index("window.CATALOG_DATA = ") + len("window.CATALOG_DATA = ")
        inlined = json.loads(script[assignment:].strip().removesuffix(";"))

        self.assertEqual(catalog, inlined)
        self.assertEqual(len(catalog), 100)
        self.assertEqual(catalog, sorted(catalog, key=lambda row: (row["name"].casefold(), row["id"])))
        self.assertTrue(all(row["config_keys"] == sorted(row["config_schema"]) for row in catalog))
        self.assertTrue(all(row["setting_keys"] == sorted(set(row["config_schema"]) - set(row["camera_zones"])) for row in catalog))

    def test_catalog_geometry_matches_runtime_camera_zone_lookups(self):
        catalog = {
            row["id"]: row
            for row in json.loads((ROOT / "storefront" / "catalog.json").read_text(encoding="utf-8"))
        }
        active_geometry_modules = 0
        source_geometry_modules = 0
        for path in sorted((SRC / "marketplace" / "functions").glob("*.py")):
            if path.name.startswith("_"):
                continue
            manifest = catalog_builder.manifest_from_file(path)
            schema = dict(manifest.get("config_schema") or {})
            mapping = catalog_builder.camera_zone_map_from_file(path, schema)
            source_geometry_modules += bool(mapping)
            if manifest["id"] in catalog:
                self.assertEqual(catalog[manifest["id"]]["camera_zones"], mapping, path.name)
                active_geometry_modules += bool(mapping)

        self.assertEqual(source_geometry_modules, 133)
        self.assertEqual(active_geometry_modules, 55)
        self.assertEqual(catalog["wrong-way"]["camera_zones"], {"line": "oneway_line"})
        self.assertEqual(
            catalog_builder.camera_zone_map_from_file(
                SRC / "marketplace" / "functions" / "service_lane_cycle.py",
                catalog_builder.manifest_from_file(
                    SRC / "marketplace" / "functions" / "service_lane_cycle.py"
                )["config_schema"],
            ),
            {"entry_zone": "service_entry", "exit_zone": "service_exit"},
        )
        self.assertEqual(catalog["dwell-analytics"]["camera_zones"], {"zones": "*"})

    def test_generated_catalog_matches_runtime_registry(self):
        catalog = json.loads((ROOT / "storefront" / "catalog.json").read_text(encoding="utf-8"))
        registry, errors = loader.load_all()
        self.assertEqual(errors, {})
        self.assertEqual({row["id"] for row in catalog}, set(registry))

    def test_runtime_instantiates_marketplace_detector_from_download_schema(self):
        registry, errors = loader.load_all()
        self.assertEqual(errors, {})
        detector_id = "wrong-way"
        classes = {function_id: entry["cls"] for function_id, entry in registry.items()}
        cameras = [{
            "id": "cam-1",
            "name": "Camera 1",
            "detectors": [detector_id],
            detector_id: {"forbidden": "backward"},
        }]
        settings = {detector_id: {"forbidden": "forward"}}
        configured = build_camera_detectors(cameras, settings, classes)
        self.assertEqual(len(configured["cam-1"]), 1)
        self.assertEqual(configured["cam-1"][0].settings["forbidden"], "backward")
        self.assertEqual(configured["cam-1"][0].forbidden, -1)
        self.assertEqual(configured["cam-1"][0].name, detector_id)
        self.assertEqual(detector_status_payload(configured), {"cam-1": [detector_id]})

    def test_runtime_rejects_unknown_configured_detector(self):
        cameras = [{"id": "cam-1", "name": "Camera 1", "detectors": ["missing-module"]}]
        with self.assertRaisesRegex(ValueError, "unknown detector 'missing-module' on 'Camera 1'"):
            build_camera_detectors(cameras, {}, {})

    def test_icon_manifest_matches_catalog_and_svgs_are_self_contained(self):
        catalog = json.loads((ROOT / "storefront" / "catalog.json").read_text(encoding="utf-8"))
        icons = ROOT / "assets" / "icons"
        manifest = json.loads((icons / "manifest.json").read_text(encoding="utf-8"))
        ids = {row["id"] for row in catalog}
        module_files = {path.stem for path in icons.glob("*.svg") if not path.name.startswith("_")}

        self.assertEqual(ids, set(manifest))
        self.assertEqual(ids, module_files)
        self.assertTrue((icons / "_fallback.svg").is_file())
        self.assertLess(sum(path.stat().st_size for path in icons.glob("*.svg")), 250_000)

        forbidden_tags = {"script", "image", "foreignObject", "use"}
        for path in icons.glob("*.svg"):
            self.assertLess(path.stat().st_size, 4_096, path.name)
            text = path.read_text(encoding="utf-8")
            elements = []
            parser = expat.ParserCreate(namespace_separator="}")
            parser.StartDoctypeDeclHandler = lambda *_args: (_ for _ in ()).throw(ValueError("DOCTYPE forbidden"))
            parser.EntityDeclHandler = lambda *_args: (_ for _ in ()).throw(ValueError("entities forbidden"))
            parser.ExternalEntityRefHandler = lambda *_args: 0
            parser.StartElementHandler = lambda name, attrs: elements.append((name.rsplit("}", 1)[-1], attrs))
            parser.Parse(text, True)

            self.assertEqual(elements[0][1].get("role"), "img", path.name)
            self.assertTrue(any(name == "title" for name, _attrs in elements), path.name)
            for local_name, attributes in elements:
                self.assertNotIn(local_name, forbidden_tags, path.name)
                for attribute in attributes:
                    self.assertFalse(attribute.lower().startswith("on"), f"{path.name}: {attribute}")
                    self.assertFalse(attribute.lower().endswith("href"), f"{path.name}: {attribute}")

    def test_service_art_processor_removes_white_background_and_centers_subject(self):
        processor = ROOT / "scripts" / "process_service_art.py"
        self.assertTrue(processor.is_file(), "service-art processor is missing")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "source.png"
            output = directory / "output.webp"
            image = Image.new("RGB", (640, 640), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((180, 120, 460, 520), fill="#01183e")
            draw.line((110, 520, 530, 520), fill="#006fff", width=36)
            image.save(source)

            subprocess.run([sys.executable, str(processor), str(source), str(output)], check=True)
            with Image.open(output) as rendered:
                rgba = rendered.convert("RGBA")
                self.assertEqual(rgba.size, (320, 320))
                alpha = rgba.getchannel("A")
                self.assertEqual(cast(int, alpha.getpixel((0, 0))), 0)
                self.assertGreater(cast(int, alpha.getpixel((160, 160))), 240)
                bounds = alpha.getbbox()
                self.assertIsNotNone(bounds)
                left, top, right, bottom = bounds or (0, 0, 0, 0)
                self.assertGreaterEqual(min(left, top, 320 - right, 320 - bottom), 12)
                self.assertLessEqual(max(left, top, 320 - right, 320 - bottom), 48)

    def test_service_art_prompt_registry_uses_text_free_scene_plan(self):
        catalog = json.loads((ROOT / "storefront" / "catalog.json").read_text(encoding="utf-8"))
        art = ROOT / "assets" / "module-art"
        registry_path = art / "prompts.json"
        scene_plan_path = art / "scene-plan.json"
        self.assertTrue(registry_path.is_file())
        self.assertTrue(scene_plan_path.is_file())
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        scene_plan = json.loads(scene_plan_path.read_text(encoding="utf-8"))
        catalog_ids = {row["id"] for row in catalog}
        self.assertEqual(set(registry), catalog_ids)
        self.assertEqual(set(scene_plan), catalog_ids)
        seeds = set()
        for row in catalog:
            entry = registry[row["id"]]
            scene = scene_plan[row["id"]]
            self.assertEqual(set(scene), {"subject", "context", "signal", "composition"})
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in scene.values()))
            self.assertTrue(all(value in entry["prompt"] for value in scene.values()))
            self.assertNotIn(f"'{row['name']}'", entry["prompt"])
            self.assertNotIn(row["tagline"], entry["prompt"])
            self.assertIn("Pure pictorial marketplace icon scene", entry["prompt"])
            self.assertIn("Pure flat white contiguous background", entry["prompt"])
            self.assertIn("No colored square or tile", entry["prompt"])
            self.assertNotIn("warm grey background", entry["prompt"])
            seeds.add(entry["seed"])
        self.assertEqual(len(seeds), len(catalog))

    def test_every_catalog_service_has_transparent_optimized_art(self):
        catalog = json.loads((ROOT / "storefront" / "catalog.json").read_text(encoding="utf-8"))
        ids = {row["id"] for row in catalog}
        art = ROOT / "assets" / "module-art"
        files = {path.stem: path for path in art.glob("*.webp")}
        manifest_source = (art / "manifest.js").read_text(encoding="utf-8")
        manifest_ids = set(json.loads(manifest_source.split("window.MODULE_ART = ", 1)[1].removesuffix(";\n")))

        self.assertEqual(set(files), ids)
        self.assertEqual(manifest_ids, ids)
        self.assertLess(sum(path.stat().st_size for path in files.values()), 8_000_000)
        for module_id, path in files.items():
            self.assertLess(path.stat().st_size, 100_000, module_id)
            with Image.open(path) as image:
                rgba = image.convert("RGBA")
                self.assertEqual(rgba.size, (320, 320), module_id)
                alpha = rgba.getchannel("A")
                self.assertTrue(all(cast(int, alpha.getpixel(point)) == 0 for point in ((0, 0), (319, 0), (0, 319), (319, 319))), module_id)
                self.assertIsNotNone(alpha.getbbox(), module_id)

    def test_svg_fallbacks_have_no_gradient_tiles(self):
        icons = ROOT / "assets" / "icons"
        for path in icons.glob("*.svg"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("linearGradient", source, path.name)
            self.assertNotIn('width="92" height="92"', source, path.name)
            self.assertNotIn("fill=\"url(#", source, path.name)

    def test_generators_are_deterministic(self):
        tracked = [
            ROOT / "storefront" / "catalog.json",
            ROOT / "storefront" / "catalog.js",
            *(ROOT / "assets" / "icons").glob("*"),
        ]

        def hashes():
            return {
                path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in tracked
                if path.is_file()
            }

        before = hashes()
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_marketplace_catalog.py")], check=True)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_marketplace_icons.py")], check=True)
        self.assertEqual(before, hashes())

    def test_icon_generator_fails_closed_on_path_traversal_id(self):
        original_catalog = icon_generator.CATALOG
        original_output = icon_generator.OUTPUT
        try:
            with tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                catalog_path = base / "catalog.json"
                output = base / "icons"
                catalog_path.write_text(json.dumps([{"id": "../escape"}]), encoding="utf-8")
                icon_generator.CATALOG = catalog_path
                icon_generator.OUTPUT = output
                with self.assertRaises(SystemExit):
                    icon_generator.main()
                self.assertFalse((base / "escape.svg").exists())
        finally:
            icon_generator.CATALOG = original_catalog
            icon_generator.OUTPUT = original_output


if __name__ == "__main__":
    unittest.main()
