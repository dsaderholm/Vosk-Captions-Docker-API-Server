import os
import wave
import json
import logging
import subprocess
from vosk import Model, KaldiRecognizer, SetLogLevel
import tempfile
import sys

# Configure logging to show more detail
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG level
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('caption_service.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

def verify_file_exists(path: str, description: str) -> bool:
    """Verify file exists and has content"""
    if not os.path.exists(path):
        logging.error(f"{description} file not found at {path}")
        return False
    if os.path.getsize(path) == 0:
        logging.error(f"{description} file is empty at {path}")
        return False
    logging.debug(f"{description} file verified at {path} with size {os.path.getsize(path)}")
    return True

def run_ffmpeg_command(command, input_file=None, output_file=None, description="FFmpeg operation"):
    """Run FFmpeg command with detailed logging"""
    try:
        cmd_list = ['ffmpeg', '-hide_banner', '-y']
        if input_file:
            cmd_list.extend(['-i', input_file])
        cmd_list.extend(command)

        logging.debug(f"Running FFmpeg command: {' '.join(cmd_list)}")
        
        process = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL
        )
        
        _, stderr = process.communicate()
        stderr_str = stderr.decode('utf-8', errors='ignore')
        
        if process.returncode != 0:
            logging.error(f"FFmpeg {description} failed with error: {stderr_str}")
            return False
            
        if output_file and not verify_file_exists(output_file, f"FFmpeg {description} output"):
            return False
            
        logging.debug(f"FFmpeg {description} completed successfully")
        return True
        
    except Exception as e:
        logging.error(f"FFmpeg {description} failed with exception: {str(e)}")
        return False

def extract_audio(video_path: str, audio_path: str) -> bool:
    """Extract audio from video file"""
    try:
        if not verify_file_exists(video_path, "Input video"):
            return False
            
        command = [
            '-vn',
            '-acodec', 'pcm_s16le',
            '-ac', '1',
            '-ar', '16000',
            audio_path
        ]
        
        success = run_ffmpeg_command(command, video_path, audio_path, "audio extraction")
        if success:
            logging.debug(f"Audio extracted to {audio_path}")
        return success
    except Exception as e:
        logging.error(f"Audio extraction failed: {str(e)}")
        return False

def transcribe_audio(audio_path: str, model_path: str) -> list:
    """Transcribe audio file to get word timings"""
    if not verify_file_exists(audio_path, "Audio"):
        return []
        
    if not os.path.exists(model_path):
        logging.error(f"Vosk model not found at {model_path}")
        return []
        
    try:
        wf = wave.open(audio_path, "rb")
        model = Model(model_path)
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)

        words = []
        total_audio_processed = 0
        
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            total_audio_processed += len(data)
            if rec.AcceptWaveform(data):
                part_result = json.loads(rec.Result())
                if 'result' in part_result:
                    words.extend(part_result['result'])
        
        final_result = json.loads(rec.FinalResult())
        if 'result' in final_result:
            words.extend(final_result['result'])
            
        logging.debug(f"Transcription complete. Found {len(words)} words in {total_audio_processed} bytes of audio")
        
        # Log some example words if any were found
        if words:
            example_words = words[:3]
            logging.debug(f"First few words with timings: {json.dumps(example_words, indent=2)}")
        else:
            logging.warning("No words were transcribed from the audio")
            
        return words
        
    except Exception as e:
        logging.error(f"Transcription failed: {str(e)}")
        return []

def create_subtitle_file(word_timings: list, output_path: str) -> bool:
    """Create an SRT subtitle file from word timings"""
    try:
        if not word_timings:
            logging.error("No word timings provided for subtitle creation")
            return False
            
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, word in enumerate(word_timings, 1):
                start_time = format_time(word['start'])
                end_time = format_time(word['end'])
                f.write(f"{i}\n{start_time} --> {end_time}\n{word['word']}\n\n")
                
        if not verify_file_exists(output_path, "Subtitle"):
            return False
            
        # Log some statistics about the subtitle file
        subtitle_size = os.path.getsize(output_path)
        logging.debug(f"Created subtitle file with {len(word_timings)} entries, size: {subtitle_size} bytes")
        return True
    except Exception as e:
        logging.error(f"Failed to create subtitle file: {str(e)}")
        return False

def process_video(input_path: str, output_path: str, model_path: str, font_path: str, 
                 font_size: int = 200, y_offset: int = 700) -> bool:
    """Process video with subtitles using FFmpeg"""
    try:
        # Create debug directory
        debug_dir = "/app/debug_files"
        os.makedirs(debug_dir, exist_ok=True)
        
        audio_path = os.path.join(debug_dir, "debug_audio.wav")
        srt_path = os.path.join(debug_dir, "debug_subtitles.srt")

        logging.info(f"Debug files will be saved to {debug_dir}")
        
        if not extract_audio(input_path, audio_path):
            raise Exception("Audio extraction failed")

        word_timings = transcribe_audio(audio_path, model_path)
        if not word_timings:
            raise Exception("No words were transcribed")

        if not create_subtitle_file(word_timings, srt_path):
            raise Exception("Failed to create subtitle file")

        # More aggressive subtitle styling
        subtitle_filter = (
            f"subtitles={srt_path}:force_style='"
            f"FontSize={font_size},"
            f"MarginV={y_offset},"
            "PrimaryColour=&Hffffff,"  # White text
            "OutlineColour=&H000000,"  # Black outline
            "BorderStyle=3,"           # Opaque box
            "Outline=3,"               # Thicker outline
            "Shadow=0,"                # No shadow
            "Bold=1"                   # Bold text
            "'"
        )

        # Add -v debug to see detailed FFmpeg output
        command = [
            'ffmpeg',
            '-hide_banner',
            '-v', 'debug',  # Detailed logging
            '-y',
            '-i', input_path,
            '-vf', subtitle_filter,
            '-c:a', 'copy',
            output_path
        ]
        
        # Run FFmpeg with full output capture
        try:
            logging.debug(f"Running FFmpeg command: {' '.join(command)}")
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL
            )
            
            stdout, stderr = process.communicate()
            
            # Save FFmpeg output to debug files
            with open(os.path.join(debug_dir, "ffmpeg_stdout.log"), "wb") as f:
                f.write(stdout)
            with open(os.path.join(debug_dir, "ffmpeg_stderr.log"), "wb") as f:
                f.write(stderr)
                
            if process.returncode != 0:
                logging.error("FFmpeg failed")
                stderr_str = stderr.decode('utf-8', errors='ignore')
                logging.error(f"FFmpeg error: {stderr_str}")
                return False

            if not os.path.exists(output_path):
                logging.error("Output file was not created")
                return False

            # Verify SRT file content
            with open(srt_path, 'r', encoding='utf-8') as f:
                srt_content = f.read()
                logging.debug(f"SRT file content preview:\n{srt_content[:500]}")

            logging.info("Video processing completed successfully")
            return True

        except Exception as e:
            logging.error(f"FFmpeg execution failed: {str(e)}")
            return False

    except Exception as e:
        logging.error(f"Error processing video: {str(e)}")
        return False

# Helper function to escape paths for FFmpeg
def escape_path(path):
    """Escape path for FFmpeg"""
    return path.replace(":", "\\:").replace("'", "'\\''")

def format_time(seconds: float) -> str:
    """Convert seconds to SRT time format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
