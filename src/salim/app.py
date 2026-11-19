from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Salim")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
