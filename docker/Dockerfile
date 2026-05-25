# voice-forge container image.
# Single-stage build for the NeuTTS-only deploy. Multi-stage + Kokoro
# variants land when those backends ship to the image.

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
