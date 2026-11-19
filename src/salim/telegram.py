"""Bot do Telegram: comandos simples, só para IDs autorizados, lançamento com confirmação e idempotente."""
import json
import urllib.request
from dataclasses import dataclass
from datetime import date

from salim import botstate, ledger, nlentry, proposals, queries
from salim.channels import Incoming, TelegramChannel
from salim.money import brl, parse_brl

AJUDA = ("Comandos:\n/saldo [conta] — saldo do caixa ou de uma conta\n/orcamento — orçado × realizado do mês\n"
         "/faturas — contas a pagar (30 dias)\n/lancar <valor> <débito> <crédito> <descrição> — propõe um lançamento\n"
         "/ok — confirma a proposta · /cancelar — descarta")


@dataclass
class Reply:
    chat_id: int
    text: str


class HttpSender:
    """Envia pela API do Telegram (só stdlib). Em teste, troque por qualquer função (chat_id, text)."""
    def __init__(self, token: str, timeout: float = 10):
        self.url, self.timeout = f"https://api.telegram.org/bot{token}/sendMessage", timeout

    def __call__(self, chat_id: int, text: str) -> None:
        req = urllib.request.Request(self.url, data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=self.timeout).close()


def _dm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


class Bot:
    def __init__(self, session_factory, allowed_ids: set[int], clock=date.today, remember_updates: int = 1000,
                 interpreter=None, channel=None):
        self.sf, self.allowed, self.clock, self.interpreter = session_factory, set(allowed_ids), clock, interpreter
        self.channel = channel or TelegramChannel()
        self.remember = remember_updates

    # ------------------------------------------------------------ entrada
    def handle(self, native: dict) -> list[Reply]:
        """Recebe a entrega no formato do canal e devolve as respostas a enviar."""
        return [r for inc in self.channel.parse(native) for r in self._message(inc)]

    def _message(self, inc: Incoming) -> list[Reply]:
        if inc.user_id not in self.allowed:
            return []
        chat, uid, texto = inc.chat_id, inc.msg_id, inc.text
        if uid is not None:
            with self.sf() as s:
                if not botstate.first_time(s, self.channel.name, uid, self.remember):
                    return []
        if not texto.startswith("/"):
            return [Reply(chat, self._texto_livre(chat, uid, texto))]
        cmd, _, resto = texto.partition(" ")
        cmd = cmd.lower().split("@")[0]
        handler = {"/saldo": self._saldo, "/orcamento": self._orcamento, "/faturas": self._faturas,
                   "/lancar": self._lancar, "/ok": self._ok, "/cancelar": self._cancelar}.get(cmd)
        if handler is None:
            return [Reply(chat, AJUDA if cmd in ("/ajuda", "/start") else "Não entendi. " + AJUDA)]
        return [Reply(chat, handler(chat, uid, resto.strip()))]

    # ------------------------------------------------------------ comandos
    def _saldo(self, chat, uid, arg):
        with self.sf() as s:
            if arg:
                try:
                    r = queries.get_balance(s, arg.split()[0])
                except ledger.AccountNotFoundError:
                    return f"Não encontrei a conta {arg.split()[0]}."
                return f"{r['name']} ({r['code']}): {brl(r['balance_cents'])}"
            caixa = [c for _, c in ledger.account_tree(s) if c.is_cash and not c.is_group]
            linhas, total = [], 0
            for c in caixa:
                v = ledger.balance(s, c.code)
                total += v
                linhas.append(f"{c.name}: {brl(v)}")
        return "\n".join(linhas + [f"Total: {brl(total)}"])

    def _orcamento(self, chat, uid, arg):
        hoje = self.clock()
        with self.sf() as s:
            itens = queries.get_budget_status(s, ledger.month_start(hoje), hoje)
        if not itens:
            return "Nenhuma meta definida para este mês."
        marca = {"acima_do_ritmo": " ⚠ acima do ritmo", "estourado": " ⚠ estourado", "ok": ""}
        return "\n".join(f"{i['name']}: {brl(i['actual_cents'])} de {brl(i['budget_cents'])} "
                         f"({i['pct_used'] if i['pct_used'] is not None else '—'}%){marca[i['alert']]}" for i in itens)

    def _faturas(self, chat, uid, arg):
        with self.sf() as s:
            itens = queries.get_upcoming_payables(s, self.clock(), 30)
        if not itens:
            return "Nada a pagar nos próximos 30 dias."
        linhas = []
        for i in itens:
            situacao = f"atrasada {i['days_late']} dias" if i["status"] == "atrasada" else i["status"].replace("_", " ")
            nome = i["counterparty"] or i["reference"] or i["kind"]
            linhas.append(f"{_dm(i['due_date'])} {nome} — {brl(i['balance_cents'])} ({situacao})")
        return "\n".join(linhas + [f"Total: {brl(sum(i['balance_cents'] for i in itens))}"])

    def _texto_livre(self, chat, uid, texto):
        with self.sf() as s:
            p = nlentry.parse_entry_text(s, texto, self.clock(), fallback=self.interpreter)
        if p is None:
            return "Não entendi. " + AJUDA
        if not p["ok"]:
            return ("Entendi o valor, mas não identifiquei a categoria. Diga a conta com "
                    "/lancar <valor> <débito> <crédito> <descrição>.")
        return self._mostrar(chat, uid, p)

    def _lancar(self, chat, uid, arg):
        self._descartar(chat)
        partes = arg.split(None, 3)
        if len(partes) < 4:
            return "Uso: /lancar <valor> <conta débito> <conta crédito> <descrição>"
        try:
            cents = parse_brl(partes[0])
        except ValueError:
            return f"Valor inválido: {partes[0]}"
        if cents <= 0:
            return f"Valor inválido: {partes[0]}"
        with self.sf() as s:
            p = proposals.propose_simple(s, event_date=self.clock(), description=partes[3], amount_cents=cents,
                                         debit_account=partes[1], credit_account=partes[2])
        if not p["ok"]:
            return "Não deu certo: " + "; ".join(p["errors"])
        return self._mostrar(chat, uid, p)

    def _mostrar(self, chat, uid, p):
        with self.sf() as s:
            botstate.put_pending(s, self.channel.name, chat, p, f"{self.channel.ref_prefix}:{chat}:{uid}")
        d, c = p["entries"]
        return (f"Lançamento {_dm(p['event_date'])} — {p['description']}\n"
                f"Débito: {d['account_name']} ({d['account_code']}) {brl(d['amount_cents'])}\n"
                f"Crédito: {c['account_name']} ({c['account_code']}) {brl(-c['amount_cents'])}\n"
                "Responda /ok para registrar ou /cancelar.")

    def _ok(self, chat, uid, arg):
        with self.sf() as s:
            item = botstate.pop_pending(s, self.channel.name, chat)
        if item is None:
            return "Nada pendente."
        with self.sf() as s:
            try:
                r = proposals.confirm_transaction(s, item["proposal"], source=self.channel.name, external_ref=item["ref"])
            except ValueError as e:
                return f"Não registrei: {e}"
        return "Esse lançamento já estava registrado." if r["duplicate"] else f"Registrado (#{r['transaction_id']})."

    def _descartar(self, chat) -> bool:
        with self.sf() as s:
            return botstate.pop_pending(s, self.channel.name, chat) is not None

    def _cancelar(self, chat, uid, arg):
        return "Proposta cancelada." if self._descartar(chat) else "Nada pendente."
