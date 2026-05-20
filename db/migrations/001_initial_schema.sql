-- Wrapped with Gratitude — initial schema
-- Idempotent: safe to re-run. Drops policies before re-creating them.
--
-- Scope:
--   1. profiles + role system (admin | staff)
--   2. Phase 1 inventory tables (vendors, invoices, lines, items, lots)
--   3. Phase 2 sales tables (customers, sales_orders, lines, lot_consumptions)
--   4. RLS enabled on all tables, authenticated-users policies
--
-- Note on role enforcement: RLS policies allow any authenticated user
-- read/write access to operational tables. Admin-only visibility (reports,
-- COGS/margin columns) is enforced in the Streamlit app layer. If true
-- column-level enforcement is needed later, swap to per-role policies or
-- views that exclude sensitive columns.

-- =====================================================================
-- 1. Profiles + roles
-- =====================================================================

create table if not exists public.profiles (
    id          uuid primary key references auth.users(id) on delete cascade,
    full_name   text,
    role        text not null default 'staff' check (role in ('admin','staff')),
    created_at  timestamptz not null default now()
);

-- Auto-create a profile row whenever a new auth user is added.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, full_name, role)
    values (
        new.id,
        coalesce(new.raw_user_meta_data->>'full_name', ''),
        'staff'
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- Helper used by policies and the app.
create or replace function public.is_admin()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
    select exists (
        select 1 from public.profiles
        where id = auth.uid() and role = 'admin'
    );
$$;

-- =====================================================================
-- 2. Vendors + inventory master
-- =====================================================================

create table if not exists public.vendors (
    id           uuid primary key default gen_random_uuid(),
    name         text not null,
    contact_name text,
    email        text,
    phone        text,
    notes        text,
    created_at   timestamptz not null default now(),
    created_by   uuid references auth.users(id)
);

create unique index if not exists vendors_name_unique
    on public.vendors (lower(name));

create table if not exists public.inventory_items (
    id              uuid primary key default gen_random_uuid(),
    sku             text unique,
    name            text not null,
    description     text,
    category        text,
    unit_of_measure text not null default 'each',
    reorder_point   numeric(12,2),
    created_at      timestamptz not null default now(),
    created_by      uuid references auth.users(id)
);

create index if not exists inventory_items_name_idx
    on public.inventory_items (lower(name));

-- =====================================================================
-- 3. Invoices + invoice lines
-- =====================================================================

create table if not exists public.invoices (
    id                  uuid primary key default gen_random_uuid(),
    vendor_id           uuid not null references public.vendors(id) on delete restrict,
    invoice_number      text,
    invoice_date        date not null,
    subtotal            numeric(12,2) not null default 0,
    shipping            numeric(12,2) not null default 0,
    tax                 numeric(12,2) not null default 0,
    other_charges       numeric(12,2) not null default 0,
    total               numeric(12,2) not null default 0,
    pdf_path            text,
    raw_extracted_json  jsonb,
    status              text not null default 'draft'
                            check (status in ('draft','posted')),
    notes               text,
    created_at          timestamptz not null default now(),
    created_by          uuid references auth.users(id),
    constraint invoices_vendor_number_unique unique (vendor_id, invoice_number)
);

create index if not exists invoices_vendor_id_idx on public.invoices (vendor_id);
create index if not exists invoices_date_idx      on public.invoices (invoice_date);

create table if not exists public.invoice_line_items (
    id                  uuid primary key default gen_random_uuid(),
    invoice_id          uuid not null references public.invoices(id) on delete cascade,
    inventory_item_id   uuid not null references public.inventory_items(id) on delete restrict,
    line_no             int,
    description         text,
    qty                 numeric(12,3) not null check (qty > 0),
    unit_price          numeric(12,4) not null check (unit_price >= 0),
    line_subtotal       numeric(12,2) not null check (line_subtotal >= 0),
    allocated_shipping  numeric(12,4) not null default 0,
    allocated_tax       numeric(12,4) not null default 0,
    allocated_other     numeric(12,4) not null default 0,
    landed_unit_cost    numeric(12,4) not null check (landed_unit_cost >= 0),
    created_at          timestamptz not null default now()
);

create index if not exists invoice_line_items_invoice_idx
    on public.invoice_line_items (invoice_id);
create index if not exists invoice_line_items_item_idx
    on public.invoice_line_items (inventory_item_id);

-- =====================================================================
-- 4. Inventory lots (the FIFO unit)
-- =====================================================================

create table if not exists public.inventory_lots (
    id                    uuid primary key default gen_random_uuid(),
    inventory_item_id     uuid not null references public.inventory_items(id) on delete restrict,
    invoice_line_item_id  uuid not null references public.invoice_line_items(id) on delete restrict,
    received_date         date not null,
    qty_received          numeric(12,3) not null check (qty_received > 0),
    qty_remaining         numeric(12,3) not null,
    landed_unit_cost      numeric(12,4) not null check (landed_unit_cost >= 0),
    created_at            timestamptz not null default now(),
    constraint qty_remaining_non_negative check (qty_remaining >= 0),
    constraint qty_remaining_lte_received check (qty_remaining <= qty_received)
);

-- FIFO query path: open lots for an item, oldest first.
create index if not exists inventory_lots_fifo_idx
    on public.inventory_lots (inventory_item_id, received_date, id)
    where qty_remaining > 0;

-- =====================================================================
-- 5. Customers + sales
-- =====================================================================

create table if not exists public.customers (
    id                uuid primary key default gen_random_uuid(),
    name              text not null,
    email             text,
    phone             text,
    instagram_handle  text,
    shipping_address  text,
    billing_address   text,
    notes             text,
    created_at        timestamptz not null default now(),
    created_by        uuid references auth.users(id)
);

create index if not exists customers_name_idx on public.customers (lower(name));
create index if not exists customers_email_idx on public.customers (lower(email));

create table if not exists public.sales_orders (
    id              uuid primary key default gen_random_uuid(),
    order_number    text unique,
    customer_id     uuid not null references public.customers(id) on delete restrict,
    order_date      date not null default current_date,
    subtotal_cogs   numeric(12,2) not null default 0,
    markup_pct      numeric(6,4)  not null default 0,
    subtotal_price  numeric(12,2) not null default 0,
    shipping_charge numeric(12,2) not null default 0,
    sales_tax       numeric(12,2) not null default 0,
    total           numeric(12,2) not null default 0,
    status          text not null default 'draft'
                        check (status in ('draft','invoiced','paid','void')),
    paid_date       date,
    payment_method  text default 'venmo',
    pdf_path        text,
    notes           text,
    created_at      timestamptz not null default now(),
    created_by      uuid references auth.users(id)
);

create index if not exists sales_orders_customer_idx on public.sales_orders (customer_id);
create index if not exists sales_orders_date_idx     on public.sales_orders (order_date);
create index if not exists sales_orders_status_idx   on public.sales_orders (status);

create table if not exists public.sales_order_lines (
    id                  uuid primary key default gen_random_uuid(),
    sales_order_id      uuid not null references public.sales_orders(id) on delete cascade,
    inventory_item_id   uuid not null references public.inventory_items(id) on delete restrict,
    line_no             int,
    qty                 numeric(12,3) not null check (qty > 0),
    unit_price_at_sale  numeric(12,4) not null check (unit_price_at_sale >= 0),
    total_cogs          numeric(12,2) not null default 0,
    created_at          timestamptz not null default now()
);

create index if not exists sales_order_lines_order_idx
    on public.sales_order_lines (sales_order_id);

create table if not exists public.lot_consumptions (
    id                   uuid primary key default gen_random_uuid(),
    sales_order_line_id  uuid not null references public.sales_order_lines(id) on delete cascade,
    inventory_lot_id     uuid not null references public.inventory_lots(id) on delete restrict,
    qty_consumed         numeric(12,3) not null check (qty_consumed > 0),
    unit_cost            numeric(12,4) not null check (unit_cost >= 0),
    created_at           timestamptz not null default now()
);

create index if not exists lot_consumptions_line_idx
    on public.lot_consumptions (sales_order_line_id);
create index if not exists lot_consumptions_lot_idx
    on public.lot_consumptions (inventory_lot_id);

-- =====================================================================
-- 6. RLS
-- =====================================================================

alter table public.profiles            enable row level security;
alter table public.vendors             enable row level security;
alter table public.inventory_items     enable row level security;
alter table public.invoices            enable row level security;
alter table public.invoice_line_items  enable row level security;
alter table public.inventory_lots      enable row level security;
alter table public.customers           enable row level security;
alter table public.sales_orders        enable row level security;
alter table public.sales_order_lines   enable row level security;
alter table public.lot_consumptions    enable row level security;

-- profiles: each user sees and updates their own; admins see/manage all.
drop policy if exists profiles_self_read    on public.profiles;
drop policy if exists profiles_self_update  on public.profiles;
drop policy if exists profiles_admin_all    on public.profiles;

create policy profiles_self_read on public.profiles
    for select using (id = auth.uid() or public.is_admin());

create policy profiles_self_update on public.profiles
    for update using (id = auth.uid());

create policy profiles_admin_all on public.profiles
    for all using (public.is_admin()) with check (public.is_admin());

-- Operational tables: any authenticated user can read/write.
-- (UI gates admin-only views; tighten here later if needed.)
do $$
declare
    t text;
begin
    for t in
        select unnest(array[
            'vendors',
            'inventory_items',
            'invoices',
            'invoice_line_items',
            'inventory_lots',
            'customers',
            'sales_orders',
            'sales_order_lines',
            'lot_consumptions'
        ])
    loop
        execute format('drop policy if exists %I_auth_all on public.%I;', t, t);
        execute format(
            'create policy %I_auth_all on public.%I '
            'for all '
            'using (auth.uid() is not null) '
            'with check (auth.uid() is not null);',
            t, t
        );
    end loop;
end $$;

-- =====================================================================
-- 7. Storage bucket policies (run after creating the `invoices` bucket)
-- =====================================================================
-- The `invoices` bucket must be created via the dashboard first.
-- Once created, these policies let any authenticated user upload/read
-- objects in it. Re-runnable.

drop policy if exists invoices_bucket_auth_read   on storage.objects;
drop policy if exists invoices_bucket_auth_write  on storage.objects;
drop policy if exists invoices_bucket_auth_update on storage.objects;
drop policy if exists invoices_bucket_auth_delete on storage.objects;

create policy invoices_bucket_auth_read on storage.objects
    for select using (
        bucket_id = 'invoices' and auth.uid() is not null
    );

create policy invoices_bucket_auth_write on storage.objects
    for insert with check (
        bucket_id = 'invoices' and auth.uid() is not null
    );

create policy invoices_bucket_auth_update on storage.objects
    for update using (
        bucket_id = 'invoices' and auth.uid() is not null
    );

create policy invoices_bucket_auth_delete on storage.objects
    for delete using (
        bucket_id = 'invoices' and auth.uid() is not null
    );
