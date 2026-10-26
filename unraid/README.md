# Nexus Vision AI on Unraid

Use the CPU template for onboarding, image-health/event analytics, and evaluation. Use the GPU template for continuous video inference.

## Install

1. Confirm the Unraid host is x86-64/AMD64 and Docker is enabled.
2. GPU installs: install the Unraid **NVIDIA Driver** plugin, reboot if requested, and confirm the GPU is listed by the plugin.
3. In **Docker → Add Container**, switch to Advanced View and load one of the XML templates in this directory. Community Applications can use the raw `TemplateURL` after the image is published.
4. Set a long random **Administrator token**. Keep the optional door-control token different.
5. Keep bridge networking and port `8090` unless another local service already uses it. Do not port-forward this service to the Internet.
6. Start the container and open `http://UNRAID-IP:8090/setup/`.
7. Complete Protect connection, camera discovery, mapping, save, restart, and readiness checks in the local wizard.

## Persistent layout

All mutable state is under `/mnt/user/appdata/nexus-vision-ai/`:

- `config/`: site YAML, owner-only runtime credentials, trusted certificates
- `data/`: SQLite state, alert outbox, indexes
- `models/`: model downloads and caches; retained across upgrades
- `evidence/`: permitted snapshots, clips, and exports

Back up `config/` and `data/`. Apply retention appropriate to the site before enabling evidence capture.

## Network access

The container needs outbound LAN access to the UniFi console/NVR over HTTPS (`443`) and to enabled Protect RTSP/S feeds (`7441`). Initial model acquisition may require outbound HTTPS unless every selected weight is preloaded in `models/`.

The image health endpoint is `/health`. Analytics readiness is `/ready`; it remains unavailable until every configured camera has a fresh frame and no unresolved detector or alert-delivery failure exists.
