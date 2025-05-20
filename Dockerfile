FROM python:3.10.11

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gnupg \
    wget \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Install Intel GPU drivers and runtime requirements
RUN wget -qO - https://repositories.intel.com/graphics/intel-graphics.key | gpg --dearmor --output /usr/share/keyrings/intel-graphics.gpg
RUN echo "deb [arch=amd64,i386 signed-by=/usr/share/keyrings/intel-graphics.gpg] https://repositories.intel.com/graphics/ubuntu jammy arc" | tee /etc/apt/sources.list.d/intel-gpu-jammy.list
RUN apt-get update && apt-get install -y \
    intel-media-va-driver-non-free \
    intel-opencl-icd \
    intel-level-zero-gpu \
    level-zero \
    level-zero-dev \
    ocl-icd-opencl-dev \
    vainfo \
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