#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${VISION_CONFIG:=/config/sites.yaml}"
: "${VISION_RUNTIME_SETTINGS:=/config/runtime-settings.json}"
: "${VISION_DATA:=/data}"
: "${VISION_MODELS:=/models}"
: "${VISION_EVIDENCE:=/evidence}"
: "${VISION_LICENSE_DIR:=/config/licensing}"
: "${VISION_ENTITLEMENT_TRUST_STORE:=/config/trusted-entitlement-keys.json}"
: "${PUID:=99}"
: "${PGID:=100}"

case "$PUID:$PGID" in
  *[!0-9:]*|:*|*:) printf 'PUID and PGID must be numeric\n' >&2; exit 64 ;;
esac

mkdir -p "$(dirname "$VISION_CONFIG")" "$(dirname "$VISION_RUNTIME_SETTINGS")" \
  "$VISION_DATA" "$VISION_MODELS" "$VISION_EVIDENCE" "$VISION_LICENSE_DIR" \
  "$(dirname "$VISION_ENTITLEMENT_TRUST_STORE")" /config/home

if [[ ! -e "$VISION_CONFIG" ]]; then
  install -m 0600 /app/config/sites.unraid.yaml "$VISION_CONFIG"
fi
if [[ ! -e "$VISION_ENTITLEMENT_TRUST_STORE" ]]; then
  # The image template is intentionally public-only and deny-all until Nexus
  # provisions an Ed25519 verification key. Private signing keys never belong here.
  install -m 0600 /app/config/trusted-entitlement-keys.json "$VISION_ENTITLEMENT_TRUST_STORE"
fi

# Own only the mount roots; recursive ownership changes can stall large evidence stores.
if [[ "$(id -u)" == "0" ]]; then
  chown "$PUID:$PGID" "$(dirname "$VISION_CONFIG")" "$VISION_CONFIG" \
    "$VISION_DATA" "$VISION_MODELS" "$VISION_EVIDENCE" "$VISION_LICENSE_DIR" \
    "$(dirname "$VISION_ENTITLEMENT_TRUST_STORE")" "$VISION_ENTITLEMENT_TRUST_STORE" /config/home
fi

export VISION_CONFIG VISION_RUNTIME_SETTINGS VISION_DATA VISION_MODELS VISION_EVIDENCE
export VISION_LICENSE_DIR VISION_ENTITLEMENT_TRUST_STORE
export HOME=/config/home
export TORCH_HOME="${TORCH_HOME:-$VISION_MODELS/torch}"
export HF_HOME="${HF_HOME:-$VISION_MODELS/huggingface}"
export YOLO_CONFIG_DIR="${YOLO_CONFIG_DIR:-$VISION_MODELS/ultralytics}"
export EASYOCR_MODULE_PATH="${EASYOCR_MODULE_PATH:-$VISION_MODELS/easyocr}"
mkdir -p "$TORCH_HOME" "$HF_HOME" "$YOLO_CONFIG_DIR" "$EASYOCR_MODULE_PATH"
if [[ "$(id -u)" == "0" ]]; then
  chown "$PUID:$PGID" "$TORCH_HOME" "$HF_HOME" "$YOLO_CONFIG_DIR" "$EASYOCR_MODULE_PATH"
  exec gosu "$PUID:$PGID" /opt/nvidia/nvidia_entrypoint.sh "$@"
fi
exec /opt/nvidia/nvidia_entrypoint.sh "$@"
