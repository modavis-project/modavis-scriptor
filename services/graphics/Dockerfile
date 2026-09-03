FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
LABEL org.opencontainers.image.title="MODAVIS Scriptor processing service" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.source="https://github.com/modavis-project/modavis-scriptor"
ENV PYTHONUNBUFFERED=1 OMP_THREAD_LIMIT=1 GRAPHICS_DATA=/data
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY models/ ./models/
COPY *.py ./
COPY LICENSE THIRD_PARTY_NOTICES.md ./
COPY corpus/catalogue.sqlite corpus/import-report.json corpus/zenodo-record.json ./corpus/
COPY example/ ./example/
RUN useradd --create-home --uid 10001 graphics && mkdir /data && chown graphics:graphics /data
USER graphics
EXPOSE 8010
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8010"]
