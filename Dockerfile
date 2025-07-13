# Use Python base image
FROM python:3.10-slim

# Install system dependencies: tesseract, zbar, and build tools
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libzbar0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your app code
COPY . .

# Expose port (FastAPI default port)
EXPOSE 8000

# Start the server
CMD ["uvicorn", "final:app", "--host", "0.0.0.0", "--port", "8000"]
