"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'multi-class-flow-ledger',
 'name': 'Multi-Class Flow Ledger',
 'tagline': 'Produces directional anonymous line-crossing counts by configured person and vehicle '
            'object classes.',
 'category': 'Intelligence',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'crossing_line': 'two-point line — flow counting threshold',
                   'classes': 'list — COCO class IDs to include',
                   'digest_seconds': 'int — digest interval (default 300)'}}

CAMERA_ZONES = {'crossing_line': 'multi_class_flow_line'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'multi_class_flow'
    profile = {'zones': {'crossing_line': 'multi_class_flow_line'},
 'classes': [0, 2, 3, 5, 7],
 'digest_seconds': 300}
