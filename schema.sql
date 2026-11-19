CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nome_completo TEXT NOT NULL,
    matricula TEXT NOT NULL,
    escritorio TEXT NOT NULL,
    tipo_vinculo TEXT NOT NULL CHECK (tipo_vinculo IN ('Efetivo', 'Bolsista', 'Cedido')),
    email TEXT NOT NULL UNIQUE,
    password_reset_token_hash TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email_lower
    ON usuarios (lower(email)) WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS programacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    matricula TEXT NOT NULL,
    escritorio TEXT NOT NULL,
    data_trabalho DATE NOT NULL,
    atividade TEXT NOT NULL,
    local_atividade TEXT NOT NULL DEFAULT '',
    tipo_atividade TEXT NOT NULL DEFAULT 'Escritório',
    status TEXT DEFAULT 'Planejado',
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    usuario_id INTEGER REFERENCES usuarios(id)
)
