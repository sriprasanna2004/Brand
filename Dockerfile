FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including ffmpeg for video processing
RUN apt-get update && apt-get install -y \
    supervisor \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-railway.txt .
RUN pip install --use-deprecated=legacy-resolver --no-cache-dir -r requirements-railway.txt

COPY . .

EXPOSE 8000

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]