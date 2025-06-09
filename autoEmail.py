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

# ----------------------------
# Part 1: Fetch Odoo Data
# ----------------------------
print("Connecting to Odoo and fetching leads...")

# Odoo connection details (use your production details here)
ODOO_URL = os.getenv("ODOO_URL", "https://odoo-scoobic-holding-test.nip.ccit.es")
ODOO_DB = os.getenv("ODOO_DB", "copiaprod24-3-25")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "your-production-api-key")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "daniel.byle@scoobic.com")

# Authenticate with Odoo
common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})

# Connect to the object API
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

domain = []
fields = ['id', 'name', 'email_from', 'create_date', 'city', 'country_id']

leads = models.execute_kw(
    ODOO_DB, uid, ODOO_API_KEY,
    'crm.lead', 'search_read',
    [domain],
    {'fields': fields, 'order': 'create_date desc'}
)

print(f"Fetched {len(leads)} leads from Odoo.")

# Convert leads to a pandas DataFrame
df = pd.DataFrame(leads)

# ----------------------------
# Field Mapping Debug Information
# ----------------------------
print("Field mapping (columns):")
print(df.columns)
print("\nSample record:")
print(df.head(1))

##############################################
# Show all columns that were fetched
print("Columns fetched from Odoo:")
print(df.columns)

# Display a few rows to see the data
print("\nSample Data:")
print(df.head())
###############################################



df['create_date'] = pd.to_datetime(df['create_date'])

# ----------------------------
# Part 2: Filter and Export Leads
# ----------------------------
now = datetime.utcnow()
window_start = now - timedelta(hours=25)

new_leads = df[df['create_date'] >= window_start]

if new_leads.empty:
    print("No new leads in the last 25 hours.")
    no_new_leads = True
    # Create a DataFrame with a message indicating no new deals
    export_leads = pd.DataFrame({
        "Message": [f"No new deals between {window_start.strftime('%Y-%m-%d %H:%M:%S')} and {now.strftime('%Y-%m-%d %H:%M:%S')}."]
    })
else:
    export_leads = new_leads
    no_new_leads = False

# Export the filtered leads to an Excel file (this file is always generated)
excel_file = "leads_report.xlsx"
export_leads.to_excel(excel_file, index=False)
print(f"Exported leads to Excel: {excel_file}")

# ----------------------------
# Part 3: Generate Graphs and Save as PDF
# ----------------------------
print("Generating graphs...")

df.sort_values(by='create_date', inplace=True)

# Graph 1: Daily counts for last 14 days
start_daily = now - timedelta(days=14)
df_daily = df[df['create_date'] >= start_daily].copy()
df_daily.set_index('create_date', inplace=True)
daily_counts = df_daily.resample('D').size()

fig1, ax1 = plt.subplots(figsize=(10, 6))
daily_counts.plot(kind='bar', ax=ax1)
ax1.set_title('Daily New Deals (Last 14 Days)')
ax1.set_xlabel('Date')
ax1.set_ylabel('Number of Deals')
plt.xticks(rotation=45)
plt.tight_layout()

# Graph 2: Weekly counts for last 6 weeks
start_weekly = now - timedelta(weeks=6)
df_weekly = df[df['create_date'] >= start_weekly].copy()
df_weekly.set_index('create_date', inplace=True)
weekly_counts = df_weekly.resample('W').size()

fig2, ax2 = plt.subplots(figsize=(10, 6))
weekly_counts.plot(kind='bar', ax=ax2)
ax2.set_title('Weekly New Deals (Last 6 Weeks)')
ax2.set_xlabel('Week')
ax2.set_ylabel('Number of Deals')
plt.xticks(rotation=45)
plt.tight_layout()

# Graph 3: Monthly counts for last 6 months
start_monthly = now - pd.DateOffset(months=6)
df_monthly = df[df['create_date'] >= start_monthly].copy()
df_monthly.set_index('create_date', inplace=True)
monthly_counts = df_monthly.resample('M').size()

fig3, ax3 = plt.subplots(figsize=(10, 6))
monthly_counts.plot(kind='bar', ax=ax3)
ax3.set_title('Monthly New Deals (Last 6 Months)')
ax3.set_xlabel('Month')
ax3.set_ylabel('Number of Deals')
plt.xticks(rotation=45)
plt.tight_layout()

pdf_file = "leads_graphs.pdf"
with PdfPages(pdf_file) as pdf:
    pdf.savefig(fig1)
    pdf.savefig(fig2)
    pdf.savefig(fig3)
plt.close('all')
print(f"Graphs saved to PDF: {pdf_file}")

# ----------------------------
# Part 4: Send Email with Attachments
# ----------------------------
print("Preparing email...")

EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not EMAIL_USERNAME or not EMAIL_PASSWORD:
    raise Exception("Gmail credentials are not set in the environment variables.")

sender_email = EMAIL_USERNAME
# Updated recipient list
receiver_emails = ["dany.work.99@gmail.com", "antonio.suarez@scoobic.com", "daniel.byle@scoobic.com", "scoobicapps@gmail.com"]

current_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
period_start_str = window_start.strftime("%Y-%m-%d %H:%M:%S UTC")
period_end_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")

if no_new_leads:
    body_text = (f"Daily Leads Report ({period_start_str} to {period_end_str}):\n\n"
                 "There have been no new deals in the specified period.\n"
                 "Please find attached the Excel report and graphs.")
else:
    body_text = (f"Daily Leads Report ({period_start_str} to {period_end_str}):\n\n"
                 "Please find attached the Excel report for new leads (last 25 hours) and the graphs.")

subject = f"Daily Leads Report - {current_str}"

message = MIMEMultipart()
message["From"] = sender_email
message["To"] = ", ".join(receiver_emails)
message["Subject"] = subject
message.attach(MIMEText(body_text, "plain"))

def attach_file(msg, filepath):
    with open(filepath, "rb") as file:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(file.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(filepath)}")
    msg.attach(part)

# Attach both the Excel file and the PDF
attach_file(message, excel_file)
attach_file(message, pdf_file)

print("Sending email...")
context = ssl.create_default_context()
with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls(context=context)
    server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
    server.sendmail(sender_email, receiver_emails, message.as_string())

print("Email sent successfully!")
