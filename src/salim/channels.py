"""Canais de mensagem: cada um traduz seu formato nativo para `Incoming` e sabe enviar uma resposta."""
import json
import urllib.request
from dataclasses import dataclass


@dataclass
class Incoming:
    user_id: object      # quem enviou (Telegram: int; WhatsApp: telefone)
    chat_id: object      # para onde responder
    msg_id: object       # id único da entrega, usado para ignorar reenvios
    text: str


class TelegramChannel:
    name, ref_prefix = "telegram", "tg"

    def parse(self, update: dict) -> list[Incoming]:
        m = update.get("message") or {}
        texto = (m.get("text") or "").strip()
        user, chat = (m.get("from") or {}).get("id"), (m.get("chat") or {}).get("id")
        if not texto or user is None or chat is None:
            return []
        return [Incoming(user, chat, update.get("update_id"), texto)]


class WhatsAppChannel:
    """Formato do webhook da WhatsApp Cloud API."""
    name, ref_prefix = "whatsapp", "wa"

    def parse(self, payload: dict) -> list[Incoming]:
        saida = []
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                for m in (change.get("value") or {}).get("messages") or []:
                    texto = ((m.get("text") or {}).get("body") or "").strip() if m.get("type") == "text" else ""
                    if texto and m.get("from"):
                        saida.append(Incoming(m["from"], m["from"], m.get("id"), texto))
        return saida


class WhatsAppSender:
    """Envia pela Cloud API (só stdlib). Em teste, troque por qualquer função (destinatário, texto)."""
    def __init__(self, token: str, phone_number_id: str, timeout: float = 10):
        self.url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
        self.token, self.timeout = token, timeout

    def __call__(self, to: str, text: str) -> None:
        corpo = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
        req = urllib.request.Request(self.url, data=json.dumps(corpo).encode(), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        urllib.request.urlopen(req, timeout=self.timeout).close()
