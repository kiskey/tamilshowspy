# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables to prevent interactive prompts
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Create a non-root user
RUN addgroup --system app && adduser --system --group app

# Set the working directory in the container
WORKDIR /home/app

# Install system dependencies
# gcc and libpq-dev are often needed for psycopg2, which is a common dependency of other libraries
# We install them here just in case, can be removed if not needed.
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY ./src ./src
COPY main.py .

# Change the owner of the application files to the non-root user
RUN chown -R app:app .

# Switch to the non-root user
USER app

# Expose the port the app runs on
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
