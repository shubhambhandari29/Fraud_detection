"""Authentication API models."""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: EmailStr
    models: str
    branch: str | None = None


class LoginResponse(BaseModel):
    message: str
    user: UserResponse
    token: str


class UserInfoResponse(BaseModel):
    user: str
    groups: str
