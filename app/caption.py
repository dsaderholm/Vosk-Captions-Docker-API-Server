import os
import wave
import json
import logging
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from vosk import Model, KaldiRecognizer, SetLogLevel

# Import Intel Arc GPU initialization
try:
    from intel_gpu_init import initialize_intel_arc_gpu
except ImportError:
    def initialize_intel_arc_gpu():
        pass

# Configure logging to show more detail
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('caption_service.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Initialize Intel Arc GPU on module load
initialize_intel_arc_gpu()

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
    """Create FFmpeg drawtext filter commands for each word with enhanced styling"""
    filters = []
    
    for word in word_timings:
        start_time = word['start']
        end_time = word['end']
        text = word['word'].upper().replace("'", "'\\\\\\''")
        
        filter_text = (
            f"drawtext=fontfile={font_path}"
            f":text='{text}'"
            f":fontsize={font_size}"
            # Bright white text with full opacity
            f":fontcolor=white@1"
            # Thicker black border
            f":bordercolor=black@1"
            f":borderw=8"
            # Deeper shadow
            f":shadowcolor=black@0.8"
            f":shadowx=5"
            f":shadowy=5"
            f":x=(w-text_w)/2"
            f":y=h-{y_offset}"
            # Quick fade in/out
            f":alpha='if(lt(t,{start_time + 0.05}),((t-{start_time})/0.05),if(lt({end_time}-t,0.05),(({end_time}-t)/0.05),1))'"
            f":enable='between(t,{start_time},{end_time})'"
        )
        
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

def try_intel_arc_encoding(input_path: str, output_path: str, filter_complex: str, max_retries: int = 3) -> bool:
    """Intel Arc hardware encoding - skip for subtitle overlays due to fundamental limitations."""
    
    # Based on research: Intel Arc QSV/VA-API cannot handle drawtext filters reliably
    # Multiple sources confirm this is a known limitation
    logging.info("🚀 Intel Arc GPU detected")
    logging.warning("⚠️ Intel Arc has fundamental limitations with subtitle overlays (drawtext filters)")
    logging.info("💡 Intel Arc works best for simple re-encoding without complex filters")
    logging.info("💡 For subtitle overlays, optimized software encoding is recommended")
    
    # Return False immediately to use optimized software encoding
    # This is the most reliable approach for subtitle generation
    return False

def test_qsv_support() -> bool:
    """Test QSV hardware encoding support."""
    try:
        # Test basic QSV encoding without complex filters
        test_cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc=duration=0.1:size=320x240:rate=30',
            '-c:v', 'h264_qsv',
            '-preset', 'medium',
            '-global_quality', '23',
            '-frames:v', '1',
            '-f', 'null', '-'
        ]
        
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            logging.info("✅ QSV H264 encoding works")
            return True
        else:
            logging.warning(f"⚠️ QSV encoding failed: {result.stderr[-200:] if result.stderr else 'Unknown error'}")
            return False
            
    except Exception as e:
        logging.warning(f"⚠️ Could not test QSV support: {str(e)}")
        return False


def test_vaapi_drawtext_support() -> bool:
    """Test if VA-API supports drawtext filters."""
    try:
        test_cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc=duration=0.1:size=320x240:rate=30',
            '-vf', 'format=nv12,hwupload,drawtext=text=TEST:fontcolor=white:fontsize=24,hwdownload',
            '-c:v', 'h264_vaapi',
            '-vaapi_device', '/dev/dri/renderD128',
            '-frames:v', '1',
            '-f', 'null', '-'
        ]
        
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            logging.info("✅ VA-API supports drawtext filters")
            return True
        else:
            logging.info("⚠️ VA-API does not support drawtext filters")
            return False
            
    except Exception as e:
        logging.warning(f"⚠️ Could not test VA-API drawtext support: {str(e)}")
        return False


def debug_gpu_status():
    """Debug GPU status and save detailed information"""
    debug_dir = "/app/debug_files"
    debug_file = os.path.join(debug_dir, "gpu_debug.log")
    
    try:
        with open(debug_file, 'w') as f:
            f.write("=== GPU Debug Information ===\n\n")
            
            # Check if GPU device exists
            try:
                result = subprocess.run(['ls', '-la', '/dev/dri/'], capture_output=True, text=True)
                f.write("GPU Devices:\n")
                f.write(result.stdout)
                f.write("\n")
            except Exception as e:
                f.write(f"Failed to list GPU devices: {str(e)}\n")
            
            # Check VA-API status
            try:
                result = subprocess.run(['vainfo', '--display', 'drm', '--device', '/dev/dri/renderD128'], 
                                      capture_output=True, text=True, timeout=10)
                f.write("VA-API Information:\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write("STDOUT:\n")
                f.write(result.stdout)
                f.write("\nSTDERR:\n")
                f.write(result.stderr)
                f.write("\n")
            except Exception as e:
                f.write(f"Failed to get VA-API info: {str(e)}\n")
            
            # Check FFmpeg encoders
            try:
                result = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True, timeout=10)
                f.write("FFmpeg Hardware Encoders:\n")
                for line in result.stdout.split('\n'):
                    if any(codec in line.lower() for codec in ['vaapi', 'qsv', 'intel']):
                        f.write(f"  {line}\n")
                f.write("\n")
            except Exception as e:
                f.write(f"Failed to get FFmpeg encoder info: {str(e)}\n")
                
    except Exception as e:
        logging.error(f"Failed to create GPU debug file: {str(e)}")

def check_gpu_availability():
    """Enhanced Intel Arc GPU availability check with multiple fallback methods"""
    try:
        # Run vainfo to check GPU hardware acceleration availability
        process = subprocess.run(['vainfo', '--display', 'drm', '--device', '/dev/dri/renderD128'], 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE, 
                               text=True,
                               timeout=10)
        
        if process.returncode == 0:
            gpu_info = process.stdout
            if 'Intel' in gpu_info:
                if 'H264' in gpu_info:
                    logging.info("✅ Intel Arc GPU hardware acceleration is available")
                    if 'iHD driver' in gpu_info:
                        logging.info("✅ Using Intel iHD driver for optimal Arc performance")
                    logging.debug(f"GPU capabilities: {gpu_info.strip()}")
                    return True
                else:
                    logging.warning("⚠️ Intel GPU found but H264 support limited")
                    return False
            else:
                logging.warning("⚠️ Non-Intel GPU detected")
                return False
        else:
            logging.warning("⚠️ Intel GPU hardware acceleration is not available")
            logging.debug(f"vainfo error: {process.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        logging.warning("⚠️ GPU check timed out")
        return False
    except FileNotFoundError:
        logging.warning("⚠️ vainfo not found, install intel-gpu-tools")
        return False
    except Exception as e:
        logging.error(f"❌ Error checking GPU availability: {str(e)}")
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
        
        # Debug GPU status
        debug_gpu_status()
        
        # Check GPU availability with enhanced VA-API testing
        use_gpu = check_gpu_availability()
        if use_gpu:
            logging.info("Using Intel GPU acceleration for video processing")
            # Test specific VA-API capabilities
            supports_drawtext = test_vaapi_drawtext_support()
            if supports_drawtext:
                logging.info("✅ VA-API supports drawtext - can use hardware filtering")
            else:
                logging.info("⚠️ VA-API doesn't support drawtext - will use CPU filtering")
            
            # Test QSV capabilities
            supports_qsv = test_qsv_support()
            if supports_qsv:
                logging.info("✅ QSV encoding available as backup")
            else:
                logging.info("⚠️ QSV encoding not available")
        else:
            logging.info("Using CPU for video processing")
        
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

        # This section is already handled by the software fallback above

        try:
            if use_gpu:
                # Intel Arc GPU detected - explain the situation
                logging.info("🚀 Intel Arc GPU detected and available")
                
                success = try_intel_arc_encoding(input_path, output_path, filter_complex)
                if success:
                    logging.info("✅ Intel Arc hardware encoding completed successfully")
                    return True
                # Note: Intel Arc function will always return False for subtitle overlays
            
            # Optimized software encoding: Guaranteed to work with subtitles
            logging.info("🎯 Using optimized CPU encoding with subtitle support...")
            
            # Create filter file to avoid "Argument list too long" error
            software_filter_path = os.path.join(debug_dir, "software_filter.txt")
            
            try:
                # Write filter to file to avoid command line length issues
                with open(software_filter_path, 'w') as f:
                    f.write(filter_complex)
                
                # Optimized command for subtitle rendering
                command = [
                    'ffmpeg',
                    '-y',
                    '-i', input_path,
                    # Use filter file to avoid argument length limits
                    '-filter_complex_script', software_filter_path,
                    '-c:a', 'copy',
                    '-c:v', 'libx264',
                    # Optimized for speed with good quality
                    '-preset', 'fast',  # Changed from medium to fast
                    '-crf', '23',
                    # Use multiple threads efficiently
                    '-threads', '0',  # Use all available threads
                    # Optimize for streaming/web delivery
                    '-movflags', '+faststart',
                    '-pix_fmt', 'yuv420p',
                    # Optimize encoding speed
                    '-tune', 'fastdecode',
                    output_path
                ]
                
                logging.debug(f"Software encoding command: {' '.join(command)}")
                
                # Run FFmpeg with output capture
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
                    logging.error(f"FFmpeg software encoding failed: {stderr_str}")
                    return False

                if not os.path.exists(output_path):
                    logging.error("Output file was not created")
                    return False

                logging.info("✅ Software encoding completed successfully")
                return True

            except Exception as e:
                logging.error(f"Software encoding execution failed: {str(e)}")
                return False
            finally:
                # Clean up the software filter file
                try:
                    os.unlink(software_filter_path)
                except Exception as e:
                    logging.debug(f"Failed to clean up software filter file: {str(e)}")

        except Exception as e:
            logging.error(f"Video processing execution failed: {str(e)}")
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