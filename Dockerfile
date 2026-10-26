# Nexus Vision AI runtime image.
# CUDA base for GPU inference; CPU profile uses the same image (torch picks device).
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04@sha256:f4d8e1264366940438f0353da6f289c7bef069d993d111f8106086ccd18c4a30

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    ca-certificates ffmpeg gosu libgl1 libglib2.0-0 libsm6 libxext6 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements.lock ./
# Ubuntu 22.04 ships a packaging toolchain with known pip/wheel advisories.
RUN python -m pip install --upgrade "pip==26.2.1" "wheel==0.48.0" "setuptools==84.0.0"
# Install the CUDA 12.1 PyTorch pair only from the matching official index,
# then resolve all remaining application packages from normal PyPI.
RUN python -m pip install --index-url https://download.pytorch.org/whl/cu121 \
    "torch==2.5.1" "torchvision==0.20.1"
RUN python -m pip install -r requirements.lock

COPY src/ ./src/
COPY config/ ./config/
COPY assets/ ./assets/
COPY scripts/ ./scripts/
COPY landing/ ./landing/
COPY storefront/ ./storefront/
COPY guide/ ./guide/
COPY setup/ ./setup/
COPY docker/entrypoint.sh /app/docker/entrypoint.sh

# Keep manifests, public catalog data, and module artwork synchronized.
RUN python scripts/build_marketplace_catalog.py \
    && python scripts/generate_marketplace_icons.py

ENV PYTHONPATH=/app/src \
    VISION_CONFIG=/config/sites.yaml \
    VISION_RUNTIME_SETTINGS=/config/runtime-settings.json \
    VISION_DATA=/data \
    VISION_MODELS=/models \
    VISION_EVIDENCE=/evidence

RUN chmod 0755 /app/docker/entrypoint.sh \
    && chmod -R a+rX /app/assets /app/landing /app/storefront /app/guide /app/setup \
    && mkdir -p /config /data /models /evidence
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3).read()" || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "src/main.py"]
