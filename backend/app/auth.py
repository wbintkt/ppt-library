"""JWT 认证（单用户）"""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from .config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ALGORITHM = "HS256"


def verify_credentials(username: str, password: str) -> bool:
    return username == settings.auth_username and password == settings.auth_password


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.token_expire_minutes)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    token_q: str = Query("", alias="token"),
) -> str:
    """认证：支持 Authorization header 或 ?token= query（图片直链用）"""
    actual = token_q or token
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已失效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not actual:
        raise credentials_exception
    try:
        payload = jwt.decode(actual, settings.secret_key, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception
