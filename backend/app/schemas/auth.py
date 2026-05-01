from pydantic import BaseModel, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenBody(BaseModel):
    email: EmailStr
    password: str
