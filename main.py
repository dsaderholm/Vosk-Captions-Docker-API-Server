from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from app.caption import process_video
import os
import tempfile
import asyncio

app = FastAPI()

# Constants
MODEL_PATH = "/app/vosk-model-en-us-0.22"
FONT_PATH = "/app/fonts/Lexend-Bold.ttf"

@app.post("/caption/")
async def create_caption(
    video: UploadFile = File(...),
    font_size: int = Form(200),
    y_offset: int = Form(700)
):
    if not video.filename.endswith(('.mp4', '.avi', '.mov')):
        raise HTTPException(status_code=400, detail="Unsupported file format")
    
    # Create temporary files for processing
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video.filename)[1]) as temp_input, \
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

        response = FileResponse(
            temp_output.name,
            media_type="video/mp4",
            filename=f"captioned_{video.filename}"
        )
        
        response.background = cleanup_files
        return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
