# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install build dependencies and tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Remove TA-Lib from requirements since it's problematic on ARM64
RUN grep -v "TA-Lib" requirements.txt > requirements_no_talib.txt

# Install any needed packages specified in requirements.txt
# We use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements_no_talib.txt

# Copy the rest of the application code into the container at /app
COPY . .

# Make port 8001 available to the world outside this container
# Note: Cloud Run will automatically use the port your application listens on.
# This EXPOSE is more for documentation and local Docker runs.
EXPOSE 8001

# Define environment variable for the port (Cloud Run injects this)
ENV PORT=8001

# Run uvicorn when the container launches
# We use 0.0.0.0 to bind to all network interfaces
# The port is taken from the PORT environment variable
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"] 