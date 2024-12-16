from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from app.caption import process_video
import os
import tempfile
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

# Constants
MODEL_PATH = "/app/vosk-model-en-us-0.22"
FONT_PATH = "/app/fonts/Lexend-Bold.ttf"

def cleanup_files(*files_to_delete: str):
    """Delete temporary files"""
    for file_path in files_to_delete:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logging.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logging.error(f"Error cleaning up {file_path}: {str(e)}")

@app.post("/caption/")
async def create_caption(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    font_size: int = Form(200),
    y_offset: int = Form(700)
):
    """
    Process video and add captions.
    Args:
        background_tasks: FastAPI BackgroundTasks for cleanup
        video: Input video file
        font_size: Size of caption font
        y_offset: Vertical position of captions
    Returns:
        FileResponse with processed video
    """
    if not video.filename.endswith(('.mp4', '.avi', '.mov')):
        raise HTTPException(status_code=400, detail="Unsupported file format")
    
    # Create temporary files with unique names
    temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video.filename)[1])
    temp_output = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    
    try:
        # Save uploaded video
        logging.info(f"Processing video: {video.filename}")
        content = await video.read()
        temp_input.write(content)
        temp_input.close()  # Close the file to ensure it's written
        
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
            raise HTTPException(status_code=500, detail="Failed to process video")
        
        # Verify output file exists and has content
        if not os.path.exists(temp_output.name) or os.path.getsize(temp_output.name) == 0:
            raise HTTPException(status_code=500, detail="Output video file is empty or missing")
        
        # Schedule cleanup using background tasks
        background_tasks.add_task(cleanup_files, temp_input.name, temp_output.name)
        
        logging.info(f"Successfully processed video: {video.filename}")
        
        # Return processed video
        return FileResponse(
            temp_output.name,
            media_type="video/mp4",
            filename=f"captioned_{video.filename}",
        )
        
    except Exception as e:
        logging.error(f"Error processing video {video.filename}: {str(e)}")
        # Clean up files in case of error
        cleanup_files(temp_input.name, temp_output.name)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.info("Starting captioning service...")
    uvicorn.run(app, host="0.0.0.0", port=8080)
