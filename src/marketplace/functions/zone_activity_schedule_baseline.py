"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'zone-activity-schedule-baseline',
 'name': 'Zone Activity Schedule Baseline',
 'tagline': 'Learns anonymous hour-of-week activity counts and flags sustained deviations for '
            'contextual review.',
 'category': 'Intelligence',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'activity_zone': 'polygon — area used for schedule baseline',
                   'classes': 'list — COCO classes to include',
                   'min_samples': 'int — samples required per hour-of-week slot (default 12)',
                   'change_threshold': 'float — absolute count deviation (default 2.5)',
                   'hold_seconds': 'float — sustained deviation duration (default 30)'}}

CAMERA_ZONES = {'activity_zone': 'schedule_activity'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'schedule_baseline'
    profile = {'zones': {'activity': 'schedule_activity'},
 'classes': [0, 2, 3, 5, 7],
 'min_samples': 12,
 'change_threshold': 2.5,
 'hold_seconds': 30}
