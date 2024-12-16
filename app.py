from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from moviepy import *
import tempfile
import os
import logging
from caption_processor import process_video
import uvicorn

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

@app.post("/caption/video")
async def caption_video(
    video: UploadFile = File(...),
    font_path: str = "/app/fonts/Lexend-Bold.ttf"
):
    # Create temporary files for processing
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as input_video:
        # Save uploaded video
        content = await video.read()
        input_video.write(content)
        input_video.flush()
        
        # Create temporary output path
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as output_video:
            try:
                # Process the video
                process_video(input_video.name, output_video.name, font_path)
                
                # Return the processed video
                return FileResponse(
                    output_video.name,
                    media_type="video/mp4",
                    filename=f"captioned_{video.filename}"
                )
            finally:
                # Cleanup temporary files
                os.unlink(input_video.name)
                if os.path.exists(output_video.name):
                    os.unlink(output_video.name)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
