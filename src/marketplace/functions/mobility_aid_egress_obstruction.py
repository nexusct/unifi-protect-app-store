"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'mobility-aid-egress-obstruction',
 'name': 'Mobility-Aid Egress Obstruction Review',
 'tagline': 'Uses customer-supplied object weights to flag mobility aids that persist in a '
            'configured egress polygon.',
 'category': 'Healthcare & Senior Living',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'egress_zone': 'polygon — egress area that must remain passable',
                   'weights': 'path — customer-supplied mobility-aid model weights',
                   'labels': 'list — mobility-aid labels to observe',
                   'confidence': 'float — minimum custom-model confidence (default 0.45)',
                   'hold_seconds': 'float — persistence before review (default 20)'}}

CAMERA_ZONES = {'egress_zone': 'mobility_egress'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'mobility_obstruction'
    profile = {'zones': {'egress': 'mobility_egress'},
 'labels': ['wheelchair', 'walker', 'mobility-aid'],
 'hold_seconds': 20}
