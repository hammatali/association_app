import psycopg2
import os
from flask import Flask, render_template, request, redirect, url_for, send_file, Response
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
import io
from functools import wraps

app = Flask(__name__)

# ✅ CONFIGURATION NEON
db_env = os.environ.get("DATABASE_URL")
if db_env and db_env.startswith("postgres://"):
    DATABASE_URL = db_env.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = db_env

# 🔐 SÉCURITÉ ADMIN
ADMIN_USER = "admin"
ADMIN_PASS = "SALL250159"

def get_db_connection():
    # Nécessaire pour Neon.tech
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def check_auth(username, password):
    return username == ADMIN_USER and password == ADMIN_PASS

def authenticate():
    return Response('Identifiants invalides.', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

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

@app.route("/")
def home():
    return "Application Active. Accédez à /admin ou /votre_association"

# --------- ROUTE ADMIN ----------------
@app.route("/admin", methods=["GET", "POST"])
@requires_auth
def admin_dashboard():
    conn = get_db_connection()
    c = conn.cursor()

    if request.method == "POST" and "add_member" in request.form:
        name = request.form["name"].strip()
        association = request.form["association"].strip().upper()
        c.execute("INSERT INTO Member(name, association) VALUES (%s, %s)", (name, association))
        conn.commit()

    if request.method == "POST" and "delete_member" in request.form:
        member_id = request.form["member_id"]
        c.execute("DELETE FROM Payment WHERE member_id=%s", (member_id,))
        c.execute("DELETE FROM Member WHERE id=%s", (member_id,))
        conn.commit()
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST" and "add_payment" in request.form:
        member_id = request.form["member_id"]
        month = request.form["month"]
        year = request.form["year"]
        amount = float(request.form["amount"])
        c.execute("INSERT INTO Payment(member_id, month, year, amount) VALUES (%s, %s, %s, %s)",
                  (member_id, month, year, amount))
        conn.commit()

    if request.method == "POST" and "delete_payment" in request.form:
        payment_id = request.form["payment_id"]
        c.execute("DELETE FROM Payment WHERE id=%s", (payment_id,))
        conn.commit()
        return redirect(url_for("admin_dashboard"))

    c.execute("SELECT id, name, association FROM Member")
    members = c.fetchall()
    c.execute("""
        SELECT Payment.id, Member.name, Payment.month, Payment.year, Payment.amount
        FROM Payment JOIN Member ON Payment.member_id=Member.id
        ORDER BY Member.name
    """)
    payments = c.fetchall()
    conn.close()
    return render_template("dashboard.html", members=members, payments=payments, months=MONTHS)

# --------- ROUTE PUBLIQUE ---------------------
@app.route("/<association>", methods=["GET", "POST"])
def public_view(association):
    association = association.strip().upper()
    from datetime import date
    year_selected = request.form.get("year", str(date.today().year))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name FROM Member WHERE UPPER(association)=%s", (association,))
    members = c.fetchall()

    table_data = []
    total_per_month = {m: 0 for m in MONTHS}
    total_general = 0

    for member_id, member_name in members:
        row_months = {}
        member_total = 0
        for month in MONTHS:
            c.execute("SELECT SUM(amount) FROM Payment WHERE member_id=%s AND TRIM(month)=%s AND year=%s", (member_id, month, year_selected))
            res = c.fetchone()[0]
            amount = res if res else 0
            row_months[month] = amount
            member_total += amount
            total_per_month[month] += amount
        total_general += member_total
        table_data.append({"name": member_name, "months": row_months, "total": member_total})

    conn.close()
    return render_template("public.html", association=association, year=year_selected, 
                           months=MONTHS, table_data=table_data, total_per_month=total_per_month, total_general=total_general)

# --------- EXPORT PDF ----------------
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
    elements.append(Paragraph(f"{association.upper()} - {year}", style['Heading1']))
    
    data = [["Nom"] + MONTHS + ["Total"]]
    for m_id, m_name in members:
        row = [m_name]
        for mon in MONTHS:
            c.execute("SELECT SUM(amount) FROM Payment WHERE member_id=%s AND TRIM(month)=%s AND year=%s", (m_id, mon, year))
            res = c.fetchone()[0]
            row.append(res if res else 0)
        data.append(row)
    
    table = Table(data)
    table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black)]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    conn.close()
    return send_file(buffer, as_attachment=True, download_name="export.pdf", mimetype="application/pdf")

def init_db():
    if not DATABASE_URL: return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS Member(id SERIAL PRIMARY KEY, name TEXT, association TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS Payment(id SERIAL PRIMARY KEY, member_id INTEGER, month TEXT, year TEXT, amount REAL, FOREIGN KEY(member_id) REFERENCES Member(id))")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    #app.run(host='0.0.0.0', port=port)
    #app.run(host='0.0.0.0', port=port, debug=True)
    app.run(host='0.0.0.0', port=port, debug=True)


