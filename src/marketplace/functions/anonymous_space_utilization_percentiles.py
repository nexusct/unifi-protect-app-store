"""Independently implemented super skill; portfolio evidence is documented in docs/super-skill-portfolio.md."""

MANIFEST = {'id': 'anonymous-space-utilization-percentiles',
 'name': 'Anonymous Space Utilization Percentiles',
 'tagline': 'Reports anonymous occupancy percentiles and peak utilization for a configured space.',
 'category': 'Intelligence',
 'tier': 'pro',
 'requires_gpu': True,
 'config_schema': {'space_zone': 'polygon — anonymous occupancy area',
                   'sample_seconds': 'int — sample interval (default 5)',
                   'digest_seconds': 'int — percentile digest interval (default 900)'}}

CAMERA_ZONES = {'space_zone': 'space_utilization'}

from marketplace.super_skills import SuperSkillFunction


class Function(SuperSkillFunction):
    name = MANIFEST["id"]
    function_id = MANIFEST["id"]
    workflow = 'space_utilization'
    profile = {'zones': {'space': 'space_utilization'}, 'sample_seconds': 5, 'digest_seconds': 900}
