import os
import tempfile
from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import FileResponse
from app.caption import process_video

app = FastAPI()

# Constants
MODEL_PATH = "/app/vosk-model-en-us-0.22"
FONT_PATH = "/app/fonts/Lexend-Bold.ttf"

@app.post("/caption")
async def create_captions(
    video: UploadFile,
    font_size: int = Form(200),
    y_offset: int = Form(700)
):
    # Create temporary files for input and output
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_in, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_out:
        
        # Save uploaded video
        content = await video.read()
        tmp_in.write(content)
        tmp_in.flush()
        
        try:
            # Process the video
            process_video(
                tmp_in.name,
                tmp_out.name,
                MODEL_PATH,
                FONT_PATH,
                font_size,
                y_offset
            )
            
            # Return the processed video
            return FileResponse(
                tmp_out.name,
                media_type="video/mp4",
                filename=f"captioned_{video.filename}"
            )
        finally:
            # Cleanup temporary files
            os.unlink(tmp_in.name)
            os.unlink(tmp_out.name)