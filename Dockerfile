FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files
COPY pyproject.toml .
COPY src/ src/
COPY main.py .

# Install dependencies using uv
RUN uv sync --no-dev

# Expose port
EXPOSE 8000

# Run the server
CMD ["uv", "run", "python", "main.py"]
