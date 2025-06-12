# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables to prevent interactive prompts
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create a non-root user
RUN addgroup --system app && adduser --system --group app

# Set the working directory in the container
WORKDIR /home/app

# Install system dependencies
# gcc is needed by some python packages for C extensions.
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements file first to leverage Docker layer caching
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# --- CORRECTED BLOCK: PRE-DOWNLOAD NLTK DATA ---
# This command runs a non-interactive python scriptlet to download the data.
# It is more robust for Docker builds than using the downloader module directly.
RUN python -c "import nltk; nltk.download('porter_stemmer')"
# --- END CORRECTED BLOCK ---

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
