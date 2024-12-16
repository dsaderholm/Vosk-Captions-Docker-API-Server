import os
import wave
import json
import logging
import subprocess
from moviepy import VideoFileClip, CompositeVideoClip, ImageClip
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from vosk import Model, KaldiRecognizer, SetLogLevel

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_audio(video_path, audio_path):
    logging.info(f"Starting audio extraction from {video_path} to {audio_path}")
    
    if os.path.exists(audio_path):
        os.remove(audio_path)
    
    command = [
        "ffmpeg",
        "-y",  # Overwrite output file if it exists
        "-i", video_path,
        "-vn",  # No video
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", "16000",
        audio_path
    ]
    
    try:
        logging.info(f"Running ffmpeg command: {' '.join(command)}")
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True
        )
        logging.info("Audio extraction completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"FFmpeg error: {e.stderr}")
        return False

def transcribe_audio(audio_path, model_path):
    SetLogLevel(0)
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

def create_text_image(text, size, font_size, color, font_path, border_size=15):
    increased_size = (size[0] + border_size * 2, size[1] + border_size * 2 + font_size // 2)
    img = Image.new('RGBA', increased_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    font = ImageFont.truetype(font_path, font_size)
    
    text_bbox = font.getbbox(text)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    position = ((increased_size[0] - text_width) // 2, (increased_size[1] - text_height) // 2)

    for x_offset in range(-border_size, border_size + 1):
        for y_offset in range(-border_size, border_size + 1):
            draw.text((position[0] + x_offset, position[1] + y_offset), text, font=font, fill=(0, 0, 0, 255))

    draw.text(position, text, font=font, fill=color)
    return np.array(img)

def create_caption_clips(word_timings, video_width, video_height, font_path, font_size, y_offset):
    caption_clips = []

    for word in word_timings:
        img_array = create_text_image(word['word'], (video_width, 120), font_size, (255, 255, 255, 255), font_path)
        # Create clip with just the duration first
        clip = ImageClip(img_array)
        # Set duration and start time separately
        clip.duration = word['end'] - word['start']
        clip.start = word['start']
        # Set position
        clip.pos = (video_width//2, video_height - y_offset)
        caption_clips.append(clip)
    
    return caption_clips

def process_video(input_path, output_path, model_path, font_path, font_size=200, y_offset=700):
    try:
        # Extract audio
        audio_path = "temp_audio.wav"
        logging.info("Starting video processing...")
        
        if not extract_audio(input_path, audio_path):
            logging.error("Audio extraction failed")
            return False
            
        if not os.path.exists(audio_path):
            logging.error(f"Audio file {audio_path} was not created")
            return False
            
        # Transcribe audio
        logging.info("Starting transcription...")
        word_timings = transcribe_audio(audio_path, model_path)
        
        if not word_timings:
            logging.error("No words were transcribed.")
            return False

        # Create caption clips
        logging.info("Creating video with captions...")
        video = VideoFileClip(input_path)
        caption_clips = create_caption_clips(word_timings, video.w, video.h, font_path, font_size, y_offset)
        
        # Overlay captions
        final_video = CompositeVideoClip([video] + caption_clips, size=(video.w, video.h))
        
        logging.info(f"Writing final video to {output_path}")
        final_video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            temp_audiofile='temp-audio.m4a',
            remove_temp=True,
            logger=None  # Disable moviepy's internal logger
        )
        
        # Cleanup
        logging.info("Cleaning up temporary files...")
        if os.path.exists(audio_path):
            os.remove(audio_path)
        video.close()
        final_video.close()
        logging.info("Video processing completed successfully")
        return True
        
    except Exception as e:
        logging.error(f"Error processing video: {str(e)}")
        if 'video' in locals():
            video.close()
        if 'final_video' in locals():
            final_video.close()
        if os.path.exists(audio_path):
            os.remove(audio_path)
        return False
