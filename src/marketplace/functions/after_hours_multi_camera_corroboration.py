"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'after-hours-multi-camera-corroboration',
 'name': 'After-Hours Multi-Camera Corroboration',
 'tagline': 'Corroborates anonymous after-hours person or vehicle classes on two cameras without '
            're-identification.',
 'category': 'Security & Access',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'monitored_zone': 'polygon — optional after-hours observation area',
                   'closed_hours': 'time range — local closed interval such as 22:00-06:00',
                   'corroboration_seconds': 'float — cross-camera time window (default 45)',
                   'classes': 'list — COCO person and vehicle class IDs'}}

CAMERA_ZONES = {'monitored_zone': 'after_hours_corroboration'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'multi_camera_corroboration'
    profile = {'zones': {'monitored': 'after_hours_corroboration'},
 'closed_hours': '22:00-06:00',
 'corroboration_seconds': 45,
 'classes': [0, 2, 3, 5, 7]}
