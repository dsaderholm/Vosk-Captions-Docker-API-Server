FROM python:3.9

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Vosk model
RUN mkdir /app
WORKDIR /app
RUN wget https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip && \
    unzip vosk-model-en-us-0.22.zip && \
    rm vosk-model-en-us-0.22.zip

# Copy application
COPY ./app /app/app
COPY ./fonts /app/fonts
COPY main.py /app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]