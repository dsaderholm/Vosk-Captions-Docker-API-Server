FROM python:3.9

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1-mesa-glx \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install moviepy directly from git
RUN pip install git+https://github.com/Zulko/moviepy.git

# Copy and install other requirements
COPY requirements.txt .
RUN grep -v "moviepy" requirements.txt > temp_requirements.txt && \
    pip install --no-cache-dir -r temp_requirements.txt

# Download Vosk model
RUN mkdir -p /app/vosk-model-en-us-0.22 && \
    wget https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip && \
    unzip vosk-model-en-us-0.22.zip -d /app && \
    rm vosk-model-en-us-0.22.zip

# Create fonts directory and copy font
COPY fonts/ /app/fonts/

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "app.py"]
