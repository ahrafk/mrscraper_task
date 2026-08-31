FROM python:3.12-slim

WORKDIR /app

ENV TZ=America/New_York

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgtk-3-0 \
    libasound2 \
    libx11-xcb1 \
    libdbus-glib-1-2 \
    libxt6 \
    libxrandr2 \
    fonts-liberation \
    ca-certificates \
    tzdata \
    xvfb \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN camoufox fetch

COPY app ./app
COPY scripts ./scripts

ENV HOST=0.0.0.0
EXPOSE 3000

CMD ["python", "-m", "app"]
