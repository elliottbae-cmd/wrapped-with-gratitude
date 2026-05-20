# Wrapped with Gratitude — Inventory & Sales App

Streamlit + Supabase app for a small gift-making business. Tracks inventory with
FIFO lot-level cost basis, builds sales baskets with markup, generates customer
invoices, and produces simple BS / P&L reports.

## Phases

1. **Inventory ingestion** — upload vendor invoices, Claude vision parses line
   items, prorata allocates shipping/tax, creates inventory lots
2. **Sales / basket** — pick from inventory, apply markup, generate PDF invoice
   with Venmo payment info, decrement lots FIFO
3. **Reports** — Balance Sheet + P&L (admin-only)
4. **Marketing** — SendGrid email campaigns + Instagram Graph API

## Setup

### 1. Supabase project

1. Create new project (region: Canada Central). Save the DB password.
2. From **Project Settings → API**, copy `Project URL` and `anon` `public` key
   into `.env` (see `.env.example`)
3. Run `db/migrations/001_initial_schema.sql` in the Supabase SQL Editor
4. Create a Storage bucket named `invoices` (private, MIME types: pdf, jpeg, png)
5. Create your wife's user account: **Authentication → Users → Add user (email)**
6. Promote her to admin (run in SQL Editor — replace the email):
   ```sql
   update public.profiles
   set role = 'admin'
   where id = (select id from auth.users where email = 'her@email.com');
   ```

### 2. Local environment

```bash
python -m venv .venv
.venv\Scripts\activate           # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env           # then fill in real values
streamlit run app.py
```

### 3. First login

Use the email + password from step 5 above. Streamlit will persist the session
for the browser tab.

## User roles

- `admin` — sees everything including reports, COGS, margin
- `staff` — operational pages only (upload, inventory, sales, customers, marketing)

New users default to `staff`. Promote via the SQL snippet above or (later) via
the Settings page.

## Project layout

```
app.py                        Streamlit entry (login gate + home)
config.py                     Env loader, app constants
db/
  client.py                   Supabase client factory (uses session JWT)
  migrations/
    001_initial_schema.sql    All tables, RLS, triggers
services/
  invoice_parser.py           Claude vision → structured invoice JSON
  invoice_allocator.py        Prorata shipping/tax → landed_unit_cost
  inventory.py                Lot create, FIFO query, on-hand summary
ui/
  auth.py                     Login form + session helpers
  invoice_review.py           Editable review table before commit
pages/
  1_📥_Upload_Invoice.py
  2_📦_Inventory.py
```
