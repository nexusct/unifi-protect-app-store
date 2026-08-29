"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'forklift-route-deviation-review',
 'name': 'Forklift Route Deviation Review',
 'tagline': 'Uses customer-supplied forklift weights to flag corridor departure or forbidden '
            'line-crossing direction.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'allowed_corridor': 'polygon — permitted forklift corridor',
                   'direction_line': 'two-point line — direction review threshold',
                   'weights': 'path — customer-supplied forklift model weights',
                   'labels': 'list — forklift labels to observe',
                   'confidence': 'float — minimum custom-model confidence (default 0.45)',
                   'forbidden_direction': 'enum — positive or negative crossing direction',
                   'off_route_seconds': 'float — corridor departure hold (default 4)'}}

CAMERA_ZONES = {'allowed_corridor': 'forklift_allowed_corridor', 'direction_line': 'forklift_direction_line'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'domain_route'
    profile = {'zones': {'allowed_corridor': 'forklift_allowed_corridor',
           'direction_line': 'forklift_direction_line'},
 'labels': ['forklift'],
 'forbidden_direction': 'negative',
 'off_route_seconds': 4}
