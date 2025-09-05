import aiosqlite
import uvicorn
import datetime
import secrets
import jwt
import hashlib
import os

from typing import Any
from fastapi import FastAPI, Depends, HTTPException, Request, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, SecretStr
from contextlib import asynccontextmanager
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

SECRET_KEY = "fc2b20edc79f41422c1cbaf115be91b9"
ALGORITHM = "HS256"

SQLITE_DB_NAME = "mydb.db"

templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(SQLITE_DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                nickname TEXT NOT NULL,
                pfp TEXT
            );
        """)
        await db.commit()
    yield


app = FastAPI(
    title="Discord Style Messenger",
    description="Messenger приложение с регистрацией и авторизацией",
    version="0.1.0",
    lifespan=lifespan
)


def create_jwt(
        payload: dict[str, Any], expires_delta: datetime.timedelta | None = None
) -> str:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    payload_copy = payload.copy()

    if expires_delta is not None:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + datetime.timedelta(minutes=15)

    jti = secrets.token_urlsafe()
    payload_copy.update(exp=expire, iat=now_utc, jti=jti)

    try:
        token = jwt.encode(payload_copy, key=SECRET_KEY, algorithm=ALGORITHM)
    except jwt.PyJWTError as e:
        raise ValueError(f"Error while encoding token: {e}") from e

    return token


def decode_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, key=SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return {}


def hash_password(password: str) -> str:
    """Hash password using PBKDF2 with SHA256"""
    salt = os.urandom(32)  # 32 bytes salt
    pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + pwdhash.hex()


def verify_password(stored_password: str, provided_password: str) -> bool:
    """Verify password against stored hash"""
    salt = bytes.fromhex(stored_password[:64])  # First 32 bytes (64 hex chars) are salt
    stored_hash = stored_password[64:]  # Rest is the hash
    pwdhash = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
    return pwdhash.hex() == stored_hash


async def get_db():
    async with aiosqlite.connect(SQLITE_DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None

    payload = decode_jwt(token)
    username = payload.get("sub")
    return username


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserShow(BaseModel):
    username: str


class Token(BaseModel):
    token_type: str
    access_token: str


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    username = await get_current_user(request)
    if not username:
        return RedirectResponse(url="/sign-in", status_code=303)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "username": username
    })


@app.get("/sign-in", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("sign-in.html", {"request": request})


@app.post("/sign-in", response_class=HTMLResponse)
async def login_form(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        connection: aiosqlite.Connection = Depends(get_db)
):
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT * FROM users WHERE username = ?;", (username,))
            db_user = await cursor.fetchone()

            if db_user is None or not verify_password(db_user["password"], password):
                return templates.TemplateResponse(
                    "sign-in.html",
                    {"request": request, "error": "Неверный логин или пароль"}
                )

        token = create_jwt({"sub": username})
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=3600 * 24 * 31
        )
        return response

    except Exception as e:
        return templates.TemplateResponse(
            "sign-in.html",
            {"request": request, "error": "Произошла ошибка при входе"}
        )


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/sign-in", status_code=303)
    response.delete_cookie("access_token")
    return response


@app.get("/sign-up", response_class=HTMLResponse)
async def sign_up_page(request: Request):
    return templates.TemplateResponse("sign-up.html", {"request": request})


@app.post("/sign-up", response_class=HTMLResponse)
async def sign_up_form(
        request: Request,
        username: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        connection: aiosqlite.Connection = Depends(get_db)
):
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1 FROM users WHERE username = ?;", (username,))
            db_user = await cursor.fetchone()

            if db_user is not None:
                return templates.TemplateResponse(
                    "sign-up.html",
                    {"request": request, "error": "Пользователь с таким именем уже существует"}
                )

            hashed_password = hash_password(password)
            await cursor.execute(
                "INSERT INTO users (username, email, password, nickname) VALUES (?, ?, ?, ?);",
                (username, email, hashed_password, username)
            )
            await connection.commit()

        return RedirectResponse(url="/sign-in", status_code=303)

    except Exception as e:
        return templates.TemplateResponse(
            "sign-up.html",
            {"request": request, "error": "Произошла ошибка при регистрации"}
        )


@app.post(
    "/api/register",
    status_code=status.HTTP_200_OK,
    response_model=UserShow,
    tags=["register"],
    summary="User registration",
    description="Endpoint used for registering new users",
)
async def user_registration(user_data: UserCreate, connection: aiosqlite.Connection = Depends(get_db)) -> UserShow:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT 1 FROM users WHERE username = ?;", (user_data.username,))
        db_user = await cursor.fetchone()

        if db_user is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "User exists.")

        hashed_password = hash_password(user_data.password)
        await cursor.execute(
            "INSERT INTO users (username, email, password, nickname) VALUES (?, ?, ?, ?) RETURNING id;",
            (user_data.username, user_data.email, hashed_password, user_data.username),
        )

        last_inserted = await cursor.fetchone()
        await connection.commit()

    return UserShow(username=user_data.username)


@app.post("/api/login", response_model=Token, tags=["auth"])
async def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        connection: aiosqlite.Connection = Depends(get_db),
) -> Token:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT * FROM users WHERE username = ?;", (form_data.username,)
        )
        db_user = await cursor.fetchone()

        if db_user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User does not exist.")

    if not verify_password(db_user["password"], form_data.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect password.")

    token = create_jwt({"sub": form_data.username})
    return Token(
        access_token=token,
        token_type="bearer"
    )


@app.get("/api/search-user/{username}")
async def search_user(username: str, connection: aiosqlite.Connection = Depends(get_db)):
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT username, nickname, pfp FROM users WHERE username = ?;",
            (username,)
        )
        user = await cursor.fetchone()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="Человека с таким username'ом не найдено"
            )

        return {
            "username": user["username"],
            "nickname": user["nickname"] or user["username"],
            "pfp": user["pfp"]
        }


if __name__ == '__main__':
    uvicorn.run("app:app", reload=True, port=8000)
