from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse
from app.caption import process_video
import os
import tempfile
import asyncio
from pathlib import Path
import threading
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# File size limits (500MB max)
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB in bytes

@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    """Middleware to limit upload size"""
    if request.method == "POST" and request.url.path.startswith("/caption"):
        # Check Content-Length header
        content_length = request.headers.get("content-length")
        if content_length:
            content_length = int(content_length)
            if content_length > MAX_FILE_SIZE * 1.1:  # Allow 10% overhead for multipart
                logger.warning(f"Upload too large: {content_length} bytes")
                raise HTTPException(
                    status_code=413, 
                    detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"
                )
    
    response = await call_next(request)
    return response

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
        "service": "Vosk Captions API",
        "max_file_size_mb": MAX_FILE_SIZE // (1024*1024)
    }

@app.post("/caption")
@app.post("/caption/")  # Support both with and without trailing slash
async def create_caption(
   video: UploadFile = File(...),
   font_size: int = Form(200), 
   y_offset: int = Form(700)
):
   global processing_in_progress
   
   logger.info(f"Received upload request: {video.filename}, content_type: {video.content_type}")
   
   # Check if processing is already in progress
   with processing_lock:
       if processing_in_progress:
           raise HTTPException(
               status_code=429,
               detail="Video processing already in progress. Please wait."
           )
       processing_in_progress = True
   
   try:
       # Validate file type
       if not video.filename or not video.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')):
           raise HTTPException(
               status_code=400, 
               detail="Unsupported file format. Please use MP4, AVI, MOV, MKV, or WebM"
           )
   
       # Get original filename and extension
       original_filename = video.filename
       file_extension = os.path.splitext(original_filename)[1]
       
       # Create temporary files for processing
       with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_input, \
            tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_output:
           
           # Save uploaded video with chunked reading to handle large files
           logger.info("Reading uploaded video file...")
           file_size = 0
           chunk_size = 1024 * 1024  # 1MB chunks
           
           while chunk := await video.read(chunk_size):
               if not chunk:
                   break
               file_size += len(chunk)
               
               # Check file size during upload
               if file_size > MAX_FILE_SIZE:
                   raise HTTPException(
                       status_code=413,
                       detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"
                   )
               
               temp_input.write(chunk)
           
           temp_input.flush()
           logger.info(f"Successfully saved {file_size} bytes to temporary file")
           
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
           
           # Sanitize filename for HTTP headers (remove Unicode characters)
           import re
           import unicodedata
           
           def sanitize_filename(filename):
               """Remove or replace characters that can't be encoded in latin-1"""
               # Normalize Unicode characters
               filename = unicodedata.normalize('NFD', filename)
               # Remove combining characters and non-ASCII
               filename = ''.join(c for c in filename if ord(c) < 128)
               # Replace any remaining problematic characters
               filename = re.sub(r'[^\w\s.-]', '_', filename)
               # Clean up multiple underscores/spaces
               filename = re.sub(r'[_\s]+', '_', filename)
               return filename
           
           safe_filename = sanitize_filename(Path(original_filename).name)
           
           # Properly format filename in Content-Disposition header
           headers = {
               'Content-Type': 'video/mp4',
               'Content-Disposition': f'attachment; filename="{safe_filename}"'
           }

           response = FileResponse(
               path=temp_output.name,
               headers=headers
           )
           
           response.background = cleanup_files
           return response
   
   except HTTPException as e:
       # Re-raise HTTP exceptions as-is
       raise e
   except Exception as e:
       logger.error(f"Unexpected error during video processing: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
   finally:
       # Always reset the processing flag
       with processing_lock:
           processing_in_progress = False

if __name__ == "__main__":
   import uvicorn
   uvicorn.run(app, host="0.0.0.0", port=8080)
