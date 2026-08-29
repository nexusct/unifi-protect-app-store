"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'curbside-handoff-timer',
 'name': 'Curbside Handoff Timer',
 'tagline': 'Correlates anonymous vehicle arrival, person handoff overlap, departure, and '
            'excessive curbside wait.',
 'category': 'Retail & QSR',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'arrival_zone': 'polygon — curbside vehicle arrival area',
                   'handoff_zone': 'polygon — handoff interaction area',
                   'departure_line': 'two-point line — curbside departure threshold',
                   'max_wait_seconds': 'float — maximum curbside wait (default 300)'}}

CAMERA_ZONES = {'arrival_zone': 'curbside_arrival',
 'handoff_zone': 'curbside_handoff',
 'departure_line': 'curbside_departure_line'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'curbside_handoff'
    profile = {'zones': {'arrival': 'curbside_arrival',
           'handoff': 'curbside_handoff',
           'departure': 'curbside_departure_line'},
 'max_wait_seconds': 300}
