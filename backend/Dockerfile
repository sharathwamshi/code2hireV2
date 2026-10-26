FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5050
CMD ["sh", "-c", "python wait_db.py && python seed.py && gunicorn -w 3 -k gthread --threads 16 -b 0.0.0.0:5050 app:app"]
