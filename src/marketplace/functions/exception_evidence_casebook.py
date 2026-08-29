"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'exception-evidence-casebook',
 'name': 'Exception Evidence Casebook',
 'tagline': 'Writes a bounded local redacted case package linking Access, Protect, and anonymous '
            'visual context.',
 'category': 'Intelligence',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'door_id': 'string — optional UniFi Access door ID',
                   'collect_seconds': 'int — evidence collection window (default 20)',
                   'retention_days': 'int — local package retention (default 30)',
                   'max_cases': 'int — maximum retained packages (default 500)',
                   'privacy_mode': 'enum — skeleton suppresses alert snapshots'}}

CAMERA_ZONES = {}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'evidence_casebook'
    profile = {'collect_seconds': 20, 'retention_days': 30, 'max_cases': 500}
