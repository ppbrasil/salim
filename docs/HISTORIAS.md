# Salim — Histórias (v2, modelo de títulos)

Modelo: `docs/MODELO.md`. Schema: `src/salim/schema.sql` (fonte única). Cada história toca ≤2 arquivos de produção (+ teste). **B** = back, **F** = front.

Decisões: gestão por **competência (mês)**; compra parcelada entra inteira na competência da compra; juros e multa em contas separadas; caixa mostra o pagamento do título.

## E0 Fundação ✅
0.1 projeto e pytest · 0.2 `/health` · 0.3 sessão de banco por teste

## E1 Ledger ✅ v1 (1.1–1.10) · v2 migrando ao modelo de títulos
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 1.11 | Schema SQL como fonte única | Tabelas, views, triggers e FKs existem | B db.py, schema.sql |
| 1.12 | Flags de conta (`is_cash`, `tracks_obligations`, dia de fechamento/vencimento) | Persistem; grupo não pode ser caixa/título | B models.py, ledger.py |
| 1.13 | Competência é mês (dia 01) | Qualquer data normaliza para o dia 01 | B ledger.py |
| 1.14 | Partida aponta para título | Conta com título exige `obligation_id`; título de outra conta é rejeitado; banco também barra | B models.py, ledger.py |
| 1.15 | Imutabilidade no banco | SQL direto de UPDATE/DELETE falha; só vencimento e data planejada do título mudam | B schema.sql |
| 1.16 | Plano padrão v2 | Flags, juros e multa separados, parcelamentos | B chart.py |

## E2 Interface web
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 2.1 | `GET /accounts` árvore com saldos | JSON aninhado | B app.py |
| 2.2 | `POST /transactions` | 201; soma ≠ 0 → 422 | B app.py |
| 2.3 | `GET /accounts/{code}/statement` | Linhas com competência e saldo corrente | B app.py |
| 2.4 | Tela do plano de contas | HTML com contas e saldos | B app.py, F accounts.html |
| 2.5 | Tela de novo lançamento | Posta e redireciona; erro aparece na tela | B app.py, F transaction_form.html |
| 2.6 | Tela de extrato | Lista com competência | B app.py, F statement.html |

## E3 Títulos (fatura, parcela, boleto, dívida, reembolso) ✅
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 3.1 | Criar título | Persiste com vencimento; saldo 0 | B obligations.py |
| 3.2 | Saldo e status do título | quitada / a_vencer / atrasada (+dias) / aberta / crédito | B obligations.py |
| 3.3 | Pagar título (total, parcial, vários numa saída) | Saldo cai; uma saída de caixa | B obligations.py |
| 3.4 | Compra no cartão cai na fatura certa e abre a fatura sozinha | Antes/depois do fechamento → faturas diferentes | B obligations.py |
| 3.5 | Compra parcelada no cartão | Competência cheia; N faturas | B obligations.py |
| 3.6 | Parcelar um título | Original zera; N parcelas; juros em linha própria | B obligations.py |
| 3.7 | Consolidar títulos (renegociação) | Originais zeram; novo título; multa em linha própria; competências intactas | B obligations.py |
| 3.8 | Reembolso a receber | Só minha parte é despesa; título a receber | B obligations.py |
| 3.9 | Estorno reabre título | Pagamento estornado volta a dever | B ledger.py |
| 3.10 | Mudar vencimento e data planejada | Só esses campos mudam | B obligations.py |
| 3.11 | API: títulos e aging | `GET /obligations?status=atrasada` | B app.py |
| 3.12 | Tela "a pagar" | Por vencimento, com atraso destacado | B app.py, F payables.html |

## E4 DRE, caixa e orçamento ✅
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 4.1 | DRE por competência | Inclui não pago; juros e multa em linhas próprias | B reports.py |
| 4.2 | Caixa executado | Por mês, só contas de caixa | B reports.py |
| 4.3 | Caixa futuro | Títulos por data planejada ou vencimento | B reports.py |
| 4.4 | Orçamento: mês padrão e exceções | Mês específico sobrescreve o padrão | B budget.py |
| 4.5 | Orçado × realizado por competência | Soma subárvore; restante e % | B budget.py |
| 4.6 | Perfil pontual × diluído e alerta | Aluguel no dia 5 sem alerta; mercado acima do esperado alerta | B budget.py |
| 4.7 | Telas: DRE, caixa, orçamento | HTML com números | B app.py, F reports.html |

## E5 Consulta e MCP ✅
5.1 camada de consulta única (`queries.py`) · 5.2 servidor MCP `get_balance` · 5.3 `get_statement` · 5.4 `get_budget_status` · 5.5 `get_upcoming_payables` · 5.6 `propose_transaction` (não grava) · 5.7 `confirm_transaction`

## E6 Telegram ✅
6.1 webhook + `/saldo` · 6.2 só IDs autorizados · 6.3 `/orcamento` e `/faturas` · 6.4 lançamento com confirmação · 6.5 idempotência por `external_ref`

## E7 Lançamento por texto ✅
7.1 texto livre → proposta (regras determinísticas, plugável para LLM) · 7.2 sugestão de conta pelo histórico

## E8 Importação ✅ (API; sem tela)
8.1 CSV de extrato → fila · 8.2 casar com lançamento existente · 8.3 criar lançamento do item · 8.4 contrato do conector Open Finance

## E9 Canal comum e WhatsApp ✅ (adaptador testado com payloads simulados)
9.1 interface de canal · 9.2 adaptador WhatsApp com os mesmos testes do Telegram

## Situação (19/11/2026)
E0–E9 implementados + camada de produção (login, backup diário, HTTPS via Caddy): 246 testes verdes com `-W error`. Falta antes de uso com dinheiro real: `docker build` rodado fora deste ambiente, restauração de backup testada no servidor, backup copiado para fora do servidor, versionamento de schema (Alembic), WhatsApp/Telegram testados contra as APIs reais, tela de importação, MCP por HTTP (hoje só stdio).

## Riscos conhecidos
- Migrações: schema nasce do `schema.sql`; antes de dados reais entra Alembic ou versionamento de schema.
- Soma do lançamento = 0 é validada no serviço, não no banco (SQLite sem constraint diferida).
- Aging histórico ("como estava em outubro") precisa filtrar por `event_date`.
- Ordenação de códigos de conta é lexicográfica; o plano padrão usa 2 dígitos por nível.
