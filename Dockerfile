# syntax=docker/dockerfile:1

# Use official Python image (slim for smaller size)
FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies (for pip requirements and wheels build)
RUN apt-get update \
    && apt-get install --no-install-recommends -y gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements to leverage Docker cache
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Copy application code
COPY . .

# Create and use a non-root user (security best practice)
RUN useradd -m appuser
USER appuser

# Expose the port used by Uvicorn
EXPOSE 8000

# Start FastAPI app with Uvicorn
CMD ["python", "-m", "uvicorn", "main:app", "--host=0.0.0.0", "--port=8000"]
