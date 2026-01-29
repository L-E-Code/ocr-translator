FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Minimal runtime deps for EasyOCR/OpenCV; keep image small
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

CMD ["python", "app/main.py"]
