import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
#from reportlab.pdfbase.ttfonts import TTFont
#from reportlab.pdfbase import pdfmetrics

from flask import send_file
import io

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.db")

MONTHS = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin",
          "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"]

# --------- ROUTE ADMIN DASHBOARD ----------------
@app.route("/admin", methods=["GET", "POST"])
def admin_dashboard():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Ajouter membre
    if request.method == "POST" and "add_member" in request.form:
        name = request.form["name"].strip()
        association = request.form["association"].strip().upper()
        c.execute("INSERT INTO Member(name, association) VALUES (?, ?)", (name, association))
        conn.commit()

    # Supprimer membre et tous ses paiements
    if request.method == "POST" and "delete_member" in request.form:
        member_id = request.form["member_id"]
        c.execute("DELETE FROM Payment WHERE member_id=?", (member_id,))
        c.execute("DELETE FROM Member WHERE id=?", (member_id,))
        conn.commit()
        return redirect(url_for("admin_dashboard"))

    # Ajouter paiement
    if request.method == "POST" and "add_payment" in request.form:
        member_id = request.form["member_id"]
        month = request.form["month"]
        year = request.form["year"]
        amount = float(request.form["amount"])
        c.execute("INSERT INTO Payment(member_id, month, year, amount) VALUES (?, ?, ?, ?)",
                  (member_id, month, year, amount))
        conn.commit()

    # Supprimer paiement
    if request.method == "POST" and "delete_payment" in request.form:
        payment_id = request.form["payment_id"]
        c.execute("DELETE FROM Payment WHERE id=?", (payment_id,))
        conn.commit()
        return redirect(url_for("admin_dashboard"))

    # Liste des membres
    c.execute("SELECT id, name, association FROM Member")
    members = c.fetchall()

    # Liste des paiements
    c.execute("SELECT Payment.id, Member.name, Payment.month, Payment.year, Payment.amount "
              "FROM Payment JOIN Member ON Payment.member_id=Member.id "
              "ORDER BY Member.name")
    payments = c.fetchall()

    conn.close()
    return render_template("dashboard.html", members=members, payments=payments, months=MONTHS)

# --------- ROUTE PUBLIQUE ---------------------
@app.route("/<association>", methods=["GET", "POST"])
def public_view(association):
    association = association.strip().upper()

    year_selected = request.form.get("year") if request.method=="POST" else None
    if not year_selected:
        from datetime import date
        year_selected = date.today().year
    year_selected = str(year_selected)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Membres actuels de l'association
    c.execute("SELECT id, name FROM Member WHERE UPPER(association)=?", (association,))
    members = c.fetchall()

    table_data = []
    total_per_month = {m:0 for m in MONTHS}
    total_general = 0

    for member_id, member_name in members:
        row_months = {}
        member_total = 0
        for month in MONTHS:
            c.execute("""
                SELECT SUM(amount) FROM Payment
                WHERE member_id=? AND TRIM(month)=? AND year=?
            """, (member_id, month, year_selected))
            result = c.fetchone()[0]
            amount = result if result else 0
            row_months[month] = amount
            member_total += amount
            total_per_month[month] += amount
        total_general += member_total
        table_data.append({
            "name": member_name,
            "months": row_months,
            "total": member_total
        })
    conn.close()

    return render_template(
        "public.html",
        association=association,
        year=year_selected,
        months=MONTHS,
        table_data=table_data,
        total_per_month=total_per_month,
        total_general=total_general
    )




@app.route("/export/<association>/<year>")
def export_pdf(association, year):

    from flask import send_file
    import io

    association = association.upper().strip()
    year = str(year)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT id, name FROM Member WHERE UPPER(association)=?", (association,))
    members = c.fetchall()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)

    elements = []
    style = getSampleStyleSheet()

    # ===== CHOIX AUTOMATIQUE LOGO & SIGNATURE =====
    if association == "CEEN":
        logo_file = "logo.png"
        signature_file = "signature_ceen.png"
    elif association == "ADG":
        logo_file = "logo_adg.png"
        signature_file = "signature_adg.png"
    else:
        logo_file = None
        signature_file = None

    # ===== LOGO =====
    if logo_file:
        logo_path = os.path.join(BASE_DIR, "static", logo_file)
        if os.path.exists(logo_path):
            logo = Image(logo_path, width=120, height=120)
            elements.append(logo)

    elements.append(Spacer(1, 12))

    # ===== TITRE =====
    elements.append(Paragraph(f"{association} - Cotisations {year}", style['Heading1']))
    elements.append(Spacer(1, 20))

    # ===== TABLEAU =====
    data = [["Nom"] + MONTHS + ["Total"]]
    total_general = 0

    for member_id, member_name in members:
        row = [member_name]
        member_total = 0

        for month in MONTHS:
            c.execute("""
                SELECT SUM(amount) FROM Payment
                WHERE member_id=? AND TRIM(month)=? AND year=?
            """, (member_id, month, year))
            result = c.fetchone()[0]
            amount = result if result else 0
            row.append(amount)
            member_total += amount

        row.append(member_total)
        total_general += member_total
        data.append(row)

    data.append(["TOTAL"] + [""]*12 + [total_general])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('ALIGN', (1,1), (-1,-1), 'CENTER')
    ]))

    elements.append(table)
    elements.append(Spacer(1, 40))

    # ===== SIGNATURE =====
    if signature_file:
        signature_path = os.path.join(BASE_DIR, "static", signature_file)
        if os.path.exists(signature_path):
            elements.append(Paragraph("La Trésorière :", style['Normal']))
            elements.append(Spacer(1, 10))
            signature = Image(signature_path, width=150, height=60)
            elements.append(signature)

    doc.build(elements)
    buffer.seek(0)
    conn.close()

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{association}_{year}.pdf",
        mimetype="application/pdf"
    )
# --------- CREATION DB SI NON EXISTE -----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS Member(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            association TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS Payment(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            month TEXT,
            year TEXT,
            amount REAL,
            FOREIGN KEY(member_id) REFERENCES Member(id)
        )
    """)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    app.run(debug=True)