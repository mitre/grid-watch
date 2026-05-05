FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY dnp3-sim/ dnp3-sim/
COPY config.yaml .

EXPOSE 20000

ENTRYPOINT ["python", "dnp3-sim/server.py"]
