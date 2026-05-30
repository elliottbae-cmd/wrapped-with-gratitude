-- Wrapped with Gratitude — migration 007
-- Operating expenses tracking — feeds P&L (net income), BS (cash), cash flow.
-- Idempotent.

create table if not exists public.operating_expenses (
    id              uuid primary key default gen_random_uuid(),
    expense_date    date not null,
    category        text not null,
    vendor          text,
    description     text,
    amount          numeric(12,2) not null check (amount > 0),
    payment_method  text,
    notes           text,
    created_at      timestamptz not null default now(),
    created_by      uuid references auth.users(id)
);

create index if not exists operating_expenses_date_idx
    on public.operating_expenses (expense_date);
create index if not exists operating_expenses_category_idx
    on public.operating_expenses (category);

alter table public.operating_expenses enable row level security;

drop policy if exists operating_expenses_auth_all on public.operating_expenses;
create policy operating_expenses_auth_all on public.operating_expenses
    for all
    using (auth.uid() is not null)
    with check (auth.uid() is not null);
