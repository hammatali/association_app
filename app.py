import psycopg2
import os
from flask import Flask, render_template, request, redirect, url_for, send_file, Response
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
import io
from functools import wraps
from datetime import date

app = Flask(__name__)

# ✅ CONFIGURATION DATABASE RENDER
# Transforme postgres:// en postgresql:// pour la compatibilité Python
raw_url = os.environ.get("DATABASE_URL")
if raw_url and raw_url.startswith("postgres://"):
    DATABASE_URL = raw_url.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = raw_url

# 🔐 IDENTIFIANTS ADMIN
ADMIN_USER = "admin"
ADMIN_PASS = "SALL250159"

def get_db_connection():
    # Connexion simple pour le réseau interne Render
    return psycopg2.connect(DATABASE_URL)

# --- SÉCURITÉ ADMIN ---
def check_auth(username, password):
    return username == ADMIN_USER and password == ADMIN_PASS

def authenticate():
    return Response(
        'Identifiants requis pour accéder à l\'administration.', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

MONTHS = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin",
          "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"]

# --- ROUTES ---

@app.route("/")
def home():
    return "L'application est en ligne. Accédez à /admin pour gérer les données."

@app.route("/admin", methods=["GET", "POST"])
@requires_auth
def admin_dashboard():
    conn = get_db_connection()
    c = conn.cursor()

    if request.method == "POST":
        if "add_member" in request.form:
            name = request.form["name"].strip()
            association = request.form["association"].strip().upper()
            c.execute("INSERT INTO Member(name, association) VALUES (%s, %s)", (name, association))
        
        elif "delete_member" in request.form:
            mid = request.form["member_id"]
            c.execute("DELETE FROM Payment WHERE member_id=%s", (mid,))
            c.execute("DELETE FROM Member WHERE id=%s", (mid,))
        
        elif "add_payment" in request.form:
            mid = request.form["member_id"]
            mon = request.form["month"]
            yr = request.form["year"]
            amt = float(request.form["amount"])
            c.execute("INSERT INTO Payment(member_id, month, year, amount) VALUES (%s, %s, %s, %s)", (mid, mon, yr, amt))

        elif "delete_payment" in request.form:
            pid = request.form["payment_id"]
            c.execute("DELETE FROM Payment WHERE id=%s", (pid,))
        
        conn.commit()

    c.execute("SELECT id, name, association FROM Member ORDER BY name ASC")
    members = c.fetchall()
    c.execute("SELECT p.id, m.name, p.month, p.year, p.amount FROM Payment p JOIN Member m ON p.member_id = m.id ORDER BY p.id DESC")
    payments = c.fetchall()
    conn.close()
    return render_template("dashboard.html", members=members, payments=payments, months=MONTHS)

@app.route("/<association>", methods=["GET", "POST"])
def public_view(association):
    assoc_name = association.strip().upper()
    year_selected = str(request.form.get("year", date.today().year))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name FROM Member WHERE UPPER(association)=%s", (assoc_name,))
    members = c.fetchall()

    table_data = []
    total_per_month = {m: 0 for m in MONTHS}
    total_general = 0

    for m_id, m_name in members:
        row_months = {}
        m_total = 0
        for mon in MONTHS:
            c.execute("SELECT SUM(amount) FROM Payment WHERE member_id=%s AND TRIM(month)=%s AND year=%s", (m_id, mon, year_selected))
            res = c.fetchone()[0]
            amt = float(res) if res is not None else 0.0
            row_months[mon] = amt
            m_total += amt
            total_per_month[mon] += amt
        
        total_general += m_total
        table_data.append({"name": m_name, "months": row_months, "total": m_total})

    conn.close()
    return render_template("public.html", association=assoc_name, year=year_selected, 
                           months=MONTHS, table_data=table_data, total_per_month=total_per_month, total_general=total_general)

@app.route("/export/<association>/<year>")
def export_pdf(association, year):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name FROM Member WHERE UPPER(association)=%s", (association.upper(),))
    members = c.fetchall()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    style = getSampleStyleSheet()
    elements.append(Paragraph(f"Cotisations {association.upper()} - {year}", style['Heading1']))
    
    data = [["Nom"] + MONTHS + ["Total"]]
    for m_id, m_name in members:
        row = [m_name]
        m_total = 0
        for mon in MONTHS:
            c.execute("SELECT SUM(amount) FROM Payment WHERE member_id=%s AND TRIM(month)=%s AND year=%s", (m_id, mon, year))
            res = c.fetchone()[0]
            val = float(res) if res is not None else 0.0
            row.append(val)
            m_total += val
        row.append(m_total)
        data.append(row)
    
    table = Table(data)
    table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    conn.close()
    return send_file(buffer, as_attachment=True, download_name=f"export_{association}.pdf", mimetype="application/pdf")

def init_db():
    if not DATABASE_URL: return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS Member(id SERIAL PRIMARY KEY, name TEXT, association TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS Payment(id SERIAL PRIMARY KEY, member_id INTEGER, month TEXT, year TEXT, amount REAL, FOREIGN KEY(member_id) REFERENCES Member(id))")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erreur d'initialisation : {e}")

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
