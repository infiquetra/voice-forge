# voice-forge container image.
# Phase D will flesh this out with multi-stage build + NeuTTS install + entrypoint.
# For now, a placeholder.

FROM python:3.11-slim

WORKDIR /app

# System deps for audio + GGUF model loading
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install voice-forge with NeuTTS backend
COPY . /app/voice-forge
RUN pip install --no-cache-dir -e "/app/voice-forge[neutts,voice-lab]"

EXPOSE 9876

CMD ["voice-forge", "serve", "--host", "0.0.0.0", "--port", "9876"]
