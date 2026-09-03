FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

ENV HOST=0.0.0.0
EXPOSE 3000

CMD ["python", "-m", "app"]
