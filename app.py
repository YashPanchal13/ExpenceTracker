# Usrename : Yash13 | Password : P@ssword | Secuirty Que. Babu

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import datetime, date, timedelta
from functools import wraps
import calendar

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production-xyz123')

DB_PATH = os.environ.get('DB_PATH', 'expense_tracker.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('expense','income')),
            category TEXT,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS monthly_budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            opening_balance REAL DEFAULT 0,
            UNIQUE(user_id, year, month),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    ''')
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        username = request.form['username'].strip().lower()
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            flash('Passwords do not match', 'error')
            return render_template('register.html')
        conn = get_db()
        existing = conn.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if existing:
            flash('Username already taken', 'error')
            conn.close()
            return render_template('register.html')
        hashed = generate_password_hash(password)
        conn.execute('INSERT INTO users (name, username, password) VALUES (?,?,?)', (name, username, hashed))
        conn.commit()
        conn.close()
        flash('Account created! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    return render_template('dashboard.html', today=today.strftime('%Y-%m-%d'),
                           month=today.month, year=today.year)

@app.route('/api/dashboard-data')
@login_required
def dashboard_data():
    uid = session['user_id']
    today = date.today()
    year, month = today.year, today.month
    month_start = f"{year}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    month_end = f"{year}-{month:02d}-{last_day:02d}"

    conn = get_db()

    # Opening balance
    ob = conn.execute('SELECT opening_balance FROM monthly_budget WHERE user_id=? AND year=? AND month=?',
                      (uid, year, month)).fetchone()
    opening_balance = ob['opening_balance'] if ob else 0

    # This month totals
    rows = conn.execute('''SELECT type, SUM(amount) as total FROM transactions
        WHERE user_id=? AND date BETWEEN ? AND ? GROUP BY type''',
        (uid, month_start, month_end)).fetchall()
    
    income = 0; expenses = 0
    for r in rows:
        if r['type'] == 'income': income = r['total']
        else: expenses = r['total']

    # Recent transactions
    recent = conn.execute('''SELECT * FROM transactions WHERE user_id=?
        ORDER BY date DESC, created_at DESC LIMIT 10''', (uid,)).fetchall()

    # Category breakdown (expenses this month)
    cats = conn.execute('''SELECT category, SUM(amount) as total FROM transactions
        WHERE user_id=? AND type='expense' AND date BETWEEN ? AND ?
        GROUP BY category ORDER BY total DESC''', (uid, month_start, month_end)).fetchall()

    # Last 6 months trend
    trend = []
    for i in range(5, -1, -1):
        d = today.replace(day=1) - timedelta(days=i*28)
        m_start = f"{d.year}-{d.month:02d}-01"
        m_end = f"{d.year}-{d.month:02d}-{calendar.monthrange(d.year, d.month)[1]:02d}"
        r = conn.execute('''SELECT type, SUM(amount) as t FROM transactions
            WHERE user_id=? AND date BETWEEN ? AND ? GROUP BY type''', (uid, m_start, m_end)).fetchall()
        inc = exp = 0
        for x in r:
            if x['type']=='income': inc = x['t'] or 0
            else: exp = x['t'] or 0
        trend.append({'month': d.strftime('%b %Y'), 'income': inc, 'expense': exp})

    conn.close()
    closing = opening_balance + income - expenses

    return jsonify({
        'opening_balance': opening_balance,
        'income': income,
        'expenses': expenses,
        'closing_balance': closing,
        'net': income - expenses,
        'recent': [dict(r) for r in recent],
        'categories': [dict(c) for c in cats],
        'trend': trend,
        'month_name': today.strftime('%B %Y')
    })

@app.route('/transactions')
@login_required
def transactions():
    return render_template('transactions.html')

@app.route('/api/transactions', methods=['GET'])
@login_required
def get_transactions():
    uid = session['user_id']
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    t_type = request.args.get('type', '')
    month = request.args.get('month', '')
    
    where = 'WHERE user_id=?'
    params = [uid]
    if t_type:
        where += ' AND type=?'; params.append(t_type)
    if month:
        where += ' AND date LIKE ?'; params.append(f'{month}%')
    
    conn = get_db()
    total = conn.execute(f'SELECT COUNT(*) FROM transactions {where}', params).fetchone()[0]
    rows = conn.execute(f'SELECT * FROM transactions {where} ORDER BY date DESC, id DESC LIMIT ? OFFSET ?',
                        params + [per_page, offset]).fetchall()
    conn.close()
    return jsonify({'transactions': [dict(r) for r in rows], 'total': total, 'page': page, 'per_page': per_page})

@app.route('/api/transactions', methods=['POST'])
@login_required
def add_transaction():
    uid = session['user_id']
    data = request.json
    t_type = data.get('type')
    desc = data.get('description', '').strip()
    amount = float(data.get('amount', 0))
    category = data.get('category', '').strip()
    txn_date = data.get('date', date.today().strftime('%Y-%m-%d'))
    
    if not desc or amount <= 0:
        return jsonify({'error': 'Invalid data'}), 400
    
    conn = get_db()
    conn.execute('INSERT INTO transactions (user_id, type, category, description, amount, date) VALUES (?,?,?,?,?,?)',
                 (uid, t_type, category, desc, amount, txn_date))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/transactions/<int:tid>', methods=['DELETE'])
@login_required
def delete_transaction(tid):
    uid = session['user_id']
    conn = get_db()
    conn.execute('DELETE FROM transactions WHERE id=? AND user_id=?', (tid, uid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/opening-balance', methods=['POST'])
@login_required
def set_opening_balance():
    uid = session['user_id']
    data = request.json
    year = data.get('year', date.today().year)
    month = data.get('month', date.today().month)
    balance = float(data.get('balance', 0))
    conn = get_db()
    conn.execute('''INSERT INTO monthly_budget (user_id, year, month, opening_balance)
        VALUES (?,?,?,?) ON CONFLICT(user_id,year,month) DO UPDATE SET opening_balance=?''',
        (uid, year, month, balance, balance))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/api/report/weekly')
@login_required
def weekly_report():
    uid = session['user_id']
    today = date.today()
    # Get last 4 weeks
    weeks = []
    for i in range(3, -1, -1):
        week_end = today - timedelta(weeks=i)
        week_start = week_end - timedelta(days=6)
        ws = week_start.strftime('%Y-%m-%d')
        we = week_end.strftime('%Y-%m-%d')
        conn = get_db()
        rows = conn.execute('''SELECT type, SUM(amount) as t, category FROM transactions
            WHERE user_id=? AND date BETWEEN ? AND ? GROUP BY type, category''', (uid, ws, we)).fetchall()
        conn.close()
        inc = exp = 0; cats = {}
        for r in rows:
            if r['type']=='income': inc += r['t'] or 0
            else:
                exp += r['t'] or 0
                cats[r['category'] or 'Other'] = cats.get(r['category'] or 'Other', 0) + (r['t'] or 0)
        weeks.append({'label': f"{week_start.strftime('%d %b')} - {week_end.strftime('%d %b')}",
                      'start': ws, 'end': we, 'income': inc, 'expense': exp, 'categories': cats})
    return jsonify(weeks)

@app.route('/api/report/monthly')
@login_required
def monthly_report():
    uid = session['user_id']
    today = date.today()
    months = []
    for i in range(5, -1, -1):
        d = today.replace(day=1) - timedelta(days=i*28)
        ms = f"{d.year}-{d.month:02d}-01"
        me = f"{d.year}-{d.month:02d}-{calendar.monthrange(d.year,d.month)[1]:02d}"
        conn = get_db()
        rows = conn.execute('''SELECT type, SUM(amount) as t, category FROM transactions
            WHERE user_id=? AND date BETWEEN ? AND ? GROUP BY type, category''', (uid, ms, me)).fetchall()
        ob = conn.execute('SELECT opening_balance FROM monthly_budget WHERE user_id=? AND year=? AND month=?',
                          (uid, d.year, d.month)).fetchone()
        conn.close()
        inc = exp = 0; cats = {}
        for r in rows:
            if r['type']=='income': inc += r['t'] or 0
            else:
                exp += r['t'] or 0
                cats[r['category'] or 'Other'] = cats.get(r['category'] or 'Other', 0) + (r['t'] or 0)
        opening = ob['opening_balance'] if ob else 0
        months.append({'label': d.strftime('%B %Y'), 'income': inc, 'expense': exp,
                        'opening': opening, 'closing': opening + inc - exp, 'categories': cats})
    return jsonify(months)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
