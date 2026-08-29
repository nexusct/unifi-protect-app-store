"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'room-exit-sequence-review',
 'name': 'Room Exit Sequence Review',
 'tagline': 'Reviews anonymous bed-area, transition, and doorway progression without identifying '
            'residents or making a clinical determination.',
 'category': 'Healthcare & Senior Living',
 'tier': 'enterprise',
 'requires_gpu': True,
 'config_schema': {'bed_zone': 'polygon — anonymous room origin area',
                   'transition_zone': 'polygon — intermediate movement area',
                   'doorway_zone': 'polygon — room doorway area',
                   'sequence_window_seconds': 'float — maximum sequence duration (default 90)',
                   'privacy_mode': 'enum — skeleton suppresses alert snapshots'}}

CAMERA_ZONES = {'bed_zone': 'room_bed_area', 'transition_zone': 'room_transition', 'doorway_zone': 'room_doorway'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'room_exit_sequence'
    profile = {'zones': {'bed': 'room_bed_area', 'transition': 'room_transition', 'doorway': 'room_doorway'},
 'sequence_window_seconds': 90,
 'privacy_mode': 'skeleton'}
