"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'waiting-room-flow-ledger',
 'name': 'Waiting-Room Flow Ledger',
 'tagline': 'Summarizes anonymous arrivals, waiting transitions, service starts, exits, and '
            'abandonment candidates.',
 'category': 'Healthcare & Senior Living',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'arrival_zone': 'polygon — waiting-room arrival area',
                   'waiting_zone': 'polygon — waiting area',
                   'service_zone': 'polygon — service-entry area',
                   'exit_zone': 'polygon — exit area',
                   'digest_seconds': 'int — digest interval (default 300)',
                   'abandonment_seconds': 'int — stale waiting track threshold (default 900)'}}

CAMERA_ZONES = {'arrival_zone': 'waiting_arrival',
 'waiting_zone': 'waiting_area',
 'service_zone': 'waiting_service',
 'exit_zone': 'waiting_exit'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'waiting_flow'
    profile = {'zones': {'arrival': 'waiting_arrival',
           'waiting': 'waiting_area',
           'service': 'waiting_service',
           'exit': 'waiting_exit'},
 'digest_seconds': 300,
 'abandonment_seconds': 900}
