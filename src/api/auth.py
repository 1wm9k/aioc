import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from src.config import settings


SECRET_USERNAME = settings.APP_USERNAME
SECRET_PASSWORD = settings.APP_PASSWORD

security = HTTPBasic()

def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != SECRET_USERNAME or credentials.password != SECRET_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username