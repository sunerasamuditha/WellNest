# Use official, lightweight Python base image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ENV=production

# Set the working directory inside the container
WORKDIR /app

# Install system utilities needed for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code into the container
COPY . .

# Expose default Cloud Run port (Cloud Run overrides PORT env at runtime)
EXPOSE 8080

# Command to boot the FastAPI application
CMD ["python", "main.py"]
