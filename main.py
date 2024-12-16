from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
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
    temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(video.filename)[1])
    temp_output = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    
    try:
        # Save uploaded video
        content = await video.read()
        temp_input.write(content)
        temp_input.close()
        
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
        
        # Create async cleanup function
        async def cleanup():
            await asyncio.sleep(0)  # Ensure this runs after response is sent
            try:
                os.unlink(temp_input.name)
                os.unlink(temp_output.name)
            except Exception as e:
                print(f"Cleanup error: {e}")
        
        # Return processed video
        return FileResponse(
            temp_output.name,
            media_type="video/mp4",
            filename=f"captioned_{video.filename}",
            background=cleanup
        )
            
    except Exception as e:
        # Clean up in case of error
        os.unlink(temp_input.name)
        os.unlink(temp_output.name)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
