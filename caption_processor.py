import os
import wave
import logging
import subprocess
from moviepy import *
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from vosk import Model, KaldiRecognizer, SetLogLevel
import json

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_audio(video_path, audio_path):
    command = [
        "ffmpeg",
        "-i", video_path,
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", "16000",
        audio_path
    ]
    subprocess.run(command, check=True)
    logging.info(f"Audio extracted to {audio_path}")

def transcribe_audio(audio_path, model_path):
    SetLogLevel(0)
    wf = wave.open(audio_path, "rb")
    
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

def create_caption_clips(word_timings, video_width, video_height, font_path):
    caption_clips = []
    font_size = 200
    y_offset = 700

    for word in word_timings:
        img_array = create_text_image(word['word'], (video_width, 120), font_size, (255, 255, 255, 255), font_path)
        clip = ImageClip(img_array, duration=word['end'] - word['start'])
        clip = clip.set_position(('center', video_height - y_offset)).set_start(word['start'])
        caption_clips.append(clip)
    
    return caption_clips

def process_video(input_path, output_path, font_path):
    # Create temporary audio file
    audio_path = f"{input_path}_temp_audio.wav"
    
    try:
        # Extract audio
        extract_audio(input_path, audio_path)
        
        # Get model path
        model_path = "/app/vosk-model-en-us-0.22"
        
        # Transcribe audio
        word_timings = transcribe_audio(audio_path, model_path)
        
        if not word_timings:
            raise ValueError("No words were transcribed")

        # Create caption clips
        video = VideoFileClip(input_path)
        caption_clips = create_caption_clips(word_timings, video.w, video.h, font_path)
        
        # Overlay captions on video
        final_video = CompositeVideoClip([video] + caption_clips)
        
        # Write output video
        final_video.write_videofile(output_path)
        
    finally:
        # Cleanup
        if os.path.exists(audio_path):
            os.remove(audio_path)
