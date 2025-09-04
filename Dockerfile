# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy app code and requirements
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the FastAPI server
CMD ["uvicorn", "containerMgmt:app", "--host", "0.0.0.0", "--port", "8000"]
