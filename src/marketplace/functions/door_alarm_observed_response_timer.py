"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'door-alarm-observed-response-timer',
 'name': 'Door Alarm Observed Response Timer',
 'tagline': 'Times anonymous observed response and door-close state after configured forced-open '
            'or held-open events.',
 'category': 'Security & Access',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'response_zone': 'polygon — area where response is observed',
                   'door_id': 'string — UniFi Access door ID',
                   'response_timeout_seconds': 'float — review timeout (default 180)'}}

CAMERA_ZONES = {'response_zone': 'door_response_zone'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'door_response'
    profile = {'zones': {'response': 'door_response_zone'}, 'response_timeout_seconds': 180}
