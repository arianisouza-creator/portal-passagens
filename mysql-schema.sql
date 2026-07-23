-- Schema MySQL do Portal-MSE (migrado do Supabase/PostgreSQL).
-- Compatível com MySQL 8.x e MariaDB 10.4+.
-- Banco de destino padrão: controle_internet_prod
--
-- Como aplicar (linha de comando):
--   mysql -h dbsubdominios.portalmse.com.br -u controle_internet_prod -p controle_internet_prod < mysql-schema.sql
--
-- Observações:
--   - Os IDs continuam sendo gerados pela aplicação (Date.now()+random), por isso
--     as PKs BIGINT NÃO usam AUTO_INCREMENT.
--   - As antigas policies de RLS do Supabase (anon) não existem no MySQL; a
--     segurança passa a ser feita pelo backend Flask + privilégios do usuário MySQL.

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE IF NOT EXISTS internet_contracts (
  id BIGINT NOT NULL,
  empresa VARCHAR(255) NOT NULL DEFAULT '',
  obra VARCHAR(255) NOT NULL DEFAULT '',
  vencimento VARCHAR(64) NOT NULL DEFAULT '',
  numero_contrato VARCHAR(255) NOT NULL DEFAULT '',
  status_contrato VARCHAR(64) NOT NULL DEFAULT 'Ativo',
  inicio_contrato VARCHAR(16) NOT NULL,
  fim_contrato VARCHAR(16) NOT NULL DEFAULT '',
  contato VARCHAR(255) NOT NULL DEFAULT '',
  obs_contrato TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS internet_month_entries (
  month_key VARCHAR(16) NOT NULL,
  contract_id BIGINT NOT NULL,
  status VARCHAR(64) NOT NULL DEFAULT 'Ativo',
  valor DECIMAL(15,2) NULL,
  pedido VARCHAR(255) NOT NULL DEFAULT '',
  aprovado TINYINT(1) NULL,
  s1 TINYINT(1) NULL,
  login_acesso VARCHAR(255) NOT NULL DEFAULT '',
  senha_acesso VARCHAR(255) NOT NULL DEFAULT '',
  obs TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (month_key, contract_id),
  KEY idx_ime_contract (contract_id),
  CONSTRAINT fk_ime_contract FOREIGN KEY (contract_id)
    REFERENCES internet_contracts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS internet_lines (
  id BIGINT NOT NULL,
  month_key VARCHAR(16) NOT NULL,
  numero VARCHAR(255) NOT NULL DEFAULT '',
  responsavel VARCHAR(255) NOT NULL DEFAULT '',
  status VARCHAR(64) NOT NULL DEFAULT 'Ativo',
  centro_custo VARCHAR(255) NOT NULL DEFAULT '',
  percentual VARCHAR(32) NOT NULL DEFAULT '',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_lines_month (month_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS diarista_cadastros (
  id BIGINT NOT NULL,
  obra_diarista VARCHAR(255) NOT NULL DEFAULT '',
  nome_diarista VARCHAR(255) NOT NULL DEFAULT '',
  status_diarista VARCHAR(64) NOT NULL DEFAULT 'Ativo',
  inicio_diarista VARCHAR(16) NOT NULL,
  fim_diarista VARCHAR(16) NOT NULL DEFAULT '',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS diarista_month_entries (
  month_key VARCHAR(16) NOT NULL,
  diarista_id BIGINT NOT NULL,
  pedido VARCHAR(255) NOT NULL DEFAULT '',
  valor DECIMAL(15,2) NULL,
  protocolado VARCHAR(64) NOT NULL DEFAULT '',
  link TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (month_key, diarista_id),
  KEY idx_dme_diarista (diarista_id),
  CONSTRAINT fk_dme_diarista FOREIGN KEY (diarista_id)
    REFERENCES diarista_cadastros (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hitachi_collaborators (
  id BIGINT NOT NULL,
  month_key VARCHAR(16) NOT NULL,
  empresa VARCHAR(255) NOT NULL DEFAULT 'MSE ENGENHARIA',
  colaborador VARCHAR(255) NOT NULL DEFAULT '',
  situacao VARCHAR(64) NOT NULL DEFAULT 'Ativo',
  holerite VARCHAR(64) NOT NULL DEFAULT 'OK',
  comprovante_pagamento VARCHAR(64) NOT NULL DEFAULT 'OK',
  comprovante_adiantamento VARCHAR(64) NOT NULL DEFAULT 'OK',
  kit_rescisao VARCHAR(64) NOT NULL DEFAULT 'N/A',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_hc_month (month_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hitachi_company_docs (
  id BIGINT NOT NULL,
  month_key VARCHAR(16) NOT NULL,
  empresa VARCHAR(255) NOT NULL DEFAULT 'MSE ENGENHARIA',
  documento VARCHAR(255) NOT NULL DEFAULT '',
  status VARCHAR(64) NOT NULL DEFAULT 'OK',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_hcd_month (month_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS passagens_rows (
  `key` VARCHAR(191) NOT NULL,
  tabela VARCHAR(64) NOT NULL DEFAULT 'passagens',
  item JSON NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS passagens_complements (
  `key` VARCHAR(191) NOT NULL,
  `data` JSON NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS passagens_creditos (
  id VARCHAR(191) NOT NULL,
  `data` JSON NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
