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

- `app.py`: backend Flask
- `controle-internet.html`: interface compartilhada com foco no modulo passagens
- `project-config.json`: define a abertura direta no modulo `passagens`
- `passagens_import_seed.py`: apoio para carga inicial

## Como rodar

```bash
pip install -r requirements.txt
copy .env.example .env
python app.py
```
