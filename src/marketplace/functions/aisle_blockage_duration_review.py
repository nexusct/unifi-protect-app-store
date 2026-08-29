"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'aisle-blockage-duration-review',
 'name': 'Aisle Blockage Duration Review',
 'tagline': 'Flags non-person objects that persist in configured aisle or emergency-access '
            'polygons.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'aisle_zone': 'polygon — protected aisle area',
                   'emergency_access_zone': 'polygon — emergency-access area',
                   'weights': 'path — optional customer-supplied obstruction model weights',
                   'confidence': 'float — minimum model confidence (default 0.45)',
                   'hold_seconds': 'float — persistence before review (default 45)'}}

CAMERA_ZONES = {'aisle_zone': 'aisle_blockage_area', 'emergency_access_zone': 'emergency_access_area'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'persistent_obstruction'
    profile = {'zones': {'aisle': 'aisle_blockage_area', 'emergency_access': 'emergency_access_area'},
 'hold_seconds': 45}
