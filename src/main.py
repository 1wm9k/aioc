from fastapi import FastAPI
from src.api.endpoints import router as api_router
from src.config import settings  

app = FastAPI(title="AIOC Mini Server")

app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app", 
        host=settings.SERVER_HOST, 
        port=settings.SERVER_PORT, 
        reload=True
    )