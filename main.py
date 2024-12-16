import os
import tempfile
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
from app.caption import process_video

app = FastAPI()

# Constants
MODEL_PATH = "/app/vosk-model-en-us-0.22"
FONT_PATH = "/app/fonts/Lexend-Bold.ttf"

@app.post("/caption/")
async def create_caption(
    video: UploadFile,
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
            raise HTTPException(status_code=500, detail="Failed to process video")
        
        # Return processed video
        response = FileResponse(
            temp_output.name,
            media_type="video/mp4",
            filename=f"captioned_{video.filename}"
        )
        
        # Schedule cleanup
        def cleanup():
            os.unlink(temp_input.name)
            os.unlink(temp_output.name)
        
        response.background = cleanup
        return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)