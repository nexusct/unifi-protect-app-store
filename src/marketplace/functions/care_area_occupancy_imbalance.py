"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'care-area-occupancy-imbalance',
 'name': 'Care-Area Occupancy Imbalance',
 'tagline': 'Compares anonymous counts in two configured care areas and flags sustained staffing '
            'or occupancy imbalance for review.',
 'category': 'Healthcare & Senior Living',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'zone_a': 'polygon — first care-area count zone',
                   'zone_b': 'polygon — second care-area count zone',
                   'imbalance_threshold': 'int — count difference requiring review (default 4)',
                   'hold_seconds': 'float — sustained imbalance duration (default 30)',
                   'privacy_mode': 'enum — skeleton suppresses alert snapshots'}}

CAMERA_ZONES = {'zone_a': 'care_zone_a', 'zone_b': 'care_zone_b'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'occupancy_imbalance'
    profile = {'zones': {'zone_a': 'care_zone_a', 'zone_b': 'care_zone_b'},
 'imbalance_threshold': 4,
 'hold_seconds': 30,
 'privacy_mode': 'skeleton'}
