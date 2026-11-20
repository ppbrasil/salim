"""A Vercel reescreve toda requisição para /api/index e o app perde o caminho original.

O vercel.json repassa o caminho real na query (`/api/index?__p=<caminho>`); este envelope ASGI o devolve
ao `scope` antes de o FastAPI rotear, para que rotas, redirecionamentos e a lista de caminhos abertos
(/login, /health, webhooks) enxerguem o caminho de verdade.
"""
from urllib.parse import parse_qsl, urlencode

PARAM = "__p"


class RestaurarCaminhoOriginal:
    def __init__(self, app, param: str = PARAM):
        self.app = app
        self.param = param

    def __getattr__(self, nome):  # app.state etc. continuam acessíveis
        return getattr(self.app, nome)

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            pares = parse_qsl(scope.get("query_string", b"").decode("latin1"), keep_blank_values=True)
            originais = [v for k, v in pares if k == self.param]
            if originais:
                caminho = "/" + originais[-1].lstrip("/")
                resto = [(k, v) for k, v in pares if k != self.param]
                scope = {**scope, "path": caminho, "raw_path": caminho.encode(),
                         "query_string": urlencode(resto).encode()}
        await self.app(scope, receive, send)
