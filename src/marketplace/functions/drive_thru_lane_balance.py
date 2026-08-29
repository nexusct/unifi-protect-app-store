"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'drive-thru-lane-balance',
 'name': 'Drive-Thru Lane Balance',
 'tagline': 'Compares anonymous vehicle occupancy between two drive-thru lanes and flags sustained '
            'imbalance.',
 'category': 'Retail & QSR',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'lane_a_zone': 'polygon — first drive-thru lane',
                   'lane_b_zone': 'polygon — second drive-thru lane',
                   'imbalance_count': 'int — count difference requiring review (default 2)',
                   'imbalance_seconds': 'float — sustained imbalance duration (default 60)'}}

CAMERA_ZONES = {'lane_a_zone': 'drive_thru_lane_a', 'lane_b_zone': 'drive_thru_lane_b'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'lane_balance'
    profile = {'zones': {'lane_a': 'drive_thru_lane_a', 'lane_b': 'drive_thru_lane_b'},
 'imbalance_count': 2,
 'imbalance_seconds': 60}
