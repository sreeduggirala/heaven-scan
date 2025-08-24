# main.py
import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "443")),
        reload=os.getenv("RELOAD", "0") == "1",
        log_level=os.getenv("LOG_LEVEL", "info"),
        workers=int(os.getenv("WORKERS", "1")),  # keep 1 unless you externalize state
    )
