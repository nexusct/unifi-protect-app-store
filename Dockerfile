# Nexus Vision AI runtime image.
# CUDA base for GPU inference; CPU profile uses the same image (torch picks device).
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# CUDA-enabled torch wheels (cu121 matches the base image)
RUN pip install --extra-index-url https://download.pytorch.org/whl/cu121 -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/
COPY landing/ ./landing/
COPY storefront/ ./storefront/
COPY guide/ ./guide/

ENV PYTHONPATH=/app/src \
    VISION_CONFIG=/app/config/sites.yaml \
    VISION_DATA=/app/data

RUN mkdir -p /app/data
EXPOSE 8090

CMD ["python", "src/main.py"]
