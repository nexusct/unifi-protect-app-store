"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'high-traffic-service-trigger',
 'name': 'High-Traffic Service Trigger',
 'tagline': 'Raises a service-review trigger when anonymous crossings exceed a configured rolling '
            'traffic threshold.',
 'category': 'Retail & QSR',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'service_zone': 'polygon — service area associated with the trigger',
                   'traffic_line': 'two-point line — traffic counting threshold',
                   'event_threshold': 'int — crossings required (default 20)',
                   'window_seconds': 'float — rolling count window (default 300)',
                   'classes': 'list — COCO classes to count'}}

CAMERA_ZONES = {'service_zone': 'high_traffic_service', 'traffic_line': 'high_traffic_line'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'traffic_trigger'
    profile = {'zones': {'service': 'high_traffic_service', 'traffic_line': 'high_traffic_line'},
 'event_threshold': 20,
 'window_seconds': 300,
 'classes': [0]}
