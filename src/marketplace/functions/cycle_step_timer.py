"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'cycle-step-timer',
 'name': 'Cycle Step Timer',
 'tagline': 'Uses customer-model stage labels to time workcell cycles and review skipped or '
            'overdue steps.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'workcell_zone': 'polygon — workcell observation area',
                   'weights': 'path — customer-supplied stage model weights',
                   'confidence': 'float — minimum custom-model confidence (default 0.45)',
                   'expected_sequence': 'list — ordered customer-model stage labels',
                   'max_step_seconds': 'float — maximum step duration (default 120)'}}

CAMERA_ZONES = {'workcell_zone': 'cycle_workcell'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'domain_sequence'
    profile = {'zones': {'workcell': 'cycle_workcell'},
 'expected_sequence': ['stage-a', 'stage-b', 'stage-c'],
 'max_step_seconds': 120}
