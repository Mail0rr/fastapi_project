import pathlib
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

module_path = pathlib.Path(__file__).parent
templates = Jinja2Templates(directory=module_path / "templates")

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


@app.get("/sign-up", response_class=HTMLResponse)
async def registration(request: Request):
    return templates.TemplateResponse(
        "sign-up.html",
        {"request": request}
    )

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
