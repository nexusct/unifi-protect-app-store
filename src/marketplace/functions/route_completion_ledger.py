"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'route-completion-ledger',
 'name': 'Route Completion Ledger',
 'tagline': 'Summarizes anonymous ordered checkpoint starts, completions, skipped-zone candidates, '
            'and completion time.',
 'category': 'Intelligence',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'checkpoint_a': 'polygon — route checkpoint A',
                   'checkpoint_b': 'polygon — route checkpoint B',
                   'checkpoint_c': 'polygon — route checkpoint C',
                   'checkpoint_d': 'polygon — route checkpoint D',
                   'route_window_seconds': 'float — maximum route duration (default 600)',
                   'digest_seconds': 'int — digest interval (default 600)',
                   'classes': 'list — COCO classes to include'}}

CAMERA_ZONES = {'checkpoint_a': 'route_checkpoint_a',
 'checkpoint_b': 'route_checkpoint_b',
 'checkpoint_c': 'route_checkpoint_c',
 'checkpoint_d': 'route_checkpoint_d'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'route_completion'
    profile = {'zones': {'checkpoint_a': 'route_checkpoint_a',
           'checkpoint_b': 'route_checkpoint_b',
           'checkpoint_c': 'route_checkpoint_c',
           'checkpoint_d': 'route_checkpoint_d'},
 'route_window_seconds': 600,
 'digest_seconds': 600,
 'classes': [0, 2, 3, 5, 7]}
