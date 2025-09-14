# Use official Python image
FROM python:3.11-slim   
# match your local version


RUN apt-get update && apt-get install -y libgobject-2.0-0 && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install dependencies first (better caching)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the app
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Run the FastAPI server
CMD ["uvicorn", "containerMgmt:app", "--host", "0.0.0.0", "--port", "8000"]
