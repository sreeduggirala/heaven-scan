# main.py
import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app:app",  # points to app.py -> app = FastAPI(...)
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        reload=os.getenv("RELOAD", "0") == "1",  # set RELOAD=1 for local dev
        log_level=os.getenv("LOG_LEVEL", "info"),
        workers=int(os.getenv("WORKERS", "1")),  # keep 1 while using Telethon client
    )
