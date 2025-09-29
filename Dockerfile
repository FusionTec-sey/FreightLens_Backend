# Use official Python image
FROM python:3.11-slim   
# match your local version

# Install system dependencies inside the container
# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
        libgobject-2.0-0 \
        libglib2.0-0 \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libffi-dev \
        build-essential \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*
# Set working directory
WORKDIR /app

# Install dependencies first (better caching)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the app
COPY . .

# Expose FastAPI port
EXPOSE 8001

# Run the FastAPI server
# CMD ["uvicorn", "containerMgmt:app", "--host", "0.0.0.0", "--port", "9000"]
CMD ["python", "containerMgmt.py"]