import hmac
import hashlib
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
from datetime import date, datetime
from email.message import EmailMessage
from io import BytesIO
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from openpyxl import Workbook
from openpyxl.styles import Font
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
if os.environ.get('FLASK_ENV') == 'production' or os.environ.get('DATABASE_URL'):
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY')
    if not app.config['SECRET_KEY']:
        raise RuntimeError(
            'Defina a variável de ambiente FLASK_SECRET_KEY antes de iniciar o app em produção.'
        )
else:
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-me')

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_HTTPS_ONLY') == '1'
app.config['PREFERRED_URL_SCHEME'] = 'https' if app.config['SESSION_COOKIE_SECURE'] else 'http'
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'programacao.db')


def is_postgres_db():
    database_url = os.environ.get('DATABASE_URL', '').strip()
    return bool(database_url) and not database_url.startswith('sqlite')


def get_db_connection():
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if database_url and not database_url.startswith('sqlite'):
        import psycopg2
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
        return conn

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def execute_query(conn, query, params=None):
    if is_postgres_db():
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query.replace('?', '%s'), params or ())
        return cursor

    cursor = conn.cursor()
    cursor.execute(query, params or ())
    return cursor


def init_db():
    conn = get_db_connection()
    try:
        if is_postgres_db():
            execute_query(
                conn,
                '''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    nome_completo TEXT NOT NULL,
                    matricula TEXT NOT NULL,
                    escritorio TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_reset_token_hash TEXT,
                    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
                    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            execute_query(
                conn,
                '''
                CREATE TABLE IF NOT EXISTS programacao (
                    id SERIAL PRIMARY KEY,
                    nome TEXT NOT NULL,
                    matricula TEXT NOT NULL,
                    escritorio TEXT NOT NULL,
                    data_trabalho DATE NOT NULL,
                    atividade TEXT NOT NULL,
                    tipo_atividade TEXT NOT NULL DEFAULT 'Escritório',
                    status TEXT DEFAULT 'Planejado',
                    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    usuario_id INTEGER REFERENCES usuarios(id)
                )
                '''
            )
            columns = {
                row['column_name']
                for row in execute_query(
                    conn,
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = ?
                    """,
                    ('programacao',),
                ).fetchall()
            }
            if columns == {'id', 'titulo', 'descricao'}:
                execute_query(conn, 'ALTER TABLE programacao RENAME TO programacao_legacy')
                execute_query(
                    conn,
                    '''
                    CREATE TABLE programacao (
                        id SERIAL PRIMARY KEY,
                        nome TEXT NOT NULL,
                        matricula TEXT NOT NULL,
                        escritorio TEXT NOT NULL,
                        data_trabalho DATE NOT NULL,
                        atividade TEXT NOT NULL,
                        tipo_atividade TEXT NOT NULL DEFAULT 'Escritório',
                        status TEXT DEFAULT 'Planejado',
                        data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        usuario_id INTEGER REFERENCES usuarios(id)
                    )
                    '''
                )
                execute_query(
                    conn,
                    '''
                    INSERT INTO programacao (id, nome, matricula, escritorio, data_trabalho, atividade, tipo_atividade, status, data_criacao, usuario_id)
                    SELECT id, titulo, '0', '', descricao, '', 'Escritório', 'Planejado', CURRENT_TIMESTAMP, NULL FROM programacao_legacy
                    '''
                )
                execute_query(conn, 'DROP TABLE programacao_legacy')
                columns = {
                    row['column_name']
                    for row in execute_query(
                        conn,
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = ?
                        """,
                        ('programacao',),
                    ).fetchall()
                }

            missing_columns = {
                'matricula': "TEXT NOT NULL DEFAULT '0'",
                'escritorio': "TEXT NOT NULL DEFAULT ''",
                'tipo_atividade': "TEXT NOT NULL DEFAULT 'Escritório'",
                'status': "TEXT DEFAULT 'Planejado'",
                'data_criacao': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                'usuario_id': 'INTEGER REFERENCES usuarios(id)',
            }
            for column, definition in missing_columns.items():
                if column not in columns:
                    execute_query(
                        conn,
                        f'ALTER TABLE programacao ADD COLUMN {column} {definition}'
                    )

            matricula_type = execute_query(
                conn,
                """
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'programacao'
                  AND column_name = 'matricula'
                """,
            ).fetchone()['data_type']
            if matricula_type != 'text':
                execute_query(
                    conn,
                    'ALTER TABLE programacao ALTER COLUMN matricula TYPE TEXT USING matricula::text'
                )

            execute_query(
                conn,
                'UPDATE programacao SET data_criacao = CURRENT_TIMESTAMP WHERE data_criacao IS NULL'
            )
            user_columns = {
                row['column_name']
                for row in execute_query(
                    conn,
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = ?
                    """,
                    ('usuarios',),
                ).fetchall()
            }
            if 'role' not in user_columns:
                execute_query(
                    conn,
                    "ALTER TABLE usuarios ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
                )
            for column, definition in {
                'nome_completo': 'TEXT',
                'matricula': 'TEXT',
                'escritorio': 'TEXT',
                'email': 'TEXT',
                'password_reset_token_hash': 'TEXT',
            }.items():
                if column not in user_columns:
                    execute_query(
                        conn,
                        f'ALTER TABLE usuarios ADD COLUMN {column} {definition}'
                    )
            execute_query(
                conn,
                '''
                UPDATE usuarios
                SET escritorio = (
                    SELECT p.escritorio FROM programacao p
                    WHERE p.usuario_id = usuarios.id AND p.escritorio <> ''
                    ORDER BY p.data_criacao DESC, p.id DESC LIMIT 1
                )
                WHERE escritorio IS NULL OR escritorio = ''
                ''',
            )
            execute_query(
                conn,
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email_lower '
                'ON usuarios (lower(email)) WHERE email IS NOT NULL'
            )
        else:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    nome_completo TEXT NOT NULL,
                    matricula TEXT NOT NULL,
                    escritorio TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_reset_token_hash TEXT,
                    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
                    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS programacao (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    matricula TEXT NOT NULL,
                    escritorio TEXT NOT NULL,
                    data_trabalho DATE NOT NULL,
                    atividade TEXT NOT NULL,
                    tipo_atividade TEXT NOT NULL DEFAULT 'Escritório',
                    status TEXT DEFAULT 'Planejado',
                    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    usuario_id INTEGER REFERENCES usuarios(id)
                )
                '''
            )

            programacao_columns = [
                row['name'] for row in conn.execute('PRAGMA table_info(programacao)').fetchall()
            ]
            if programacao_columns and set(programacao_columns) == {'id', 'titulo', 'descricao'}:
                conn.execute('ALTER TABLE programacao RENAME TO programacao_legacy')
                conn.execute(
                    '''
                    CREATE TABLE programacao (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT NOT NULL,
                        matricula TEXT NOT NULL,
                        escritorio TEXT NOT NULL,
                        data_trabalho DATE NOT NULL,
                        atividade TEXT NOT NULL,
                        tipo_atividade TEXT NOT NULL DEFAULT 'Escritório',
                        status TEXT DEFAULT 'Planejado',
                        data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        usuario_id INTEGER REFERENCES usuarios(id)
                    )
                    '''
                )
                conn.execute(
                    '''
                    INSERT INTO programacao (
                        id, nome, matricula, escritorio, data_trabalho,
                        atividade, tipo_atividade, status, data_criacao, usuario_id
                    )
                    SELECT id, titulo, '0', '', descricao, '', 'Escritório', 'Planejado', CURRENT_TIMESTAMP, NULL
                    FROM programacao_legacy
                    '''
                )
                conn.execute('DROP TABLE programacao_legacy')
                programacao_columns = [
                    row['name'] for row in conn.execute('PRAGMA table_info(programacao)').fetchall()
                ]

            missing_columns = {
                'matricula': "TEXT NOT NULL DEFAULT '0'",
                'escritorio': "TEXT NOT NULL DEFAULT ''",
                'tipo_atividade': "TEXT NOT NULL DEFAULT 'Escritório'",
                'status': "TEXT DEFAULT 'Planejado'",
                'data_criacao': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                'usuario_id': 'INTEGER REFERENCES usuarios(id)',
            }
            for column, definition in missing_columns.items():
                if column not in programacao_columns:
                    conn.execute(
                        f'ALTER TABLE programacao ADD COLUMN {column} {definition}'
                    )

            conn.execute(
                'UPDATE programacao SET data_criacao = CURRENT_TIMESTAMP WHERE data_criacao IS NULL'
            )

            user_columns = [
                row['name'] for row in conn.execute('PRAGMA table_info(usuarios)').fetchall()
            ]
            if 'role' not in user_columns:
                conn.execute(
                    "ALTER TABLE usuarios ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
                )
            for column, definition in {
                'nome_completo': 'TEXT',
                'matricula': 'TEXT',
                'escritorio': 'TEXT',
                'email': 'TEXT',
                'password_reset_token_hash': 'TEXT',
            }.items():
                if column not in user_columns:
                    conn.execute(f'ALTER TABLE usuarios ADD COLUMN {column} {definition}')
            conn.execute(
                '''
                UPDATE usuarios
                SET escritorio = (
                    SELECT p.escritorio FROM programacao p
                    WHERE p.usuario_id = usuarios.id AND p.escritorio <> ''
                    ORDER BY p.data_criacao DESC, p.id DESC LIMIT 1
                )
                WHERE escritorio IS NULL OR escritorio = ''
                '''
            )
            conn.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email_lower '
                'ON usuarios (lower(email)) WHERE email IS NOT NULL'
            )

            programacao_info = {
                row['name']: row['type']
                for row in conn.execute('PRAGMA table_info(programacao)').fetchall()
            }
            if programacao_info.get('matricula', '').upper() != 'TEXT':
                conn.execute(
                    '''
                    CREATE TABLE programacao_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT NOT NULL,
                        matricula TEXT NOT NULL,
                        escritorio TEXT NOT NULL,
                        data_trabalho DATE NOT NULL,
                        atividade TEXT NOT NULL,
                        tipo_atividade TEXT NOT NULL DEFAULT 'Escritório',
                        status TEXT DEFAULT 'Planejado',
                        data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        usuario_id INTEGER REFERENCES usuarios(id)
                    )
                    '''
                )
                conn.execute(
                    '''
                    INSERT INTO programacao_new (
                        id, nome, matricula, escritorio, data_trabalho,
                        atividade, tipo_atividade, status, data_criacao, usuario_id
                    )
                    SELECT id, nome, CAST(matricula AS TEXT), escritorio, data_trabalho,
                           atividade, tipo_atividade, status, data_criacao, usuario_id
                    FROM programacao
                    '''
                )
                conn.execute('DROP TABLE programacao')
                conn.execute('ALTER TABLE programacao_new RENAME TO programacao')

        admin_usernames = os.environ.get('FLASK_ADMIN_USERNAME', '').strip().lower()
        if admin_usernames:
            # Divide os nomes por vírgula e remove espaços em branco
            lista_admins = [nome.strip() for nome in admin_usernames.split(',') if nome.strip()]
            for admin in lista_admins:
                execute_query(
                conn,
                "UPDATE usuarios SET role = 'admin' WHERE lower(username) = ?",
                (admin_username,),
            )
        conn.commit()
    finally:
        conn.close()


def csrf_token():
    token = session.get('_csrf_token')
    if token is None:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': csrf_token}


@app.before_request
def validate_csrf_token():
    if request.method == 'POST':
        submitted_token = request.form.get('_csrf_token', '')
        stored_token = session.get('_csrf_token', '')
        if not stored_token or not hmac.compare_digest(submitted_token, stored_token):
            abort(400, description='Token CSRF inválido ou ausente.')


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get('user_id') is None:
            return redirect(url_for('login'))
        return view(*args, **kwargs)

    return wrapped_view


@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        conn = get_db_connection()
        try:
            g.user = execute_query(
                conn,
                '''
                SELECT id, username, nome_completo, matricula, escritorio, email, role
                FROM usuarios WHERE id = ?
                ''',
                (user_id,),
            ).fetchone()
        finally:
            conn.close()


def get_owned_programacao(conn, programacao_id):
    if g.user['role'] == 'admin':
        programacao = execute_query(
            conn,
            'SELECT * FROM programacao WHERE id = ?',
            (programacao_id,),
        ).fetchone()
    else:
        programacao = execute_query(
            conn,
            'SELECT * FROM programacao WHERE id = ? AND usuario_id = ?',
            (programacao_id, g.user['id']),
        ).fetchone()
    if programacao is None:
        abort(404)
    return programacao


def parse_iso_date(value):
    try:
        parsed_date = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed_date if parsed_date.isoformat() == value else None


def password_reset_token(user_id):
    return URLSafeTimedSerializer(
        app.config['SECRET_KEY'],
        salt='password-reset',
    ).dumps(user_id)


def send_password_reset_email(email, reset_url):
    smtp_host = os.environ.get('SMTP_HOST', '').strip()
    sender = os.environ.get('SMTP_FROM', '').strip()
    if not smtp_host or not sender:
        raise RuntimeError('Configure SMTP_HOST e SMTP_FROM para habilitar a recuperação de senha.')

    message = EmailMessage()
    message['Subject'] = 'Recuperação de senha'
    message['From'] = sender
    message['To'] = email
    message.set_content(
        'Recebemos uma solicitação para redefinir sua senha. '
        f'Acesse o link abaixo em até uma hora:\n\n{reset_url}\n\n'
        'Se você não solicitou a redefinição, ignore esta mensagem.'
    )

    with smtplib.SMTP(
        smtp_host,
        int(os.environ.get('SMTP_PORT', '587')),
        timeout=10,
    ) as smtp:
        if os.environ.get('SMTP_USE_TLS', '1') == '1':
            smtp.starttls(context=ssl.create_default_context())
        smtp_username = os.environ.get('SMTP_USERNAME', '')
        if smtp_username:
            smtp.login(smtp_username, os.environ.get('SMTP_PASSWORD', ''))
        smtp.send_message(message)


init_db()


@app.route('/register', methods=('GET', 'POST'))
def register():
    if g.user is not None:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        nome_completo = ' '.join(request.form.get('nome_completo', '').split())
        matricula = request.form.get('matricula', '').strip()
        escritorio = request.form.get('escritorio', '').strip()
        email = request.form.get('email', '').strip().lower()
        error = None
        if not 3 <= len(username) <= 50:
            error = 'O usuário deve ter entre 3 e 50 caracteres.'
        elif not 3 <= len(nome_completo) <= 150:
            error = 'Informe seu nome completo (de 3 a 150 caracteres).'
        elif not 1 <= len(matricula) <= 30:
            error = 'A matrícula deve ter entre 1 e 30 caracteres.'
        elif not 1 <= len(escritorio) <= 100:
            error = 'Informe um escritório válido (até 100 caracteres).'
        elif len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            error = 'Informe um endereço de e-mail válido.'
        elif not 12 <= len(password) <= 128:
            error = 'A senha deve ter entre 12 e 128 caracteres.'

        if error is None:
            conn = get_db_connection()
            try:
                if is_postgres_db():
                    cursor = execute_query(
                        conn,
                        '''
                        INSERT INTO usuarios (username, password_hash, nome_completo, matricula, escritorio, email)
                        VALUES (?, ?, ?, ?, ?, ?) RETURNING id
                        ''',
                        (
                            username,
                            generate_password_hash(password),
                            nome_completo,
                            matricula,
                            escritorio,
                            email,
                        ),
                    )
                    user_id = cursor.fetchone()['id']
                else:
                    cursor = execute_query(
                        conn,
                        '''
                        INSERT INTO usuarios (username, password_hash, nome_completo, matricula, escritorio, email)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            username,
                            generate_password_hash(password),
                            nome_completo,
                            matricula,
                            escritorio,
                            email,
                        ),
                    )
                    user_id = cursor.lastrowid
                conn.commit()
                session.clear()
                session['user_id'] = user_id
                csrf_token()
                return redirect(url_for('index'))
            except Exception as exc:
                if isinstance(exc, sqlite3.IntegrityError):
                    error = 'Esse nome de usuário ou e-mail já está em uso.'
                elif is_postgres_db():
                    import psycopg2
                    if isinstance(exc, psycopg2.IntegrityError):
                        error = 'Esse nome de usuário ou e-mail já está em uso.'
                    else:
                        raise
                else:
                    raise
            finally:
                conn.close()

        flash(error)

    return render_template('register.html')


@app.route('/recuperar-senha', methods=('GET', 'POST'))
def recuperar_senha():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            flash('Informe um endereço de e-mail válido.')
            return render_template('recuperar_senha.html')

        conn = get_db_connection()
        try:
            user = execute_query(
                conn,
                'SELECT id FROM usuarios WHERE lower(email) = ?',
                (email,),
            ).fetchone()
            if user is not None:
                token = password_reset_token(user['id'])
                token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
                execute_query(
                    conn,
                    'UPDATE usuarios SET password_reset_token_hash = ? WHERE id = ?',
                    (token_hash, user['id']),
                )
                conn.commit()
        finally:
            conn.close()

        if user is not None:
            try:
                send_password_reset_email(
                    email,
                    url_for('redefinir_senha', token=token, _external=True),
                )
            except (OSError, RuntimeError, smtplib.SMTPException, ValueError):
                app.logger.exception('Falha ao enviar e-mail de recuperação de senha.')
                flash('Não foi possível enviar o e-mail de recuperação. Tente novamente mais tarde.')
                return render_template('recuperar_senha.html')

        flash('Se o e-mail estiver cadastrado, você receberá um link para redefinir a senha.')
        return redirect(url_for('login'))

    return render_template('recuperar_senha.html')


@app.route('/redefinir-senha/<token>', methods=('GET', 'POST'))
def redefinir_senha(token):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='password-reset')
    try:
        user_id = serializer.loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        flash('O link de recuperação é inválido ou expirou. Solicite um novo link.')
        return redirect(url_for('recuperar_senha'))

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    conn = get_db_connection()
    try:
        user = execute_query(
            conn,
            'SELECT id, password_reset_token_hash FROM usuarios WHERE id = ?',
            (user_id,),
        ).fetchone()
        if (
            user is None
            or not user['password_reset_token_hash']
            or not hmac.compare_digest(user['password_reset_token_hash'], token_hash)
        ):
            flash('O link de recuperação é inválido ou já foi utilizado. Solicite um novo link.')
            return redirect(url_for('recuperar_senha'))

        if request.method == 'POST':
            password = request.form.get('password', '')
            if not 12 <= len(password) <= 128:
                flash('A senha deve ter entre 12 e 128 caracteres.')
            else:
                cursor = execute_query(
                    conn,
                    '''
                    UPDATE usuarios
                    SET password_hash = ?, password_reset_token_hash = NULL
                    WHERE id = ? AND password_reset_token_hash = ?
                    ''',
                    (generate_password_hash(password), user_id, token_hash),
                )
                if cursor.rowcount != 1:
                    flash('O link de recuperação já foi utilizado. Solicite um novo link.')
                    return redirect(url_for('recuperar_senha'))
                conn.commit()
                flash('Sua senha foi redefinida. Entre com a nova senha.')
                return redirect(url_for('login'))
    finally:
        conn.close()

    return render_template('redefinir_senha.html')


@app.route('/login', methods=('GET', 'POST'))
def login():
    if g.user is not None:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        conn = get_db_connection()
        try:
            user = execute_query(
                conn,
                'SELECT * FROM usuarios WHERE username = ?',
                (username,),
            ).fetchone()
        finally:
            conn.close()

        if user is None or not check_password_hash(user['password_hash'], password):
            flash('Usuário ou senha incorretos.')
        else:
            session.clear()
            session['user_id'] = user['id']
            csrf_token()
            return redirect(url_for('index'))

    return render_template('login.html')


@app.route('/logout', methods=('POST',))
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/configuracao', methods=('GET', 'POST'))
@login_required
def configuracao():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        nome_completo = ' '.join(request.form.get('nome_completo', '').split())
        matricula = request.form.get('matricula', '').strip()
        escritorio = request.form.get('escritorio', '').strip()
        email = request.form.get('email', '').strip().lower()

        if not 3 <= len(username) <= 50:
            flash('O usuário deve ter entre 3 e 50 caracteres.')
        elif not 3 <= len(nome_completo) <= 150:
            flash('Informe seu nome completo (de 3 a 150 caracteres).')
        elif not 1 <= len(matricula) <= 30:
            flash('A matrícula deve ter entre 1 e 30 caracteres.')
        elif not 1 <= len(escritorio) <= 100:
            flash('Informe um escritório válido (até 100 caracteres).')
        elif len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            flash('Informe um endereço de e-mail válido.')
        else:
            conn = get_db_connection()
            try:
                execute_query(
                    conn,
                    '''
                    UPDATE usuarios
                    SET username = ?, nome_completo = ?, matricula = ?, escritorio = ?, email = ?
                    WHERE id = ?
                    ''',
                    (username, nome_completo, matricula, escritorio, email, g.user['id']),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                flash('Esse nome de usuário ou e-mail já está em uso.')
            except Exception as exc:
                if is_postgres_db():
                    import psycopg2
                    if isinstance(exc, psycopg2.IntegrityError):
                        conn.rollback()
                        flash('Esse nome de usuário ou e-mail já está em uso.')
                    else:
                        raise
                else:
                    raise
            else:
                flash('Dados da conta atualizados com sucesso.')
                return redirect(url_for('configuracao'))
            finally:
                conn.close()

    return render_template('configuracao.html', user=g.user)


@app.route('/configuracao/senha', methods=('POST',))
@login_required
def alterar_senha():
    current_password = request.form.get('senha_atual', '')
    new_password = request.form.get('nova_senha', '')
    confirm_password = request.form.get('confirmar_senha', '')
    conn = get_db_connection()
    try:
        user = execute_query(
            conn,
            'SELECT password_hash FROM usuarios WHERE id = ?',
            (g.user['id'],),
        ).fetchone()
        if user is None or not check_password_hash(user['password_hash'], current_password):
            flash('A senha atual está incorreta.')
            return redirect(url_for('configuracao'))
        if not 12 <= len(new_password) <= 128:
            flash('A nova senha deve ter entre 12 e 128 caracteres.')
            return redirect(url_for('configuracao'))
        if new_password != confirm_password:
            flash('A confirmação da nova senha não corresponde.')
            return redirect(url_for('configuracao'))

        execute_query(
            conn,
            '''
            UPDATE usuarios
            SET password_hash = ?, password_reset_token_hash = NULL
            WHERE id = ?
            ''',
            (generate_password_hash(new_password), g.user['id']),
        )
        conn.commit()
    finally:
        conn.close()

    session.clear()
    session['user_id'] = g.user['id']
    csrf_token()
    flash('Senha alterada com sucesso.')
    return redirect(url_for('configuracao'))


@app.route('/perfil/escritorio', methods=('POST',))
@login_required
def atualizar_escritorio():
    escritorio = request.form.get('escritorio', '').strip()
    if not 1 <= len(escritorio) <= 100:
        flash('Informe um escritório válido (até 100 caracteres).')
        return redirect(url_for('index'))

    conn = get_db_connection()
    try:
        execute_query(
            conn,
            'UPDATE usuarios SET escritorio = ? WHERE id = ?',
            (escritorio, g.user['id']),
        )
        conn.commit()
    finally:
        conn.close()
    flash('Escritório atualizado. Ele será preenchido automaticamente nas programações.')
    return redirect(url_for('index'))


@app.route('/')
@login_required
def index():
    search = request.args.get('q', '').strip()[:100]
    escritorio_filter = request.args.get('escritorio', '').strip()
    status_filter = request.args.get('status', '').strip()
    tipo_atividade_filter = request.args.get('tipo_atividade', '').strip()
    date_from = request.args.get('data_inicio', '').strip()
    date_to = request.args.get('data_fim', '').strip()
    filters = []
    values = []

    if search:
        escaped_search = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = f'%{escaped_search}%'
        filters.append(
            "(nome LIKE ? ESCAPE '\\' OR CAST(matricula AS TEXT) LIKE ? ESCAPE '\\' "
            "OR escritorio LIKE ? ESCAPE '\\' OR atividade LIKE ? ESCAPE '\\')"
        )
        values.extend([pattern] * 4)

    if escritorio_filter:
        filters.append('escritorio = ?')
        values.append(escritorio_filter)

    if status_filter:
        filters.append('status = ?')
        values.append(status_filter)

    if tipo_atividade_filter in ('Campo', 'Escritório'):
        filters.append('tipo_atividade = ?')
        values.append(tipo_atividade_filter)
    elif tipo_atividade_filter:
        flash('Selecione um tipo de atividade válido.')
        tipo_atividade_filter = ''

    valid_date_from = valid_date_to = True
    for date_value in (date_from, date_to):
        if date_value and parse_iso_date(date_value) is None:
            if date_value == date_from:
                valid_date_from = False
            if date_value == date_to:
                valid_date_to = False
    if not valid_date_from or not valid_date_to:
        flash('Informe as datas do filtro no formato válido.')
        date_from = date_from if valid_date_from else ''
        date_to = date_to if valid_date_to else ''
    if date_from and date_to and date_from > date_to:
        flash('A data inicial não pode ser posterior à data final.')
        date_from = date_to = ''

    if date_from:
        filters.append('data_trabalho >= ?')
        values.append(date_from)
    if date_to:
        filters.append('data_trabalho <= ?')
        values.append(date_to)

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ''
    conn = get_db_connection()
    try:
        programacoes = execute_query(
            conn,
            f'SELECT * FROM programacao {where_clause} ORDER BY data_trabalho, id',
            values,
        ).fetchall()
        escritorios = execute_query(
            conn,
            "SELECT DISTINCT escritorio FROM programacao "
            "WHERE escritorio != '' ORDER BY escritorio",
        ).fetchall()
        statuses = execute_query(
            conn,
            "SELECT DISTINCT status FROM programacao "
            "WHERE status IS NOT NULL AND status != '' ORDER BY status",
        ).fetchall()
        technicians = []
        if g.user['role'] == 'admin':
            technicians = execute_query(
                conn,
                '''
                SELECT id, COALESCE(NULLIF(nome_completo, ''), username) AS nome_completo,
                       matricula
                FROM usuarios u
                WHERE role IN ('user', 'admin')
                ORDER BY nome_completo, matricula
                ''',
            ).fetchall()
    finally:
        conn.close()
    return render_template(
        'index.html',
        programacoes=programacoes,
        user=g.user,
        filtros={
            'q': search,
            'escritorio': escritorio_filter,
            'status': status_filter,
            'tipo_atividade': tipo_atividade_filter,
            'data_inicio': date_from,
            'data_fim': date_to,
        },
        escritorios=escritorios,
        statuses=statuses,
        technicians=technicians,
        mes_atual=date.today().strftime('%Y-%m'),
    )


@app.route('/admin/planilha-mensal')
@login_required
def planilha_mensal():
    if g.user['role'] != 'admin':
        abort(403)

    technician_id = request.args.get('tecnico', type=int)
    month_value = request.args.get('mes', date.today().strftime('%Y-%m'))
    try:
        month_start = date.fromisoformat(f'{month_value}-01')
    except ValueError:
        abort(400, description='Informe o mês no formato AAAA-MM.')
    if len(month_value) != 7 or month_start.strftime('%Y-%m') != month_value:
        abort(400, description='Informe o mês no formato AAAA-MM.')
    if technician_id is None:
        abort(400, description='Selecione um técnico.')

    next_month = (
        date(month_start.year + 1, 1, 1)
        if month_start.month == 12
        else date(month_start.year, month_start.month + 1, 1)
    )
    conn = get_db_connection()
    try:
        technician = execute_query(
            conn,
            '''
            SELECT id, COALESCE(NULLIF(nome_completo, ''), username) AS nome_completo,
                   username, matricula
            FROM usuarios WHERE id = ? AND role IN ('user', 'admin')
            ''',
            (technician_id,),
        ).fetchone()
        if technician is None:
            abort(404)
        programacoes = execute_query(
            conn,
            '''
            SELECT data_trabalho, escritorio, nome, matricula, tipo_atividade,
                   atividade, status
            FROM programacao
            WHERE usuario_id = ? AND data_trabalho >= ? AND data_trabalho < ?
            ORDER BY data_trabalho, id
            ''',
            (technician_id, month_start.isoformat(), next_month.isoformat()),
        ).fetchall()
    finally:
        conn.close()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = f'Programação {month_value}'
    worksheet.append([
        'Data', 'Escritório', 'Nome do técnico', 'Matrícula',
        'Tipo de atividade', 'Atividade', 'Status',
    ])
    for cell in worksheet[1]:
        cell.font = Font(bold=True)

    for programacao in programacoes:
        raw_date = programacao['data_trabalho']
        work_date = (
            raw_date
            if isinstance(raw_date, (date, datetime))
            else date.fromisoformat(str(raw_date)[:10])
        )
        worksheet.append([
            work_date,
            programacao['escritorio'],
            programacao['nome'],
            programacao['matricula'],
            programacao['tipo_atividade'],
            programacao['atividade'],
            programacao['status'],
        ])
        worksheet.cell(worksheet.max_row, 1).number_format = 'dd/mm/yyyy'
        for cell in worksheet[worksheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = 's'

    worksheet.freeze_panes = 'A2'
    worksheet.auto_filter.ref = worksheet.dimensions
    for column, width in {'A': 14, 'B': 24, 'C': 30, 'D': 18, 'E': 22, 'F': 50, 'G': 18}.items():
        worksheet.column_dimensions[column].width = width

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f'programacao_{technician["username"]}_{month_value}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@app.route('/add', methods=('POST',))
@login_required
def add():
    tipo_atividade = request.form.get('tipo_atividade', '')
    if tipo_atividade not in ('Campo', 'Escritório'):
        abort(400, description='Selecione um tipo de atividade válido.')

    nome = g.user['nome_completo'] or request.form.get('nome', '').strip()
    matricula = g.user['matricula'] or request.form.get('matricula', '').strip()
    data_trabalho = request.form.get('data_trabalho', '').strip()
    atividade = request.form.get('atividade', '').strip()
    if not nome or len(nome) > 150 or not matricula or len(matricula) > 30:
        abort(400, description='Informe um nome e uma matrícula válidos.')
    escritorio = (g.user['escritorio'] or '').strip()
    if not escritorio or len(escritorio) > 100:
        flash('Cadastre seu escritório para continuar com a programação.')
        return redirect(url_for('index'))
    if parse_iso_date(data_trabalho) is None:
        abort(400, description='Informe uma data válida no formato AAAA-MM-DD.')
    if not atividade:
        abort(400, description='Informe a atividade.')

    conn = get_db_connection()
    try:
        execute_query(
            conn,
            '''
            INSERT INTO programacao (
                nome, matricula, escritorio, data_trabalho, atividade,
                tipo_atividade, data_criacao, usuario_id
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ''',
            (
                nome,
                matricula,
                escritorio,
                data_trabalho,
                atividade,
                tipo_atividade,
                g.user['id'],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for('index'))


@app.route('/edit/<int:id>', methods=('GET', 'POST'))
@login_required
def edit(id):
    conn = get_db_connection()
    try:
        programacao = get_owned_programacao(conn, id)
        if request.method == 'POST':
            tipo_atividade = request.form.get('tipo_atividade', '')
            if tipo_atividade not in ('Campo', 'Escritório'):
                abort(400, description='Selecione um tipo de atividade válido.')
            nome = request.form.get('nome', '').strip()
            matricula = request.form.get('matricula', '').strip()
            escritorio = request.form.get('escritorio', '').strip()
            data_trabalho = request.form.get('data_trabalho', '').strip()
            atividade = request.form.get('atividade', '').strip()
            status = request.form.get('status', '')
            if not nome or len(nome) > 150 or not matricula or len(matricula) > 30:
                abort(400, description='Informe um nome e uma matrícula válidos.')
            if not escritorio or len(escritorio) > 100:
                abort(400, description='Informe um escritório válido.')
            if parse_iso_date(data_trabalho) is None:
                abort(400, description='Informe uma data válida no formato AAAA-MM-DD.')
            if not atividade:
                abort(400, description='Informe a atividade.')
            if status not in ('Planejado', 'Em Andamento', 'Concluído'):
                abort(400, description='Selecione um status válido.')
            execute_query(
                conn,
                '''
                UPDATE programacao
                SET nome = ?, matricula = ?, escritorio = ?, data_trabalho = ?,
                    atividade = ?, tipo_atividade = ?, status = ?
                WHERE id = ? AND (? = 'admin' OR usuario_id = ?)
                ''',
                (
                    nome,
                    matricula,
                    escritorio,
                    data_trabalho,
                    atividade,
                    tipo_atividade,
                    status,
                    id,
                    g.user['role'],
                    g.user['id'],
                ),
            )
            conn.commit()
            return redirect(url_for('index'))
    finally:
        conn.close()
    return render_template('editar.html', programacao=programacao)


@app.route('/delete/<int:id>', methods=('POST',))
@login_required
def delete(id):
    conn = get_db_connection()
    try:
        get_owned_programacao(conn, id)
        execute_query(
            conn,
            "DELETE FROM programacao WHERE id = ? AND (? = 'admin' OR usuario_id = ?)",
            (id, g.user['role'], g.user['id']),
        )
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
