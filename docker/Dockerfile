FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY simulator/ simulator/
COPY config.yaml .

EXPOSE 20000 8090

ENTRYPOINT ["python", "-m", "simulator.plc"]
