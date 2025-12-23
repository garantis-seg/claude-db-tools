# claude-db-tools MCP Server
# Multi-stage build for smaller image

# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY src/ ./src/

# Environment variables (will be overridden at runtime)
ENV DB_HOST=172.17.0.5 \
    DB_PORT=5432 \
    DB_NAME=cnpj_database \
    DB_USER=postgres \
    QUERY_TIMEOUT=300 \
    MAX_ROWS=10000 \
    MCP_TRANSPORT=http \
    PORT=8080

# Expose port for Cloud Run
EXPOSE 8080

# Run the MCP server with HTTP transport
CMD ["python", "-m", "src.server"]
