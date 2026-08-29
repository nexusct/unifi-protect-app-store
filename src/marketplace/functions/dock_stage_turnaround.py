"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'dock-stage-turnaround',
 'name': 'Dock Stage Turnaround',
 'tagline': 'Times anonymous vehicle progression through arrival, staging, dock, and departure '
            'with stage-delay review.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'arrival_zone': 'polygon — dock arrival stage',
                   'staging_zone': 'polygon — staging stage',
                   'dock_zone': 'polygon — dock stage',
                   'departure_zone': 'polygon — departure stage',
                   'turnaround_seconds': 'float — maximum whole-route window (default 7200)',
                   'stage_timeout_seconds': 'float — maximum stage duration (default 1800)'}}

CAMERA_ZONES = {'arrival_zone': 'dock_arrival',
 'staging_zone': 'dock_staging',
 'dock_zone': 'dock_bay',
 'departure_zone': 'dock_departure'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'dock_turnaround'
    profile = {'zones': {'arrival': 'dock_arrival',
           'staging': 'dock_staging',
           'dock': 'dock_bay',
           'departure': 'dock_departure'},
 'turnaround_seconds': 7200,
 'stage_timeout_seconds': 1800}
