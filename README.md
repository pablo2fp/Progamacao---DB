# Sistema de Programação Mensal

Uma aplicação web desenvolvida em Python com o microframework Flask para gerenciar a escala e as atividades mensais de técnicos em diversos escritórios. O sistema permite o cadastro de atividades, filtros avançados de busca e conta com um sistema de autenticação e permissões de usuários (Comum e Administrador).

## 🚀 Funcionalidades

Autenticação Segura: Registro e login de usuários com senhas criptografadas (hashes).

Controle de Acesso: Diferenciação entre usuários comuns (que podem editar/excluir apenas os próprios registros) e administradores (com controle total).

Gestão de Programação (CRUD): Adicionar, visualizar, editar e excluir agendamentos de técnicos, indicando se a atividade será em campo ou no escritório. A listagem também pode ser filtrada pelo tipo de atividade.

Planilha mensal: Administradores podem selecionar qualquer usuário, inclusive a própria conta, e um mês para baixar a programação em formato Excel.

Perfil do usuário: Cadastro de nome completo, matrícula da empresa, escritório e e-mail. Nome, matrícula e escritório são preenchidos automaticamente nas novas programações.

Recuperação de senha: Envio de link temporário para o e-mail cadastrado. A senha continua armazenada somente como hash e pode ser exibida temporariamente nos formulários de senha.

Filtros de Busca: Pesquisa por texto (nome, matrícula, atividade), por escritório, status da atividade e intervalo de datas.

Segurança Integrada: Proteção contra ataques CSRF nativa em todos os formulários.

## 🛠️ Tecnologias Utilizadas

Backend: Python 3.x, Flask

Banco de Dados: SQLite (padrão local)

Frontend: HTML5, CSS3, Jinja2 (Templates)

Segurança: Werkzeug (Hashes de senha), tokens CSRF customizados.

## ⚙️ Configuração e Execução Local

Siga os passos abaixo para rodar o projeto na sua máquina local:

### 1. Clone o repositório

``` text
git clone https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
cd SEU_REPOSITORIO
``` 


### 2. Crie um Ambiente Virtual (Recomendado)
``` text
python -m venv venv
```

#### No Windows:
``` text
venv\Scripts\activate
```

#### No Linux/Mac:
```text
source venv/bin/activate
```


### 3. Instale as Dependências

Instale todas as dependências do projeto:
```text
pip install -r requirements.txt
```

### 4. Configure as Variáveis de Ambiente

Crie um arquivo .env na raiz do projeto (ou exporte no seu terminal) com as seguintes variáveis obrigatórias:

#### Chave secreta para sessões e CSRF (OBRIGATÓRIO)
FLASK_SECRET_KEY=uma_chave_muito_segura_e_aleatoria_aqui

#### Ativa o modo de desenvolvimento local (0 = Produção, 1 = Desenvolvimento)
FLASK_DEBUG=1

#### Configura cookies seguros para HTTPS (0 = HTTP, 1 = HTTPS)
FLASK_HTTPS_ONLY=0

#### Define o nome de um usuário administrador padrão (Opcional)
FLASK_ADMIN_USERNAME=admin


🚨 IMPORTANTE: Nunca faça o commit do seu arquivo .env ou do banco de dados programacao.db para o GitHub. Certifique-se de que eles estejam listados no seu arquivo .gitignore.

### Configuração de e-mail para recuperação de senha

Para habilitar o envio dos links de redefinição, configure também as variáveis SMTP:

```text
SMTP_HOST=smtp.seuprovedor.com
SMTP_PORT=587
SMTP_USERNAME=usuario-smtp
SMTP_PASSWORD=senha-smtp
SMTP_FROM=Sistema de Programação <nao-responda@seu-dominio.com>
SMTP_USE_TLS=1
```

O link é válido por uma hora e pode ser usado uma única vez. Sem `SMTP_HOST` e `SMTP_FROM`, a recuperação não poderá enviar mensagens.

### 5. Inicie a Aplicação
```text
python app.py
```
#### Acesse:
```text
http://localhost:5000 no seu navegador.
```
O banco de dados SQLite (programacao.db) será inicializado automaticamente na primeira execução.

## ☁️ Deploy em Nuvem (Produção)

O projeto agora aceita PostgreSQL em produção e continua funcionando com SQLite em desenvolvimento local. O comportamento é automático:

- Se `DATABASE_URL` estiver definido e não começar com `sqlite`, o app usa PostgreSQL.
- Se `DATABASE_URL` não estiver definido, o app usa o arquivo local `programacao.db`.

### Variáveis obrigatórias em produção

```text
FLASK_SECRET_KEY=sua_chave_super_segura
FLASK_DEBUG=0
FLASK_HTTPS_ONLY=1
DATABASE_URL=postgresql://usuario:senha@host:5432/nome_do_banco
FLASK_ADMIN_USERNAME=admin
```

### Executando com Gunicorn

Em ambiente cloud, o ideal é utilizar Gunicorn:

```bash
gunicorn --bind 0.0.0.0:$PORT app:app
```

### Boas práticas

- Use PostgreSQL gerenciado em produção para garantir persistência.
- Nunca deixe `FLASK_DEBUG=1` em produção.
- Configure a aplicação por trás de HTTPS e mantenha a `FLASK_SECRET_KEY` fora do controle de versão.
- Em serviços com proxy/reverse proxy, o app já usa `ProxyFix` para tratar corretamente os headers de HTTPS.

### Observação importante

O SQLite é adequado para desenvolvimento local, mas não é recomendado como banco primário em produção em nuvem, pois arquivos locais podem ser apagados ou reinicializados entre deploys.
