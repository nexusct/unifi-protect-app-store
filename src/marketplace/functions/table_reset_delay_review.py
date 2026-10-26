"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'table-reset-delay-review',
 'name': 'Table Reset Delay Review',
 'tagline': 'Reviews prolonged vacant-table periods without the expected service approach and '
            'visible scene-change pattern.',
 'category': 'Retail & QSR',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'table_zone': 'polygon — table occupancy and reset area',
                   'service_approach_zone': 'polygon — staff approach area',
                   'reset_seconds': 'float — maximum vacant delay (default 180)',
                   'scene_change_threshold': 'float — normalized reset-change threshold (default '
                                             '0.08)'}}

CAMERA_ZONES = {'table_zone': 'table_reset_area', 'service_approach_zone': 'table_service_approach'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'table_reset'
    profile = {'zones': {'table': 'table_reset_area', 'service_approach': 'table_service_approach'},
 'reset_seconds': 180,
 'scene_change_threshold': 0.08}
