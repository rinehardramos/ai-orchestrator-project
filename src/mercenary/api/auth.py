"""
Authentication endpoints.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import jwt
import bcrypt

from src.mercenary.config import config
from src.mercenary.db import UserRepository

auth_router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()
user_repo = UserRepository()


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: Optional[str]
    balance: float
    created_at: datetime


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(minutes=config.JWT_EXPIRY_MINUTES),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm="HS256")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(
            credentials.credentials, 
            config.JWT_SECRET_KEY, 
            algorithms=["HS256"]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@auth_router.post("/signup", response_model=TokenResponse)
async def signup(request: SignupRequest):
    existing = user_repo.get_by_email(request.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    password_hash = hash_password(request.password)
    user = user_repo.create(
        email=request.email,
        password_hash=password_hash,
        display_name=request.display_name
    )
    
    token = create_token(user.id)
    
    return TokenResponse(
        access_token=token,
        expires_in=config.JWT_EXPIRY_MINUTES * 60
    )


@auth_router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    user = user_repo.get_by_email(request.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user.id)
    
    return TokenResponse(
        access_token=token,
        expires_in=config.JWT_EXPIRY_MINUTES * 60
    )


@auth_router.get("/me", response_model=UserResponse)
async def get_me(user = Depends(get_current_user)):
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        balance=user.balance,
        created_at=user.created_at
    )
