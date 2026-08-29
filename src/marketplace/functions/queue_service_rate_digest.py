"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'queue-service-rate-digest',
 'name': 'Queue Service Rate Digest',
 'tagline': 'Summarizes anonymous queue arrivals, service starts, wait percentiles, and '
            'abandonment candidates.',
 'category': 'Retail & QSR',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'arrival_line': 'two-point line — queue-arrival threshold',
                   'queue_zone': 'polygon — queue area',
                   'service_zone': 'polygon — service area',
                   'exit_line': 'two-point line — queue-exit threshold',
                   'digest_seconds': 'int — digest interval (default 300)'}}

CAMERA_ZONES = {'arrival_line': 'queue_arrival_line',
 'queue_zone': 'queue_service_area',
 'service_zone': 'queue_service_point',
 'exit_line': 'queue_exit_line'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'queue_service'
    profile = {'zones': {'arrival_line': 'queue_arrival_line',
           'queue': 'queue_service_area',
           'service': 'queue_service_point',
           'exit_line': 'queue_exit_line'},
 'digest_seconds': 300}
