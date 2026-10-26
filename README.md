# Portal Passagens

Projeto dedicado ao modulo de `Controle de Passagens`.

## Escopo

Este projeto publica somente o modulo de passagens, com:

- visao geral mensal
- detalhamento aereo e rodoviario
- cadastro manual
- creditos
- sincronizacao com API de passagens

## Arquitetura

- `app.py`: backend Flask com API REST + conexao MySQL (pymysql)
- `controle-internet.html`: interface SPA com foco no modulo passagens
- `project-config.json`: define a abertura direta no modulo `passagens`
- `mysql-schema.sql`: schema do banco MySQL
- `passagens_import_seed.py`: apoio para carga inicial
- `webhook.py`: listener de webhook do GitHub para auto-deploy
- `deploy.sh`: script de deploy automatico (systemd)

## Banco de dados

MySQL no host `dbsubdominios.portalmse.com.br:3306`, banco `controle_internet`.
Credenciais em `.env` (nunca versionar).

## Como rodar (local)

```bash
pip install -r requirements.txt
copy .env.example .env
python app.py
```

## Deploy AWS (producao)

O servidor roda com gunicorn + systemd + Nginx:

```bash
gunicorn app:app -b 127.0.0.1:8000 --workers 2 --threads 2
```

Servicos systemd: `portal-mse.service` (app) e `portal-mse-webhook.service` (auto-deploy).

## Aba Cotacao (busca de voos)

Aba "Cotacao" ao lado de "Pontos" no modulo Passagens. Codigo em `cotacao/` (Flask Blueprint, rotas em `/cotacao`).

- Busca voos no Google Flights via SerpApi e mostra so o preco cobrado pela propria companhia.
- Se a pessoa nao escolher o menor preco, a justificativa e obrigatoria (conferido tambem no servidor).
- "Solicitacoes feitas" mostra o que foi escolhido, o menor preco, a justificativa e o status.
- Usa o mesmo MySQL; as tabelas `cotacao_buscas` e `cotacao_solicitacoes` sao criadas sozinhas.
- `.env`: `SERPAPI_KEY` (sem chave abre em modo exemplo, com dados ficticios), `OPCOES_COMPANHIA`, `COTACAO_ADMIN_PASSWORD` (opcional).
- Cada conferencia de preco na companhia gasta 1 credito do SerpApi; buscas iguais em 30 min reaproveitam o resultado.
