from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


class UnraidPackagingContractTests(unittest.TestCase):
    def _template(self, name: str) -> ET.Element:
        path = ROOT / "unraid" / name
        self.assertTrue(path.is_file(), name)
        return ET.parse(path).getroot()

    def test_cpu_and_gpu_templates_are_installable_and_differ_only_at_compute_seam(self):
        cpu = self._template("nexus-vision-ai-cpu.xml")
        gpu = self._template("nexus-vision-ai-gpu.xml")
        for template in (cpu, gpu):
            self.assertEqual(template.tag, "Container")
            self.assertEqual(template.attrib.get("version"), "2")
            self.assertEqual(template.findtext("Repository"), "ghcr.io/nexusct/unifi-protect-app-store:latest")
            self.assertEqual(template.findtext("Network"), "bridge")
            self.assertEqual(template.findtext("Privileged"), "false")
            self.assertIn("[PORT:8090]/setup/", template.findtext("WebUI") or "")
            self.assertIn("x86-64", template.findtext("Requires") or "")
            configs = template.findall("Config")
            targets = {item.attrib.get("Target"): item for item in configs}
            for target, suffix in {
                "/config": "config",
                "/data": "data",
                "/models": "models",
                "/evidence": "evidence",
            }.items():
                self.assertIn(target, targets)
                self.assertEqual(
                    targets[target].attrib.get("Default"),
                    f"/mnt/user/appdata/nexus-vision-ai/{suffix}",
                )
                self.assertEqual(targets[target].attrib.get("Mode"), "rw")
            self.assertEqual(targets["8090"].attrib.get("Type"), "Port")
            self.assertEqual(targets["VISION_ADMIN_TOKEN"].attrib.get("Mask"), "true")
            self.assertEqual(targets["VISION_CONTROL_TOKEN"].attrib.get("Mask"), "true")
            self.assertEqual(targets["VISION_CONFIG"].attrib.get("Default"), "/config/sites.yaml")
            self.assertEqual(targets["VISION_DATA"].attrib.get("Default"), "/data")
            self.assertEqual(targets["VISION_LICENSE_DIR"].attrib.get("Default"), "/config/licensing")
            self.assertEqual(
                targets["VISION_ENTITLEMENT_TRUST_STORE"].attrib.get("Default"),
                "/config/trusted-entitlement-keys.json",
            )
            self.assertEqual(targets["VISION_ENTITLEMENT_TRUST_STORE"].attrib.get("Mask"), "false")
            self.assertEqual(targets["VISION_SETUP_RESTART_ENABLED"].attrib.get("Default"), "true")
        cpu_targets = {item.attrib.get("Target"): item for item in cpu.findall("Config")}
        gpu_targets = {item.attrib.get("Target"): item for item in gpu.findall("Config")}
        self.assertEqual(cpu_targets["VISION_DEVICE"].attrib.get("Default"), "cpu")
        self.assertEqual(gpu_targets["VISION_DEVICE"].attrib.get("Default"), "cuda")
        self.assertNotIn("runtime=nvidia", cpu.findtext("ExtraParams") or "")
        self.assertIn("--runtime=nvidia", gpu.findtext("ExtraParams") or "")
        self.assertEqual(gpu_targets["NVIDIA_VISIBLE_DEVICES"].attrib.get("Default"), "all")

    def test_image_has_first_boot_entrypoint_liveness_healthcheck_and_amd64_publisher(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY docker/entrypoint.sh /app/docker/entrypoint.sh", dockerfile)
        self.assertIn('ENTRYPOINT ["/app/docker/entrypoint.sh"]', dockerfile)
        self.assertRegex(dockerfile, r"HEALTHCHECK[^\n]*")
        self.assertIn("/health", dockerfile)
        entrypoint = ROOT / "docker" / "entrypoint.sh"
        self.assertTrue(entrypoint.is_file())
        source = entrypoint.read_text(encoding="utf-8")
        self.assertIn("sites.unraid.yaml", source)
        self.assertIn("trusted-entitlement-keys.json", source)
        self.assertIn("VISION_ENTITLEMENT_TRUST_STORE", source)
        self.assertIn("/opt/nvidia/nvidia_entrypoint.sh", source)
        workflow = (ROOT / ".github" / "workflows" / "container.yml").read_text(encoding="utf-8")
        self.assertIn("linux/amd64", workflow)
        self.assertIn("ghcr.io", workflow)
        self.assertIn("packages: write", workflow)
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("!config/sites.unraid.yaml", dockerignore)

    def test_compose_uses_the_same_writable_runtime_layout_without_exposing_admin_port(self):
        compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        compose = yaml.safe_load(compose_text)
        base = compose["x-vision-base"]
        self.assertEqual(base["env_file"], [{"path": ".env", "required": False}])
        self.assertEqual(base["ports"], ["127.0.0.1:8090:8090"])
        self.assertEqual(
            set(base["volumes"]),
            {"./config:/config", "./data:/data", "./models:/models", "./evidence:/evidence"},
        )
        environment = base["environment"]
        for key, value in {
            "VISION_CONFIG": "/config/sites.yaml",
            "VISION_RUNTIME_SETTINGS": "/config/runtime-settings.json",
            "VISION_DATA": "/data",
            "VISION_MODELS": "/models",
            "VISION_EVIDENCE": "/evidence",
            "VISION_LICENSE_DIR": "/config/licensing",
            "VISION_ENTITLEMENT_TRUST_STORE": "/config/trusted-entitlement-keys.json",
            "VISION_SETUP_RESTART_ENABLED": "true",
        }.items():
            self.assertEqual(str(environment[key]), value)
        self.assertIn("/health", " ".join(base["healthcheck"]["test"]))
        self.assertNotIn("/ready", " ".join(base["healthcheck"]["test"]))

    def test_first_run_config_and_offline_setup_page_are_baked_into_image(self):
        initial = yaml.safe_load((ROOT / "config" / "sites.unraid.yaml").read_text(encoding="utf-8"))
        self.assertEqual(initial["site"]["timezone"], "UTC")
        self.assertEqual(initial["cameras"], [])
        setup_page = (ROOT / "setup" / "index.html").read_text(encoding="utf-8")
        self.assertIn("UniFi Protect", setup_page)
        self.assertIn("x-admin-token", setup_page)
        self.assertIn("/api/setup/status", setup_page)
        self.assertIn("/api/setup/protect/certificate", setup_page)
        self.assertIn("/api/setup/protect/discover", setup_page)
        self.assertIn("/api/setup/save", setup_page)
        self.assertIn("/api/setup/restart", setup_page)
        self.assertIn("/ready", setup_page)
        self.assertIn('id="camera-list"', setup_page)
        self.assertIn("aria-live", setup_page)
        self.assertNotIn("localStorage", setup_page)
        self.assertNotIn("sessionStorage", setup_page)
        self.assertNotRegex(setup_page, r"https?://(?:cdn|unpkg|jsdelivr)")

    def test_restart_callback_is_disabled_by_default_and_schedules_one_exit_when_enabled(self):
        from process_control import setup_restart_callback

        timer = Mock()
        timer_factory = Mock(return_value=timer)
        exit_fn = Mock()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(setup_restart_callback(timer_factory=timer_factory, exit_fn=exit_fn))
        with patch.dict(os.environ, {"VISION_SETUP_RESTART_ENABLED": "true"}, clear=True):
            callback = setup_restart_callback(timer_factory=timer_factory, exit_fn=exit_fn)
            self.assertIsNotNone(callback)
            callback()
        timer_factory.assert_called_once()
        timer.start.assert_called_once()

    def test_custom_detector_weights_resolve_through_the_persistent_model_volume(self):
        from model_paths import model_path

        with patch.dict(os.environ, {"VISION_MODELS": "/models"}, clear=False):
            self.assertEqual(model_path("plate.pt"), "/models/plate.pt")
        for relative in (
            "src/detectors/alpr.py",
            "src/detectors/ppe.py",
            "src/detectors/smoke_flame.py",
            "src/detectors/weapon.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("model_path(", source, relative)
            self.assertNotIn('"/app/models/', source, relative)

    def test_readme_documents_the_turnkey_unraid_and_wizard_path(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for required in (
            "nexus-vision-ai-cpu.xml",
            "nexus-vision-ai-gpu.xml",
            "/setup/",
            "/mnt/user/appdata/nexus-vision-ai/config",
            "/mnt/user/appdata/nexus-vision-ai/models",
            "Linux AMD64",
            "7441",
            "VISION_ADMIN_TOKEN",
            "VISION_ENTITLEMENT_TRUST_STORE",
            "public verification keys",
            "Never place private signing keys",
        ):
            self.assertIn(required, readme)


class SetupPersistenceContractTests(unittest.TestCase):
    def test_save_keeps_secrets_out_of_site_yaml_and_uses_owner_only_settings_file(self):
        from setup_service import SetupStore

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SetupStore(root / "sites.yaml", root / "runtime-settings.json", root / "certs")
            result = store.save(
                site_name="North Campus",
                timezone_name="America/Chicago",
                connection={
                    "host": "192.168.50.1",
                    "port": 443,
                    "username": "vision-service",
                    "password": "not-logged-or-returned",
                    "tls_mode": "system",
                },
                cameras=[
                    {
                        "id": "65f123abc",
                        "name": "North Entry",
                        "rtsp": "rtsps://192.168.50.1:7441/north-entry",
                        "detectors": ["fall", "camera-tamper"],
                    }
                ],
            )
            config_text = (root / "sites.yaml").read_text(encoding="utf-8")
            settings_text = (root / "runtime-settings.json").read_text(encoding="utf-8")
            self.assertNotIn("not-logged-or-returned", config_text)
            self.assertNotIn("vision-service", config_text)
            self.assertIn("not-logged-or-returned", settings_text)
            self.assertEqual(stat.S_IMODE((root / "runtime-settings.json").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((root / "sites.yaml").stat().st_mode), 0o600)
            self.assertEqual(
                result,
                {"saved": True, "camera_count": 1, "restart_required": True},
            )

    def test_save_rejects_untrusted_camera_records_and_invalid_timezones(self):
        from setup_service import SetupStore, SetupValidationError

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SetupStore(root / "sites.yaml", root / "runtime-settings.json", root / "certs")
            common = {
                "site_name": "Site",
                "connection": {
                    "host": "unifi.local",
                    "port": 443,
                    "username": "service",
                    "password": "secret",
                    "tls_mode": "system",
                },
            }
            with self.assertRaises(SetupValidationError):
                store.save(
                    **common,
                    timezone_name="Not/A-Timezone",
                    cameras=[{"id": "../../etc/passwd", "name": "Bad", "rtsp": None, "detectors": []}],
                )
            with self.assertRaises(SetupValidationError):
                store.save(
                    **common,
                    timezone_name="UTC",
                    cameras=[{"id": "camera", "name": "Bad", "rtsp": "file:///etc/passwd", "detectors": []}],
                )

    def test_runtime_settings_are_a_fallback_and_environment_wins(self):
        from runtime_settings import runtime_setting

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime-settings.json"
            path.write_text(json.dumps({"UNIFI_PROTECT_HOST": "saved.local"}), encoding="utf-8")
            with patch.dict(
                os.environ,
                {"VISION_RUNTIME_SETTINGS": str(path), "UNIFI_PROTECT_HOST": "env.local"},
                clear=False,
            ):
                self.assertEqual(runtime_setting("UNIFI_PROTECT_HOST"), "env.local")
            with patch.dict(os.environ, {"VISION_RUNTIME_SETTINGS": str(path)}, clear=True):
                self.assertEqual(runtime_setting("UNIFI_PROTECT_HOST"), "saved.local")


if __name__ == "__main__":
    unittest.main()
