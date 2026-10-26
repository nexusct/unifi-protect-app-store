"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'controlled-room-two-person-review',
 'name': 'Controlled-Room Person-Count Review',
 'tagline': 'Correlates a configured door grant with an anonymous visual count and reports whether '
            'the observed count matched policy.',
 'category': 'Healthcare & Senior Living',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'door_zone': 'polygon — controlled-room doorway observation area',
                   'door_id': 'string — UniFi Access door ID',
                   'observe_seconds': 'float — visual correlation window (default 15)',
                   'expected_persons': 'int — configured review count (default 2)'}}

CAMERA_ZONES = {'door_zone': 'controlled_room_door'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'controlled_room_count'
    profile = {'zones': {'door': 'controlled_room_door'}, 'observe_seconds': 15, 'expected_persons': 2}
