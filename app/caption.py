import os
import wave
import json
import logging
import subprocess
import sys
from datetime import datetime
from vosk import Model, KaldiRecognizer, SetLogLevel

# Configure logging to show more detail
logging.basicConfig(
    level=logging.DEBUG,
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

def validate_video_file(file_path: str) -> bool:
    """Validate that the file is a proper video file"""
    try:
        # Use ffprobe to check file validity
        command = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_type',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        
        result = subprocess.run(command, 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE,
                              text=True)
        
        # Check if ffprobe found a video stream
        is_valid = result.returncode == 0 and 'video' in result.stdout.lower()
        if not is_valid:
            logging.error(f"Video validation failed: {result.stderr}")
        return is_valid
    except Exception as e:
        logging.error(f"Video validation failed: {str(e)}")
        return False

def create_drawtext_filter(word_timings: list, font_path: str, font_size: int = 200, y_offset: int = 700) -> str:
    """Create FFmpeg drawtext filter commands for each word with zoom and ease effects"""
    filters = []
    
    for word in word_timings:
        start_time = word['start']
        end_time = word['end']
        text = word['word'].replace("'", "'\\\\\\''")  # Escape single quotes
        
        filter_text = f"drawtext=fontfile={font_path}:text='{text}':fontsize={font_size}:"
        # Enhanced text styling
        filter_text += f"fontcolor=white@0.95:"
        filter_text += f"bordercolor=black@0.8:"
        filter_text += f"borderw=5:"
        filter_text += f"shadowcolor=black@0.6:"
        filter_text += f"shadowx=3:shadowy=3:"
        
        # Calculate center position for scaling effect
        filter_text += f"x='(w-text_w)/2':"
        filter_text += f"y='h-{y_offset}':"
        
        # Add zoom/ease effect
        ease_time = 0.15  # Duration of ease effect in seconds
        scale_start = 0.95  # Start at 95% size
        filter_text += f"scale='if(lt(t-{start_time},{ease_time}),{scale_start}+(1-{scale_start})*((t-{start_time})/{ease_time}),1)':"
        
        # Fade and timing
        fade_time = 0.2
        filter_text += f"alpha='if(lt(t,{start_time + fade_time}),((t-{start_time})/{fade_time}),if(lt({end_time}-t,{fade_time}),(({end_time}-t)/{fade_time}),1))':"
        filter_text += f"enable='between(t,{start_time},{end_time})'"
        
        filters.append(filter_text)
    
    return ','.join(filters)

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
        
        stdout, stderr = process.communicate()
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
    """Process video with subtitles using FFmpeg drawtext"""
    try:
        # Log received parameters
        logging.info(f"Processing video with font_size={font_size}, y_offset={y_offset}")
        
        # Create debug directory
        debug_dir = "/app/debug_files"
        os.makedirs(debug_dir, exist_ok=True)
        
        # Validate video file first
        if not validate_video_file(input_path):
            raise Exception("Invalid or corrupted video file")
            
        audio_path = os.path.join(debug_dir, "debug_audio.wav")
        
        logging.info(f"Debug files will be saved to {debug_dir}")
        
        if not extract_audio(input_path, audio_path):
            raise Exception("Audio extraction failed")

        word_timings = transcribe_audio(audio_path, model_path)
        if not word_timings:
            raise Exception("No words were transcribed")

        # Create drawtext filter
        filter_complex = create_drawtext_filter(
            word_timings, 
            font_path, 
            font_size=int(font_size),
            y_offset=int(y_offset)
        )
        
        # Save filter command for debugging
        with open(os.path.join(debug_dir, "filter_command.txt"), 'w') as f:
            f.write(filter_complex)
            f.write("\n\nParameters:\n")
            f.write(f"font_size: {font_size}\n")
            f.write(f"y_offset: {y_offset}\n")

        command = [
            'ffmpeg',
            '-y',
            '-i', input_path,
            '-vf', filter_complex,
            '-c:a', 'copy',
            '-c:v', 'libx264',
            '-preset', 'medium',
            output_path
        ]
        
        # Log the full command
        logging.debug(f"FFmpeg command: {' '.join(command)}")
        
        # Run FFmpeg with output capture
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL
            )
            
            stdout, stderr = process.communicate()
            
            # Save FFmpeg output
            with open(os.path.join(debug_dir, "ffmpeg_stdout.log"), "wb") as f:
                f.write(stdout)
            with open(os.path.join(debug_dir, "ffmpeg_stderr.log"), "wb") as f:
                f.write(stderr)
                
            if process.returncode != 0:
                stderr_str = stderr.decode('utf-8', errors='ignore')
                logging.error(f"FFmpeg error: {stderr_str}")
                return False

            if not os.path.exists(output_path):
                logging.error("Output file was not created")
                return False

            logging.info("Video processing completed successfully")
            return True

        except Exception as e:
            logging.error(f"FFmpeg execution failed: {str(e)}")
            return False

    except Exception as e:
        logging.error(f"Error processing video: {str(e)}")
        return False

def escape_path(path):
    """Escape path for FFmpeg"""
    return path.replace(":", "\\:").replace("'", "'\\''")

def format_time(seconds: float) -> str:
    """Convert seconds to timestamp format"""
    time = datetime.utcfromtimestamp(seconds)
    return time.strftime('%H\\:%M\\:%S.%f')[:-3]