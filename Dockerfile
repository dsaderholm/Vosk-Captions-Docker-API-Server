FROM python:3.10.11

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Vosk model
RUN wget https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip \
    && unzip vosk-model-en-us-0.22.zip \
    && rm vosk-model-en-us-0.22.zip

# Copy application code and font
COPY app/ ./app/
COPY fonts/ ./fonts/
COPY main.py .

EXPOSE 8080

CMD ["python", "main.py"]