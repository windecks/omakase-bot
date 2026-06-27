FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Volumes for persistent sessions and configuration
VOLUME ["/app/sessions", "/app/config"]

# Run the fleet manager
ENTRYPOINT ["python3", "fleet.py"]
CMD ["tasks.yaml"]
