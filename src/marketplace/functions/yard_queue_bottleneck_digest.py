"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'yard-queue-bottleneck-digest',
 'name': 'Yard Queue Bottleneck Digest',
 'tagline': 'Summarizes anonymous vehicle counts across yard queue, staging, and dock zones with '
            'spillback candidates.',
 'category': 'Manufacturing & Warehouse',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'queue_zone': 'polygon — yard queue area',
                   'staging_zone': 'polygon — yard staging area',
                   'dock_zone': 'polygon — dock-service area',
                   'digest_seconds': 'int — digest interval (default 300)',
                   'spillback_threshold': 'int — queue count requiring review (default 6)'}}

CAMERA_ZONES = {'queue_zone': 'yard_queue', 'staging_zone': 'yard_staging', 'dock_zone': 'yard_dock'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'yard_queue'
    profile = {'zones': {'queue': 'yard_queue', 'staging': 'yard_staging', 'dock': 'yard_dock'},
 'digest_seconds': 300,
 'spillback_threshold': 6}
