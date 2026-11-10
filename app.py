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
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise RuntimeError(
        'Defina a variável de ambiente FLASK_SECRET_KEY antes de iniciar o app.'
    )
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_HTTPS_ONLY') == '1'
DB_FILE = 'programacao.db'


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = get_db_connection()
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
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
        ''')

        columns = {
            row['name'] for row in conn.execute('PRAGMA table_info(programacao)')
        }

        if columns == {'id', 'titulo', 'descricao'}:
            conn.execute('ALTER TABLE programacao RENAME TO programacao_legacy')
            conn.execute('''
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
            ''')
            conn.execute('''
                INSERT INTO programacao (id, nome, matricula, escritorio, data_trabalho, atividade)
                SELECT id, titulo, 0, '', descricao, '' FROM programacao_legacy
            ''')
            conn.execute('DROP TABLE programacao_legacy')
            columns = {
                row['name'] for row in conn.execute('PRAGMA table_info(programacao)')
            }

        missing_columns = {
            'matricula': "INTEGER NOT NULL DEFAULT 0",
            'escritorio': "TEXT NOT NULL DEFAULT ''",
            'status': "TEXT DEFAULT 'Planejado'",
            'data_criacao': 'TIMESTAMP',
            'usuario_id': 'INTEGER REFERENCES usuarios(id)',
        }
        for column, definition in missing_columns.items():
            if column not in columns:
                conn.execute(
                    f'ALTER TABLE programacao ADD COLUMN {column} {definition}'
                )

        conn.execute(
            'UPDATE programacao SET data_criacao = CURRENT_TIMESTAMP '
            'WHERE data_criacao IS NULL'
        )
        user_columns = {
            row['name'] for row in conn.execute('PRAGMA table_info(usuarios)')
        }
        if 'role' not in user_columns:
            conn.execute(
                "ALTER TABLE usuarios ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
            )

        admin_username = os.environ.get('FLASK_ADMIN_USERNAME', '').strip().lower()
        if admin_username:
            conn.execute(
                "UPDATE usuarios SET role = 'admin' WHERE username = ?",
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
            g.user = conn.execute(
                'SELECT id, username, role FROM usuarios WHERE id = ?', (user_id,)
            ).fetchone()
        finally:
            conn.close()


def get_owned_programacao(conn, programacao_id):
    if g.user['role'] == 'admin':
        programacao = conn.execute(
            'SELECT * FROM programacao WHERE id = ?', (programacao_id,)
        ).fetchone()
    else:
        programacao = conn.execute(
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
                cursor = conn.execute(
                    'INSERT INTO usuarios (username, password_hash) VALUES (?, ?)',
                    (username, generate_password_hash(password)),
                )
                conn.commit()
                session.clear()
                session['user_id'] = cursor.lastrowid
                csrf_token()
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                error = 'Esse nome de usuário já está em uso.'
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
            user = conn.execute(
                'SELECT * FROM usuarios WHERE username = ?', (username,)
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
        programacoes = conn.execute(
            f'SELECT * FROM programacao {where_clause} ORDER BY data_trabalho, id',
            values,
        ).fetchall()
        escritorios = conn.execute(
            "SELECT DISTINCT escritorio FROM programacao "
            "WHERE escritorio != '' ORDER BY escritorio"
        ).fetchall()
        statuses = conn.execute(
            "SELECT DISTINCT status FROM programacao "
            "WHERE status IS NOT NULL AND status != '' ORDER BY status"
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
        conn.execute(
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
            conn.execute(
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
        conn.execute(
            "DELETE FROM programacao WHERE id = ? AND (? = 'admin' OR usuario_id = ?)",
            (id, g.user['role'], g.user['id']),
        )
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
