"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'secured-exit-approach-review',
 'name': 'Secured Exit Approach Review',
 'tagline': 'Flags anonymous approach or crossing patterns at configured secured exits and '
            'attaches nearby door-event context for human review.',
 'category': 'Healthcare & Senior Living',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'approach_zone': 'polygon — secured-exit approach area',
                   'exit_line': 'two-point line — configured exit threshold',
                   'approach_seconds': 'float — continuous approach dwell before review (default '
                                       '8)',
                   'direction': 'enum — any, positive, or negative line direction',
                   'door_id': 'string — optional UniFi Access door ID',
                   'privacy_mode': 'enum — skeleton suppresses alert snapshots'}}

CAMERA_ZONES = {'approach_zone': 'secured_exit_approach', 'exit_line': 'secured_exit_line'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'secured_exit'
    profile = {'zones': {'approach': 'secured_exit_approach', 'exit_line': 'secured_exit_line'},
 'approach_seconds': 8,
 'direction': 'any'}
