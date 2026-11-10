Sistema de Programação Mensal

Uma aplicação web desenvolvida em Python com o microframework Flask para gerenciar a escala e as atividades mensais de técnicos em diversos escritórios. O sistema permite o cadastro de atividades, filtros avançados de busca e conta com um sistema de autenticação e permissões de usuários (Comum e Administrador).

🚀 Funcionalidades

Autenticação Segura: Registro e login de usuários com senhas criptografadas (hashes).

Controle de Acesso: Diferenciação entre usuários comuns (que podem editar/excluir apenas os próprios registros) e administradores (com controle total).

Gestão de Programação (CRUD): Adicionar, visualizar, editar e excluir agendamentos de técnicos.

Filtros de Busca: Pesquisa por texto (nome, matrícula, atividade), por escritório, status da atividade e intervalo de datas.

Segurança Integrada: Proteção contra ataques CSRF nativa em todos os formulários.

🛠️ Tecnologias Utilizadas

Backend: Python 3.x, Flask

Banco de Dados: SQLite (padrão local)

Frontend: HTML5, CSS3, Jinja2 (Templates)

Segurança: Werkzeug (Hashes de senha), tokens CSRF customizados.

⚙️ Configuração e Execução Local

Siga os passos abaixo para rodar o projeto na sua máquina local:

1. Clone o repositório

git clone https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
cd SEU_REPOSITORIO


2. Crie um Ambiente Virtual (Recomendado)

python -m venv venv
# No Windows:
venv\Scripts\activate
# No Linux/Mac:
source venv/bin/activate


3. Instale as Dependências

Como o projeto utiliza Flask, instale-o via pip:

pip install Flask Werkzeug


(Dica: Considere criar um arquivo requirements.txt com o comando pip freeze > requirements.txt)

4. Configure as Variáveis de Ambiente

Crie um arquivo .env na raiz do projeto (ou exporte no seu terminal) com as seguintes variáveis obrigatórias:

# Chave secreta para sessões e CSRF (OBRIGATÓRIO)
FLASK_SECRET_KEY=uma_chave_muito_segura_e_aleatoria_aqui

# Ativa o modo de desenvolvimento local (0 = Produção, 1 = Desenvolvimento)
FLASK_DEBUG=1

# Configura cookies seguros para HTTPS (0 = HTTP, 1 = HTTPS)
FLASK_HTTPS_ONLY=0

# Define o nome de um usuário administrador padrão (Opcional)
FLASK_ADMIN_USERNAME=admin


🚨 IMPORTANTE: Nunca faça o commit do seu arquivo .env ou do banco de dados programacao.db para o GitHub. Certifique-se de que eles estejam listados no seu arquivo .gitignore.

5. Inicie a Aplicação

python app.py


Acesse http://localhost:5000 no seu navegador. O banco de dados SQLite (programacao.db) será inicializado automaticamente na primeira execução.

☁️ Recomendações para Deploy em Nuvem (Produção)

Se você planeja hospedar este projeto em plataformas como Render, Heroku, AWS ou Google Cloud, preste atenção aos seguintes pontos críticos:

Banco de Dados: Sistemas de nuvem costumam usar sistemas de arquivos efêmeros. Isso significa que o SQLite (programacao.db) perderá todos os dados a cada reinício do servidor. É altamente recomendável migrar para um banco de dados externo como PostgreSQL ou MySQL em produção.

HTTPS: Em produção, certifique-se de acessar o site via HTTPS e defina a variável FLASK_HTTPS_ONLY=1 nas configurações da sua nuvem para garantir a segurança dos cookies de sessão.

Debug Mode: Nunca deixe FLASK_DEBUG=1 em produção, pois isso pode expor seu código-fonte e dados sensíveis a visitantes em caso de erro.
