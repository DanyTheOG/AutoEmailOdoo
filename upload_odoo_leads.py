import os
import xmlrpc.client
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ——— Odoo credentials from env ———
ODOO_URL      = os.environ['ODOO_URL']
ODOO_DB       = os.environ['ODOO_DB']
ODOO_USERNAME = os.environ['ODOO_USERNAME']
ODOO_API_KEY  = os.environ['ODOO_API_KEY']

# ——— Fetch leads from Odoo ———
common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

fields = ['id','name','email_from','create_date','city','country_id']
leads = models.execute_kw(
    ODOO_DB, uid, ODOO_API_KEY,
    'crm.lead','search_read',
    [ [] ],
    {'fields': fields, 'order': 'create_date desc'}
)
print(f"Fetched {len(leads)} leads")

df = pd.DataFrame(leads)
df['create_date'] = pd.to_datetime(df['create_date'])
df['country_name'] = df['country_id'].apply(
    lambda x: x[1] if isinstance(x,(list,tuple)) and len(x)>=2 else None
)

# ——— Google Sheets setup ———
# (credentials.json is written by the workflow)
SPREADSHEET_ID   = os.environ['GSHEET_SPREADSHEET_ID']
WORKSHEET_NAME   = "Sheet1"
CREDENTIALS_PATH = "credentials.json"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_PATH, scope)
client = gspread.authorize(creds)

sheet = client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
sheet.clear()
sheet.update([df.columns.tolist()] + df.values.tolist())

print(f"Wrote {len(df)} rows to {WORKSHEET_NAME}")
