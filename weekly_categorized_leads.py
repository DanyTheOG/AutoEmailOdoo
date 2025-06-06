# weekly_categorized_leads.py

import xmlrpc.client
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
from datetime import datetime, timedelta

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
domain = []  # fetch all leads

leads = models.execute_kw(
    ODOO_DB, uid, ODOO_API_KEY,
    'crm.lead', 'search_read',
    [domain],
    {'fields': fields, 'order': 'create_date desc'}
)

print(f"Fetched {len(leads)} leads from Odoo.")
df = pd.DataFrame(leads)

# ----------------------------
# Part 2: Pre-filtering & Cleaning
# ----------------------------
df['create_date'] = pd.to_datetime(df['create_date'])

# Exclude leads whose name or email_from contain "test" or "prueba" (case-insensitive)
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

# ----------------------------
# Part 3: Categorize All Included Leads
# ----------------------------
included_df['country_name'] = included_df['country_id'].apply(
    lambda x: x[1] if isinstance(x, (list, tuple)) and len(x) >= 2 else None
)

def categorize(row):
    cname = row['country_name']
    nm_lower = (row['name'] or "").strip().lower()
    if cname not in ["Spain", "Portugal"]:
        return "Internacional"
    elif nm_lower.startswith("presupuestador"):
        return "Nimo"
    else:
        return "Scoobic team"

included_df['category'] = included_df.apply(categorize, axis=1)

# --------------------------------------------------------------------------------------
# Part 4: Time-Windowed Subsets & Data Preprocessing for Charts
# --------------------------------------------------------------------------------------

now = datetime.utcnow()

### 4.1 Last 30 Days (for PDF A: 3-bar “to be printed”)
window_30d_start = now - timedelta(days=30)
mask_30d = included_df['create_date'] >= window_30d_start
df_30d = included_df[mask_30d].copy()
totals_30d = df_30d['category'].value_counts().reindex(
    ["Internacional", "Scoobic team", "Nimo"], fill_value=0
)

### 4.2 Last 24 Months (for PDF B: monthly stacked history)
month_24_start = (now.replace(day=1) - pd.DateOffset(months=24)).to_pydatetime()
mask_24m = included_df['create_date'] >= month_24_start
df_24m = included_df[mask_24m].copy()
df_24m['year_month'] = df_24m['create_date'].dt.to_period('M').dt.to_timestamp()
monthly_counts_24m = (
    df_24m
    .groupby(['year_month', 'category'])
    .size()
    .unstack(fill_value=0)
    .reindex(columns=["Internacional", "Scoobic team", "Nimo"], fill_value=0)
    .sort_index()
)
monthly_counts_24m = monthly_counts_24m[(monthly_counts_24m.sum(axis=1) > 0)]

### 4.3 Current Year (for PDF C: grouped bars by month)
current_year = now.year
mask_cy = included_df['create_date'].dt.year == current_year
df_cy = included_df[mask_cy].copy()
df_cy['year_month'] = df_cy['create_date'].dt.to_period('M').dt.to_timestamp()
monthly_counts_cy = (
    df_cy
    .groupby(['year_month', 'category'])
    .size()
    .unstack(fill_value=0)
    .reindex(columns=["Internacional", "Scoobic team", "Nimo"], fill_value=0)
    .sort_index()
)
monthly_counts_cy = monthly_counts_cy[(monthly_counts_cy.sum(axis=1) > 0)]

### 4.4 Last 12 Months Top 3 Cities (for PDF D)
month_12_start = (now.replace(day=1) - pd.DateOffset(months=12)).to_pydatetime()
mask_12m = included_df['create_date'] >= month_12_start
df_12m = included_df[mask_12m].copy()
df_12m['year_month'] = df_12m['create_date'].dt.to_period('M').dt.to_timestamp()

top3_per_month = {}
for ym, group in df_12m.groupby('year_month'):
    city_counts = group['city'].fillna("Unknown").value_counts()
    top_cities = city_counts.head(3)
    top3_per_month[ym] = top_cities

# --------------------------------------------------------------------------------------
# Part 5: Generate PDF A: "weekly_lead_categories_to_be_printed.pdf"
# --------------------------------------------------------------------------------------
pdf_A = "weekly_lead_categories_to_be_printed.pdf"
figA, axA = plt.subplots(figsize=(8, 6))

labels_A = ["Internacional", "Scoobic team", "Nimo"]
values_A = [totals_30d[label] for label in labels_A]
barsA = axA.bar(labels_A, values_A, color=['tab:blue', 'tab:orange', 'tab:green'])

for bar, v in zip(barsA, values_A):
    axA.text(
        bar.get_x() + bar.get_width() / 2,
        v + 0.1,
        str(v),
        ha='center',
        va='bottom',
        fontsize=10
    )

title_A = f"30-Day Total Leads by Category (Generated {now.strftime('%Y-%m-%d')})"
axA.set_title(title_A)
axA.set_ylabel("Number of Leads")
plt.tight_layout()
figA.savefig(pdf_A)
plt.close(figA)
print(f"Saved: {pdf_A}")

# --------------------------------------------------------------------------------------
# Part 6: Generate PDF B: "lead_history_by_month.pdf"
# --------------------------------------------------------------------------------------
pdf_B = "lead_history_by_month.pdf"
with PdfPages(pdf_B) as pdf:
    figB, axB = plt.subplots(figsize=(12, 6))

    bottom = np.zeros(len(monthly_counts_24m))
    x_B = monthly_counts_24m.index.to_pydatetime()
    colors = ['tab:blue', 'tab:orange', 'tab:green']

    for i, cat in enumerate(["Internacional", "Scoobic team", "Nimo"]):
        vals = monthly_counts_24m[cat].values
        bars = axB.bar(
            x_B,
            vals,
            bottom=bottom,
            width=20,  # width in days
            align='center',
            label=cat,
            color=colors[i]
        )

        for idx, bar in enumerate(bars):
            count = vals[idx]
            if count > 0:
                x_center = bar.get_x() + bar.get_width() / 2
                y_center = bottom[idx] + count / 2
                axB.text(
                    x_center,
                    y_center,
                    str(count),
                    ha='center',
                    va='center',
                    fontsize=8,
                    color='white'
                )

        bottom += vals

    title_B = f"Monthly Leads by Category (Last 24 Months) (Generated {now.strftime('%Y-%m-%d')})"
    axB.set_title(title_B)
    axB.set_xlabel("Month")
    axB.set_ylabel("Number of Leads")
    axB.legend()
    plt.xticks(
        x_B,
        [dt.strftime("%Y-%m") for dt in x_B],
        rotation=45,
        fontsize=8
    )
    plt.tight_layout()
    pdf.savefig(figB)
    plt.close(figB)
print(f"Saved: {pdf_B}")

# --------------------------------------------------------------------------------------
# Part 7: Generate PDF C: "lead_category_by_month_current_year.pdf"
#          (with thinner bars—width=10 instead of 20)
# --------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------
# Part 7: Generate PDF C: "lead_category_by_month_current_year.pdf"
#            (using numeric x-positions for truly grouped bars)
# --------------------------------------------------------------------------------------
pdf_C = "lead_category_by_month_current_year.pdf"
with PdfPages(pdf_C) as pdf:
    figC, axC = plt.subplots(figsize=(12, 6))

    # 1) Prepare the “months” and counts
    months = monthly_counts_cy.index.to_pydatetime()           # array of Timestamp objects
    month_labels = [dt.strftime("%Y-%m") for dt in months]      # e.g. ["2025-01", "2025-02", ...]
    x_pos = np.arange(len(months))                              # [0, 1, 2, 3, ...]

    width = 0.25  # width of each bar
    colors = ['tab:blue', 'tab:orange', 'tab:green']

    # 2) Plot each category at x_pos + i*width
    for i, cat in enumerate(["Internacional", "Scoobic team", "Nimo"]):
        vals = monthly_counts_cy[cat].values
        bars = axC.bar(
            x_pos + i * width,
            vals,
            width=width,
            label=cat,
            color=colors[i]
        )
        # Annotate counts above each bar
        for bar, count in zip(bars, vals):
            if count > 0:
                axC.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.1,
                    str(count),
                    ha='center',
                    va='bottom',
                    fontsize=7
                )

    # 3) Center x-ticks under the three bars per month
    axC.set_xticks(x_pos + width)                # center of the three-group
    axC.set_xticklabels(month_labels, rotation=45, fontsize=8)

    # 4) Titles, legend, labels
    title_C = f"Current Year Leads by Category ({current_year}) (Generated {now.strftime('%Y-%m-%d')})"
    axC.set_title(title_C)
    axC.set_xlabel("Month")
    axC.set_ylabel("Number of Leads")
    axC.legend()

    plt.tight_layout()
    pdf.savefig(figC)
    plt.close(figC)

print(f"Saved: {pdf_C}")


# --------------------------------------------------------------------------------------
# Part 8: Generate PDF D: "top3_cities_last_12_months.pdf"
# --------------------------------------------------------------------------------------
pdf_D = "top3_cities_last_12_months.pdf"
with PdfPages(pdf_D) as pdf:
    figD, axD = plt.subplots(figsize=(14, 6))

    x_positions = []
    heights = []
    labels = []
    colors_map = {}
    color_cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']
    next_color_idx = 0

    sorted_months = sorted(top3_per_month.keys())
    for idx_m, ym in enumerate(sorted_months):
        top_cities = top3_per_month[ym]
        x_base = idx_m * 4  # gap of 1 unit between months
        for i, (city, count) in enumerate(top_cities.items()):
            x_positions.append(x_base + i)
            heights.append(count)
            labels.append(f"{ym.strftime('%Y-%m')}\n{city}")
            if city not in colors_map:
                colors_map[city] = next_color_idx % len(color_cycle)
                next_color_idx += 1

    bars = axD.bar(
        x_positions,
        heights,
        color=[color_cycle[colors_map[labels[i].split('\n', 1)[1]]] for i in range(len(labels))]
    )

    for bar, h in zip(bars, heights):
        axD.text(
            bar.get_x() + bar.get_width() / 2,
            h + 0.5,
            str(h),
            ha='center',
            va='bottom',
            fontsize=7
        )

    title_D = f"Top 3 Cities per Month (Last 12 Months) (Generated {now.strftime('%Y-%m-%d')})"
    axD.set_title(title_D)
    axD.set_ylabel("Number of Leads")
    plt.xticks(
        x_positions,
        labels,
        rotation=45,
        ha='right',
        fontsize=7
    )
    plt.tight_layout()
    pdf.savefig(figD)
    plt.close(figD)
print(f"Saved: {pdf_D}")

# --------------------------------------------------------------------------------------
# Part 9: Send Email with All Four PDFs
# --------------------------------------------------------------------------------------
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not EMAIL_USERNAME or not EMAIL_PASSWORD:
    raise Exception("Gmail credentials are not set in the environment variables.")

receiver_emails = ["dany.work.99@gmail.com", "scoobicapps@gmail.com"]
subject = f"Weekly Leads & History Report - {now.strftime('%Y-%m-%d')}"

body_text = (
    f"Weekly Leads & History Report (Generated {now.strftime('%Y-%m-%d')}):\n\n"
    "Attached:\n"
    f" • {pdf_A}  (30-day summary — 3-bar)\n"
    f" • {pdf_B}  (Last 24 months — stacked by month)\n"
    f" • {pdf_C}  (Current year — grouped by month, thinner bars)\n"
    f" • {pdf_D}  (Last 12 months — top 3 cities per month)\n\n"
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

for pdf_file in [pdf_A, pdf_B, pdf_C, pdf_D]:
    attach_file(message, pdf_file)

print("Sending email with all four PDFs...")
context = ssl.create_default_context()
with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls(context=context)
    server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
    server.sendmail(EMAIL_USERNAME, receiver_emails, message.as_string())

print("Email sent successfully!")
