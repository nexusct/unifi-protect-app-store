"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'dock-apron-conflict-review',
 'name': 'Dock Apron Conflict Review',
 'tagline': 'Flags anonymous person and vehicle tracks that remain close and converging in a '
            'configured dock apron.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'apron_zone': 'polygon — dock conflict-review area',
                   'conflict_distance_ratio': 'float — normalized proximity threshold (default '
                                              '0.14)',
                   'hold_seconds': 'float — sustained converging condition (default 1.5)'}}

CAMERA_ZONES = {'apron_zone': 'dock_apron'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'trajectory_conflict'
    profile = {'zones': {'apron': 'dock_apron'}, 'conflict_distance_ratio': 0.14, 'hold_seconds': 1.5}
