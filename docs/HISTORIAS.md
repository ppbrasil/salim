# Salim — Histórias

Cada história: ≤2 arquivos de produção (+ teste). **B** = back, **F** = front. Detalhe fino das entregas futuras é refinado quando chegar a vez delas.

## E0 Fundação ✅ (0.1–0.3 verdes)
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 0.1 | Projeto instalável com pytest rodando | `pytest` coleta e passa um teste trivial | pyproject.toml |
| 0.2 | Endpoint de saúde | `GET /health` → 200 `{"status":"ok"}` | B app.py |
| 0.3 | Sessão de banco por teste (SQLite memória) | Fixture cria schema limpo a cada teste | B db.py |

## E1 Ledger ✅ (1.1–1.10 verdes)
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 1.1 | Criar conta | Cria e busca por código; código duplicado falha | B models.py, ledger.py |
| 1.2 | Hierarquia e conta-grupo | Filha aponta para pai; árvore listada em ordem | B ledger.py |
| 1.3 | Plano de contas padrão | Seed cria árvore base; rodar 2x não duplica | B chart.py |
| 1.4 | Lançar partida dobrada | 2+ partidas somando 0 gravam; retorna id | B models.py, ledger.py |
| 1.5 | Rejeitar lançamento inválido | Soma ≠ 0, <2 partidas ou valor 0 → erro; nada gravado | B ledger.py |
| 1.6 | Rejeitar conta inválida | Conta inexistente ou grupo → erro; nada gravado | B ledger.py |
| 1.7 | Competência por partida | Default = data do evento; pode ser diferente por partida | B ledger.py |
| 1.8 | Saldo de conta | Saldo natural até a data; grupo soma a subárvore | B ledger.py |
| 1.9 | Estorno | Lançamento nunca é editado; estorno zera o efeito | B ledger.py |
| 1.10 | Balancete | Soma de todos os saldos = 0 com N lançamentos aleatórios | B ledger.py |

## E2 Interface web
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 2.1 | API: listar plano de contas | `GET /accounts` devolve árvore | B app.py |
| 2.2 | API: criar lançamento | `POST /transactions` 201; soma ≠ 0 → 422 | B app.py |
| 2.3 | API: extrato e saldo da conta | `GET /accounts/{id}/statement` | B app.py |
| 2.4 | Tela do plano de contas com saldos | HTML contém contas e saldos | B app.py, F accounts.html |
| 2.5 | Tela de novo lançamento | Formulário posta e redireciona; erro mostra mensagem | B app.py, F transaction_form.html |
| 2.6 | Tela de extrato | Lista lançamentos com competência | B app.py, F statement.html |
| 2.7 | Atalhos: despesa simples e transferência | Formulário de 1 linha gera as 2 partidas | B ledger.py, F transaction_form.html |

## E3 Faturas
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 3.1 | Fonte de fatura (cartão/guia) com dia de fechamento e vencimento | Cria fonte e primeira fatura aberta | B models.py, invoices.py |
| 3.2 | Compra cai na fatura certa pela data | Antes/depois do fechamento → faturas diferentes | B invoices.py |
| 3.3 | Fechar fatura | Status closed, saldo congelado, próxima aberta | B invoices.py |
| 3.4 | Liquidar fatura | Pagamento zera saldo, status paid | B invoices.py |
| 3.5 | Pagamento parcial | Saldo residual; status continua closed | B invoices.py |
| 3.6 | Tela de faturas | Lista abertas/fechadas, valor, vencimento | B app.py, F invoices.html |

## E4 Obrigações e parcelas
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 4.1 | Cronograma de parcelas | Soma das parcelas = valor da obrigação | B models.py, obligations.py |
| 4.2 | Compra parcelada com vencimentos ≠ evento | N parcelas com datas próprias | B obligations.py |
| 4.3 | Pagar parcela | Parcela paga; saldo da obrigação cai | B obligations.py |
| 4.4 | Consolidar obrigações | N obrigações → 1 nova; competências preservadas | B obligations.py |
| 4.5 | Parcelar fatura | Fatura fechada vira N parcelas | B obligations.py |
| 4.6 | Pagamento com várias competências | Um pagamento liquida várias partidas de competências diferentes | B obligations.py |
| 4.7 | Tela de a pagar | Parcelas por vencimento | B app.py, F payables.html |

## E5 Orçamento
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 5.1 | Mês padrão: valor mensal por conta de despesa | Grava e lê | B models.py, budget.py |
| 5.2 | Realizado por competência no mês | Soma de partidas da conta no mês | B budget.py |
| 5.3 | Orçado × realizado | Retorna restante e % | B budget.py |
| 5.4 | Perfil de gasto (pontual no dia X vs diluído) | Esperado até hoje muda conforme perfil | B budget.py |
| 5.5 | Alerta simples de estouro | Passou do esperado até hoje → alerta | B budget.py |
| 5.6 | Meta semanal | Orçamento semanal derivado do mensal | B budget.py |
| 5.7 | Tela de orçamento | Barras orçado × realizado | B app.py, F budget.html |

## E6 API de consulta + MCP
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 6.1 | Camada de consulta única (saldo, extrato, orçamento, faturas) | Funções puras sobre o ledger | B queries.py |
| 6.2 | Servidor MCP com `get_balance` | Cliente MCP de teste chama e recebe saldo | B mcp_server.py |
| 6.3 | `get_statement` | idem | B mcp_server.py |
| 6.4 | `get_budget_status` | idem | B mcp_server.py |
| 6.5 | `get_upcoming_payables` | idem | B mcp_server.py |
| 6.6 | `propose_transaction` (não grava) | Devolve proposta validada | B mcp_server.py |
| 6.7 | `confirm_transaction` | Grava proposta confirmada | B mcp_server.py |

## E7 Telegram
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 7.1 | Webhook recebe update e responde `/saldo` | Update simulado → resposta com saldo | B telegram.py |
| 7.2 | Lista de usuários autorizados | Não autorizado é ignorado | B telegram.py |
| 7.3 | `/orcamento` e `/faturas` | Respostas formatadas | B telegram.py |
| 7.4 | Lançamento por comando com confirmação | Proposta → "ok" → grava | B telegram.py |
| 7.5 | Resumo diário agendado | Mensagem enviada no horário | B telegram.py, scheduler.py |

## E8 IA no lançamento
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 8.1 | Texto livre → proposta de lançamento | Casos fixos ("mercado 230 no nubank") | B nlp.py |
| 8.2 | Classificação de conta por histórico | Sugere conta mais usada para o mesmo favorecido | B nlp.py |
| 8.3 | Perguntas livres via MCP | Pergunta → ferramenta correta | B nlp.py |

## E9 Open Finance
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 9.1 | Importar extrato (CSV/OFX) para fila | Itens pendentes | B imports.py |
| 9.2 | Casar item com lançamento existente | Match por valor/data | B imports.py |
| 9.3 | Criar lançamento a partir do item | Item vira lançamento | B imports.py |
| 9.4 | Conector Open Finance | Contrato definido; implementação por provedor | B openfinance.py |

## E10 WhatsApp
| ID | História | Teste de aceite | Arquivos |
|----|----------|-----------------|----------|
| 10.1 | Interface de canal comum | Telegram e WhatsApp implementam o mesmo contrato | B channels.py |
| 10.2 | Adaptador WhatsApp | Mesmos testes do Telegram passam | B whatsapp.py |

## Riscos conhecidos / histórias a inserir
- **Migrações**: hoje o schema nasce por `create_all`. Antes de usar com dados reais (E2), inserir história de Alembic (B alembic/env.py + 1ª migração).
- **Ordenação de código de conta** é lexicográfica ("1.10" < "1.2"). O plano padrão usa 2 dígitos por nível (ok); inserir história de ordenação natural antes da UI de criação livre de contas (E2).
- **Imutabilidade** é garantida na camada ORM (eventos SQLAlchemy). Falta trigger no banco para bloquear SQL direto (história pós-E2).
- **Concorrência**: SQLite com 1 escritor basta para uma família; revisar ao ir para Postgres.
