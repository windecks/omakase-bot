FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create non-root user for Chromium sandbox security
RUN useradd -m -s /bin/bash botuser \
    && chown -R botuser:botuser /app
USER botuser

# Volumes for persistent sessions and configuration
VOLUME ["/app/sessions", "/app/config"]

# Run the fleet manager
ENTRYPOINT ["python3", "fleet.py"]
CMD ["tasks.yaml"]
