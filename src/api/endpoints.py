from fastapi import APIRouter, Depends, HTTPException
from src.api.auth import authenticate_user
from pydantic import BaseModel, Field
from src.services.llm import llm_request


router = APIRouter()

class CommandRequest(BaseModel):
    input: str = Field(..., min_length=1)
    provider: str = "ollama"

@router.get("/")
def get_status():
    return {
        "status": "running"
    }

@router.post("/execute", dependencies=[Depends(authenticate_user)])
def execute_command(data: CommandRequest):
    result = llm_request(data.input, data.provider)

    return {
        "status": "success",
        "analysis_result": result,
        "provider": data.provider
    }