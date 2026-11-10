import hmac
import os
import secrets
import sqlite3
from datetime import date
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
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
                    matricula INTEGER NOT NULL,
                    escritorio TEXT NOT NULL,
                    data_trabalho DATE NOT NULL,
                    atividade TEXT NOT NULL,
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
                        matricula INTEGER NOT NULL,
                        escritorio TEXT NOT NULL,
                        data_trabalho DATE NOT NULL,
                        atividade TEXT NOT NULL,
                        status TEXT DEFAULT 'Planejado',
                        data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        usuario_id INTEGER REFERENCES usuarios(id)
                    )
                    '''
                )
                execute_query(
                    conn,
                    '''
                    INSERT INTO programacao (id, nome, matricula, escritorio, data_trabalho, atividade, status, data_criacao, usuario_id)
                    SELECT id, titulo, 0, '', descricao, '', 'Planejado', CURRENT_TIMESTAMP, NULL FROM programacao_legacy
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
                'matricula': "INTEGER NOT NULL DEFAULT 0",
                'escritorio': "TEXT NOT NULL DEFAULT ''",
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
        else:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
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
                    matricula INTEGER NOT NULL,
                    escritorio TEXT NOT NULL,
                    data_trabalho DATE NOT NULL,
                    atividade TEXT NOT NULL,
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
                        matricula INTEGER NOT NULL,
                        escritorio TEXT NOT NULL,
                        data_trabalho DATE NOT NULL,
                        atividade TEXT NOT NULL,
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
                        atividade, status, data_criacao, usuario_id
                    )
                    SELECT id, titulo, 0, '', descricao, '', 'Planejado', CURRENT_TIMESTAMP, NULL
                    FROM programacao_legacy
                    '''
                )
                conn.execute('DROP TABLE programacao_legacy')
                programacao_columns = [
                    row['name'] for row in conn.execute('PRAGMA table_info(programacao)').fetchall()
                ]

            missing_columns = {
                'matricula': "INTEGER NOT NULL DEFAULT 0",
                'escritorio': "TEXT NOT NULL DEFAULT ''",
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

        admin_username = os.environ.get('FLASK_ADMIN_USERNAME', '').strip().lower()
        if admin_username:
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
                'SELECT id, username, role FROM usuarios WHERE id = ?',
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


init_db()


@app.route('/register', methods=('GET', 'POST'))
def register():
    if g.user is not None:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        error = None
        if not 3 <= len(username) <= 50:
            error = 'O usuário deve ter entre 3 e 50 caracteres.'
        elif not 12 <= len(password) <= 128:
            error = 'A senha deve ter entre 12 e 128 caracteres.'

        if error is None:
            conn = get_db_connection()
            try:
                if is_postgres_db():
                    cursor = execute_query(
                        conn,
                        'INSERT INTO usuarios (username, password_hash) VALUES (?, ?) RETURNING id',
                        (username, generate_password_hash(password)),
                    )
                    user_id = cursor.fetchone()['id']
                else:
                    cursor = execute_query(
                        conn,
                        'INSERT INTO usuarios (username, password_hash) VALUES (?, ?)',
                        (username, generate_password_hash(password)),
                    )
                    user_id = cursor.lastrowid
                conn.commit()
                session.clear()
                session['user_id'] = user_id
                csrf_token()
                return redirect(url_for('index'))
            except Exception as exc:
                if isinstance(exc, sqlite3.IntegrityError):
                    error = 'Esse nome de usuário já está em uso.'
                elif is_postgres_db():
                    import psycopg2
                    if isinstance(exc, psycopg2.IntegrityError):
                        error = 'Esse nome de usuário já está em uso.'
                    else:
                        raise
                else:
                    raise
            finally:
                conn.close()

        flash(error)

    return render_template('register.html')


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


@app.route('/')
@login_required
def index():
    search = request.args.get('q', '').strip()[:100]
    escritorio_filter = request.args.get('escritorio', '').strip()
    status_filter = request.args.get('status', '').strip()
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

    valid_date_from = valid_date_to = True
    for date_value in (date_from, date_to):
        if date_value:
            try:
                date.fromisoformat(date_value)
            except ValueError:
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
            'data_inicio': date_from,
            'data_fim': date_to,
        },
        escritorios=escritorios,
        statuses=statuses,
    )


@app.route('/add', methods=('POST',))
@login_required
def add():
    conn = get_db_connection()
    try:
        execute_query(
            conn,
            '''
            INSERT INTO programacao (
                nome, matricula, escritorio, data_trabalho, atividade,
                data_criacao, usuario_id
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ''',
            (
                request.form['nome'],
                request.form['matricula'],
                request.form['escritorio'],
                request.form['data_trabalho'],
                request.form['atividade'],
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
            execute_query(
                conn,
                '''
                UPDATE programacao
                SET nome = ?, matricula = ?, escritorio = ?, data_trabalho = ?,
                    atividade = ?, status = ?
                WHERE id = ? AND (? = 'admin' OR usuario_id = ?)
                ''',
                (
                    request.form['nome'],
                    request.form['matricula'],
                    request.form['escritorio'],
                    request.form['data_trabalho'],
                    request.form['atividade'],
                    request.form['status'],
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
