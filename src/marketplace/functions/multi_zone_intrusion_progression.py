"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'multi-zone-intrusion-progression',
 'name': 'Multi-Zone Intrusion Progression Review',
 'tagline': 'Flags one anonymous track progressing through configured perimeter, yard, and doorway '
            'zones within a bounded window.',
 'category': 'Security & Access',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'perimeter_zone': 'polygon — outer perimeter stage',
                   'yard_zone': 'polygon — intermediate yard stage',
                   'doorway_zone': 'polygon — protected-door stage',
                   'progression_seconds': 'float — maximum progression window (default 120)',
                   'classes': 'list — COCO person and vehicle class IDs'}}

CAMERA_ZONES = {'perimeter_zone': 'intrusion_perimeter',
 'yard_zone': 'intrusion_yard',
 'doorway_zone': 'intrusion_doorway'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'intrusion_progression'
    profile = {'zones': {'perimeter': 'intrusion_perimeter',
           'yard': 'intrusion_yard',
           'doorway': 'intrusion_doorway'},
 'progression_seconds': 120,
 'classes': [0, 2, 3, 5, 7]}
