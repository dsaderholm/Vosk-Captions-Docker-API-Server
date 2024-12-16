import os
import wave
import json
import logging
import subprocess
from vosk import Model, KaldiRecognizer, SetLogLevel
from PIL import Image, ImageDraw, ImageFont
import tempfile

def extract_audio(video_path: str, audio_path: str) -> bool:
    """Extract audio from video file"""
    try:
        command = f'ffmpeg -hide_banner -y -i "{video_path}" -vn -acodec pcm_s16le -ac 1 -ar 16000 "{audio_path}"'
        subprocess.run(command, shell=True, check=True, capture_output=True)
        return os.path.exists(audio_path)
    except subprocess.CalledProcessError as e:
        logging.error(f"Audio extraction failed: {e.stderr.decode() if e.stderr else str(e)}")
        return False

def transcribe_audio(audio_path: str, model_path: str) -> list:
    """Transcribe audio file to get word timings"""
    SetLogLevel(0)
    
    if not os.path.exists(audio_path):
        logging.error("Audio file not found")
        return []
        
    try:
        wf = wave.open(audio_path, "rb")
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
            logging.error("Audio file must be WAV format mono PCM.")
            return []

        model = Model(model_path)
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)

        results = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                part_result = json.loads(rec.Result())
                results.append(part_result)
        
        part_result = json.loads(rec.FinalResult())
        results.append(part_result)

        words = []
        for r in results:
            if 'result' in r:
                words.extend(r['result'])
        return words
        
    except Exception as e:
        logging.error(f"Transcription failed: {str(e)}")
        return []

def create_subtitle_file(word_timings: list, output_path: str) -> bool:
    """Create an SRT subtitle file from word timings"""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, word in enumerate(word_timings, 1):
                start_time = format_time(word['start'])
                end_time = format_time(word['end'])
                f.write(f"{i}\n{start_time} --> {end_time}\n{word['word']}\n\n")
        return True
    except Exception as e:
        logging.error(f"Failed to create subtitle file: {str(e)}")
        return False

def format_time(seconds: float) -> str:
    """Convert seconds to SRT time format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def process_video(input_path: str, output_path: str, model_path: str, font_path: str, 
                 font_size: int = 200, y_offset: int = 700) -> bool:
    """Process video with subtitles using FFmpeg"""
    try:
        # Create temporary files
        temp_dir = tempfile.mkdtemp()
        audio_path = os.path.join(temp_dir, "temp_audio.wav")
        srt_path = os.path.join(temp_dir, "subtitles.srt")

        # Step 1: Extract audio
        logging.info("Extracting audio...")
        if not extract_audio(input_path, audio_path):
            raise Exception("Failed to extract audio")

        # Step 2: Transcribe audio
        logging.info("Transcribing audio...")
        word_timings = transcribe_audio(audio_path, model_path)
        if not word_timings:
            raise Exception("No words were transcribed")

        # Step 3: Create subtitle file
        logging.info("Creating subtitle file...")
        if not create_subtitle_file(word_timings, srt_path):
            raise Exception("Failed to create subtitle file")

        # Step 4: Add subtitles to video
        logging.info("Adding subtitles to video...")
        
        # Escape paths for ffmpeg
        input_path_esc = input_path.replace('"', '\\"')
        output_path_esc = output_path.replace('"', '\\"')
        srt_path_esc = srt_path.replace('"', '\\"')
        font_path_esc = font_path.replace('"', '\\"')

        # Construct subtitle filter with proper escaping
        subtitle_filter = f"subtitles={srt_path_esc}:force_style='Fontname={font_path_esc},FontSize={font_size},MarginV={y_offset}'"
        
        ffmpeg_command = [
            'ffmpeg',
            '-hide_banner',
            '-y',
            '-i', input_path,
            '-vf', subtitle_filter,
            '-c:a', 'copy',
            output_path
        ]
        
        # Run ffmpeg with subprocess list instead of shell=True
        result = subprocess.run(
            ffmpeg_command,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logging.error(f"FFmpeg error: {result.stderr}")
            raise Exception(f"FFmpeg error: {result.stderr}")

        # Verify output file exists and has size > 0
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Output file was not created successfully")

        logging.info("Video processing completed successfully")
        return True

    except Exception as e:
        logging.error(f"Error processing video: {str(e)}")
        return False
        
    finally:
        # Cleanup temporary files
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
            if os.path.exists(srt_path):
                os.remove(srt_path)
            os.rmdir(temp_dir)
        except Exception as e:
            logging.error(f"Cleanup error: {str(e)}")
            os.rmdir(temp_dir)
        except Exception as e:
            logging.error(f"Cleanup error: {str(e)}")
