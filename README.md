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
