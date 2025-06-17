from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from app.caption import process_video
import os
import tempfile
import asyncio
from pathlib import Path
import threading

app = FastAPI()

# Global lock to prevent concurrent processing
processing_lock = threading.Lock()
processing_in_progress = False

# Constants 
MODEL_PATH = "/app/vosk-model-en-us-0.22"
FONT_PATH = "/app/fonts/Lexend-Bold.ttf"

@app.get("/status")
async def get_status():
    """Get current processing status"""
    return {
        "processing_in_progress": processing_in_progress,
        "service": "Vosk Captions API"
    }

@app.post("/caption/")
async def create_caption(
   video: UploadFile = File(...),
   font_size: int = Form(200), 
   y_offset: int = Form(700)
):
   global processing_in_progress
   
   # Check if processing is already in progress
   with processing_lock:
       if processing_in_progress:
           raise HTTPException(
               status_code=429,
               detail="Video processing already in progress. Please wait."
           )
       processing_in_progress = True
   
   try:
       if not video.filename.endswith(('.mp4', '.avi', '.mov')):
           raise HTTPException(status_code=400, detail="Unsupported file format")
   
   # Get original filename and extension
   original_filename = video.filename
   file_extension = os.path.splitext(original_filename)[1]
   
   # Create temporary files for processing
   with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_input, \
        tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_output:
       
       # Save uploaded video
       content = await video.read()
       temp_input.write(content)
       temp_input.flush()
       
       # Process video
       success = process_video(
           temp_input.name,
           temp_output.name,
           MODEL_PATH,
           FONT_PATH,
           font_size,
           y_offset
       )
       
       if not success:
           # Clean up files before raising exception
           os.unlink(temp_input.name)
           os.unlink(temp_output.name)
           raise HTTPException(status_code=500, detail="Failed to process video")
       
       # Create async cleanup function
       async def cleanup_files():
           try:
               # Use asyncio to run file deletion in a thread pool
               await asyncio.get_event_loop().run_in_executor(
                   None, os.unlink, temp_input.name
               )
               await asyncio.get_event_loop().run_in_executor(
                   None, os.unlink, temp_output.name
               )
           except Exception as e:
               print(f"Cleanup error: {str(e)}")
       
       # Properly format filename in Content-Disposition header
       headers = {
           'Content-Type': 'video/mp4',
           'Content-Disposition': f'attachment; filename="{Path(original_filename).name}"'
       }

       response = FileResponse(
           path=temp_output.name,
           headers=headers
       )
       
       response.background = cleanup_files
       return response
   
   finally:
       # Always reset the processing flag
       with processing_lock:
           processing_in_progress = False

if __name__ == "__main__":
   import uvicorn
   uvicorn.run(app, host="0.0.0.0", port=8080)
