"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'shift-change-flow-review',
 'name': 'Shift Change Flow Review',
 'tagline': 'Summarizes anonymous ingress, egress, and person-vehicle overlap during configured '
            'shift-change windows.',
 'category': 'Intelligence',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'shift_zone': 'polygon — shift-change review area',
                   'ingress_line': 'two-point line — directional flow threshold',
                   'shift_windows': 'list — local time ranges such as 06:30-08:30',
                   'digest_seconds': 'int — digest interval (default 300)',
                   'overlap_distance_ratio': 'float — normalized person-vehicle proximity (default '
                                             '0.12)'}}

CAMERA_ZONES = {'shift_zone': 'shift_change_area', 'ingress_line': 'shift_ingress_line'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'shift_flow'
    profile = {'zones': {'shift': 'shift_change_area', 'ingress_line': 'shift_ingress_line'},
 'shift_windows': ['06:30-08:30', '14:30-16:30', '22:30-00:30'],
 'digest_seconds': 300,
 'overlap_distance_ratio': 0.12}
