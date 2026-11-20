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

## E12 Visões gerenciais ✅ (20/11/2026)
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 12.1 | Renomear e mover conta entre grupos (`PATCH /accounts/{code}`) | Histórico acompanha; ciclo, tipo diferente e código repetido barrados | B ledger.py, app.py |
| 12.2 | DRE mês a mês: uma coluna por mês, grupos somam filhos, expandir/recolher, tendência por linha, gráficos (receitas × despesas; despesas por grupo) | Competência manda; só linhas com movimento; `GET /reports/dre-monthly` | B reports.py, viz.py, F dre.html |
| 12.3 | Caixa mês a mês: entrou, saiu, líquido, saldo, previsto pelos títulos, desvio vs orçado (receitas − despesas do orçamento) | Meses futuros só com projeção; grupo e filho com meta não contam em dobro; `GET /reports/cash-monthly` | B reports.py, budget.py, F cash.html |
| 12.4 | A pagar e A receber em telas próprias, com Pagar/Receber (total ou parcial) pela tela; itens de cada título; pedido de reembolso por evento (`POST /reimbursements`, `/reimbursements/{id}/items`) abatendo a despesa na própria categoria | Pagar baixa e sai do caixa; receber entra; erro aparece na tela | B obligations.py, app.py, F payables/receivables.html |

| 12.5 | Arquivar conta (`PATCH archived`), sticker "Mês atual" na DRE e no caixa, plano de despesas com no máximo 9 grupos de primeiro nível | Arquivada some do plano, de `GET /accounts` e dos formulários, mas continua nos relatórios; folha só com saldo zero; grupo só sem filhos ativos | B ledger.py, app.py, F dre.html, cash.html |
| 12.6 | DRE com receita e despesa em gráficos separados: total por mês (com valor sobre a barra) e barra de 100% por origem da receita / por grupo de despesa | Nenhum gráfico mistura receita e despesa; fatia mostra valor e % ao passar o mouse; mês sem valor não desenha barra | B viz.py, app.py, F dre.html |
| 12.7 | Gasto reembolsável entra direto em "a receber", contra o cartão ou o caixa que pagou (`payer_account_code` em `POST /reimbursements`): duas contas de balanço, nada na DRE | Despesa e receita da DRE ficam em 0; fatura/caixa e a receber andam juntos; exige despesa já lançada **ou** pagador, nunca os dois | B obligations.py, app.py |

Carga real (20/11/2026): V13–V18 refeitas por itens (75 linhas "Incluir" da planilha, 6 pedidos, R$ 5.721,94), cada item abatendo a despesa na própria categoria; `5.17.01`, `5.17` e `5.15` zeradas e arquivadas.

Pendente de E12: tela para criar pedido/itens; meses marcados como "fechado/incompleto" (aguardando decisão); editar plano de contas pela tela.

## E13 Cartões de crédito ✅ (20/11/2026)
Cada cartão é uma conta de passivo sob `2.01`, como uma conta corrente que sempre tem uma fatura aberta. Dados: nome, bandeira, final, dia de fechamento, dia de vencimento (migração `0004_cartoes.sql`).
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 13.1 | Cadastro de cartão: `POST/GET/PATCH /cards`, código `2.01.NN` automático; mudar fechamento/vencimento vale só para faturas novas | Final com 4 dígitos, bandeira conhecida, dias 1–31; melhor dia de compra = dia seguinte ao fechamento | B cards.py, ledger.py, models.py, schema.sql, migração 0004 |
| 13.2 | Resumo por cartão: fatura aberta sempre (virtual se ainda sem compra), fechadas a pagar, parcelas em faturas futuras, **devido (outstanding)** | Devido = soma das faturas = saldo da conta do cartão; depois do fechamento a aberta passa ao próximo ciclo; fatura quitada sai da lista | B cards.py |
| 13.3 | Telas Cartões (lista com devido, fatura aberta, fechadas, futuras + cadastro) e detalhe do cartão com as faturas e seus itens | Erro de cadastro aparece na tela; menu "Cartões" | B app.py, F cards.html, card.html |

Próximo (conciliação): conferir o devido de cada cartão com o extrato/fatura do cartão e registrar a diferença.

## E10 Migração para Vercel + Neon ⬜ (plano em `docs/MIGRACAO_VERCEL_NEON.md`)
M0 ✅ Postgres de teste (compose + CI) · M1 ✅ `schema_pg.sql` + testes parametrizados (197 verdes no PG, 52 na lista da M2) · M2 ✅ SQL cru e casts (PG 249 verdes, CI bloqueante nos dois bancos) · M3 ✅ migrações fora da partida (`python -m salim.migrate [--seed]`, lock consultivo, 1 transação por arquivo; PG 256 verdes) · M4 ✅ estado do bot em tabelas `bot_pending`/`bot_seen` (PG 264 verdes) · M5 ✅ trava de login em tabela `login_throttle` (PG 268 verdes) · M6 ✅ fuso America/Sao_Paulo (`salim.clock.today`, PG 274 verdes) · M7 ✅ engine serverless (NullPool, SSL, retry de cold start, `DATABASE_URL`; falta só a conexão com o Neon real) · M8 🟡 deploy Vercel + webhook Telegram (código pronto: `api/index.py`, `vercel.json`; falta Neon + variáveis + deploy + `setWebhook`) · M9 backup `pg_dump` no GitHub Actions + restauração · M10 corte (remove SQLite)

## Situação (20/11/2026)
E0–E9 e E12 implementados, em produção na Vercel + Neon (telas de DRE, caixa, a pagar e a receber): 325 testes verdes no Postgres e no SQLite, com `-W error`. Falta antes de uso com dinheiro real: `docker build` rodado fora deste ambiente, restauração de backup testada no servidor, backup copiado para fora do servidor, versionamento de schema (Alembic), WhatsApp/Telegram testados contra as APIs reais, tela de importação, MCP por HTTP (hoje só stdio).

## Riscos conhecidos
- Migrações: schema nasce do `schema.sql`; antes de dados reais entra Alembic ou versionamento de schema.
- Soma do lançamento = 0 é validada no serviço, não no banco (SQLite sem constraint diferida).
- Aging histórico ("como estava em outubro") precisa filtrar por `event_date`.
- Ordenação de códigos de conta é lexicográfica; o plano padrão usa 2 dígitos por nível.
