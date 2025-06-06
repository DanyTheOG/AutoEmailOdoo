# weekly_categorized_leads.py

import xmlrpc.client
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
from datetime import datetime, timedelta
import numpy as np

# ----------------------------
# Part 1: Fetch Odoo Data
# ----------------------------
print("Connecting to Odoo and fetching leads...")

ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_API_KEY = os.getenv("ODOO_API_KEY")
ODOO_USERNAME = os.getenv("ODOO_USERNAME")

if not all([ODOO_URL, ODOO_DB, ODOO_API_KEY, ODOO_USERNAME]):
    raise Exception("One or more Odoo environment variables are missing.")

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})

models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

fields = ['id', 'name', 'email_from', 'create_date', 'city', 'country_id']
domain = []  # no extra domain, fetch all leads

leads = models.execute_kw(
    ODOO_DB, uid, ODOO_API_KEY,
    'crm.lead', 'search_read',
    [domain],
    {'fields': fields, 'order': 'create_date desc'}
)

print(f"Fetched {len(leads)} leads from Odoo.")
df = pd.DataFrame(leads)

# ----------------------------
# Part 2: Pre‐filtering & cleaning
# ----------------------------
# Convert create_date to datetime
df['create_date'] = pd.to_datetime(df['create_date'])

# Drop any rows where name or email_from contain "test" or "prueba" (case‐insensitive)
mask_exclude = (
    df['name'].str.lower().str.contains("test", na=False) |
    df['name'].str.lower().str.contains("prueba", na=False) |
    df['email_from'].str.lower().str.contains("test", na=False) |
    df['email_from'].str.lower().str.contains("prueba", na=False)
)
excluded_df = df[mask_exclude].copy()
included_df = df[~mask_exclude].copy()
excluded_count = len(excluded_df)
print(f"Excluded {excluded_count} leads (test/prueba).")

# Build a 30‐day window
now = datetime.utcnow()
window_start = now - timedelta(days=30)
window_mask = included_df['create_date'] >= window_start
window_df = included_df[window_mask].copy()

# Extract country name from country_id list [id, name]
window_df['country_name'] = window_df['country_id'].apply(
    lambda x: x[1] if isinstance(x, (list, tuple)) and len(x) >= 2 else None
)

# ----------------------------
# Part 3: Categorize leads
# ----------------------------
def categorize(row):
    cname = row['country_name']
    nm_lower = (row['name'] or "").strip().lower()
    if cname not in ["Spain", "Portugal"]:
        return "Foreign"
    elif nm_lower.startswith("presupuestador"):
        return "Presupuestador"
    else:
        return "Normal"

window_df['category'] = window_df.apply(categorize, axis=1)

# ----------------------------
# Part 4: Save CSV of filtered + categorized leads
# ----------------------------
csv_filename = "weekly_leads_categorized.csv"
export_cols = ['id', 'name', 'email_from', 'create_date', 'city', 'country_name', 'category']
window_df.to_csv(csv_filename, index=False)
print(f"Exported categorized leads to CSV: {csv_filename}")

# ----------------------------
# Part 5: Build Daily Counts per Category
# ----------------------------
# Create a date index with one row per day for the last 30 days
all_days = pd.date_range(start=window_start.normalize(), end=now.normalize(), freq='D')
counts_df = pd.DataFrame(index=all_days)

# For each category, compute daily counts
for cat in ["Foreign", "Presupuestador", "Normal"]:
    tmp = window_df[window_df['category'] == cat].copy()
    tmp.set_index('create_date', inplace=True)
    daily_counts = tmp['id'].resample('D').count()
    counts_df[cat] = daily_counts.reindex(all_days, fill_value=0)

counts_df = counts_df.fillna(0).astype(int)

# ----------------------------
# Part 6: Generate PDF with Two Charts
# ----------------------------
pdf_filename = "weekly_lead_types.pdf"
with PdfPages(pdf_filename) as pdf:
    # 6A: Stacked Bar Chart
    fig, ax = plt.subplots(figsize=(12, 6))
    bottom = np.zeros(len(all_days))
    colors = ['tab:blue', 'tab:orange', 'tab:green']  # you can adjust if you like

    for i, cat in enumerate(["Foreign", "Normal", "Presupuestador"]):
        vals = counts_df[cat].values
        bars = ax.bar(
            all_days,
            vals,
            bottom=bottom,
            label=cat,
            color=colors[i]
        )
        # Annotate each segment with its count
        for bar, count in zip(bars, vals):
            if count > 0:
                height = bar.get_height()
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_y() + height / 2 + bottom[list(all_days).index(bar.get_x().astype('M8[ns]'))],
                    str(count),
                    ha='center',
                    va='center',
                    fontsize=8,
                    color='white' if height > 0 else 'black'
                )
        bottom += vals

    ax.set_title("Daily Leads by Category (Last 30 Days) – Stacked")
    ax.set_xlabel("Date")
    ax.set_ylabel("Number of Leads")
    ax.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)

    # 6B: Grouped Bar Chart
    fig2, ax2 = plt.subplots(figsize=(12, 6))
    width = 0.25
    x = np.arange(len(all_days))

    for i, cat in enumerate(["Foreign", "Normal", "Presupuestador"]):
        vals = counts_df[cat].values
        bars = ax2.bar(
            x + i * width,
            vals,
            width=width,
            label=cat,
            color=colors[i]
        )
        # Annotate each bar
        for bar, count in zip(bars, vals):
            if count > 0:
                ax2.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.1,
                    str(count),
                    ha='center',
                    va='bottom',
                    fontsize=7
                )

    ax2.set_title("Daily Leads by Category (Last 30 Days) – Grouped")
    ax2.set_xlabel("Date")
    ax2.set_ylabel("Number of Leads")
    ax2.set_xticks(x + width)
    ax2.set_xticklabels([d.strftime("%Y-%m-%d") for d in all_days], rotation=45, fontsize=7)
    ax2.legend()
    plt.tight_layout()
    pdf.savefig(fig2)
    plt.close(fig2)

print(f"PDF with charts saved: {pdf_filename}")

# ----------------------------
# Part 7: Send Email with CSV + PDF
# ----------------------------
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not EMAIL_USERNAME or not EMAIL_PASSWORD:
    raise Exception("Gmail credentials are not set in the environment variables.")

receiver_emails = ["dany.work.99@gmail.com", "scoobicapps@gmail.com"]
subject = f"Weekly Categorized Leads Report - {now.strftime('%Y-%m-%d')}"

body_text = (
    f"Weekly Categorized Leads Report ({window_start.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}):\n\n"
    f"- Total leads fetched: {len(leads)}\n"
    f"- Total excluded (\"test\"/\"prueba\"): {excluded_count}\n"
    f"- Total included (last 30 days): {len(window_df)}\n\n"
    "Attached:\n"
    f" • {csv_filename}  (all filtered & categorized leads)\n"
    f" • {pdf_filename}  (stacked & grouped bar charts)\n\n"
    "Regards,\nAutomated Report System"
)

message = MIMEMultipart()
message["From"] = EMAIL_USERNAME
message["To"] = ", ".join(receiver_emails)
message["Subject"] = subject
message.attach(MIMEText(body_text, "plain"))

def attach_file(msg, filepath):
    with open(filepath, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f"attachment; filename={os.path.basename(filepath)}"
    )
    msg.attach(part)

attach_file(message, csv_filename)
attach_file(message, pdf_filename)

print("Sending weekly email...")
context = ssl.create_default_context()
with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls(context=context)
    server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
    server.sendmail(EMAIL_USERNAME, receiver_emails, message.as_string())

print("Weekly email sent successfully!")
