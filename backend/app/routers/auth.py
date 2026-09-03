"""认证路由"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from ..auth import create_access_token, verify_credentials, get_current_user
from ..schemas import TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends()):
    if not verify_credentials(form.username, form.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResponse(access_token=create_access_token(form.username), username=form.username)


@router.get("/me")
def me(username: str = Depends(get_current_user)):
    return {"username": username}
