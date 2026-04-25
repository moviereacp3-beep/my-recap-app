# Use Python 3.11 Slim (Latest Stable for Google AI)
FROM python:3.11-slim

# Install System Dependencies
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# Set Working Directory
WORKDIR /app

# Create a non-root user
RUN useradd -m -u 1000 user

# Copy Requirements first
COPY requirements.txt .

# Install Python Libraries
RUN pip install --no-cache-dir -r requirements.txt

# Copy all app files
COPY . .

# Permissions
RUN mkdir -p static/uploads static/processed && \
    chown -R user:user /app && \
    chmod -R 777 static/uploads static/processed

# Switch User
USER user

# Expose Port
EXPOSE 7860

# Command
CMD ["python", "app.py"]
