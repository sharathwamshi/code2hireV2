FROM python:3.12-slim
# ffmpeg finishes interview videos so they can be scrubbed (V02.00.04)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5050
CMD ["sh", "-c", "python wait_db.py && python seed.py && gunicorn -w 3 -k gthread --threads 16 -b 0.0.0.0:5050 app:app"]
