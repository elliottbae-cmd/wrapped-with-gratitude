-- Wrapped with Gratitude — migration 002
-- Add a flag + audit text for invoices posted with math discrepancies
-- (override-committed despite line totals or header math not tying out).
-- Idempotent: safe to re-run.

alter table public.invoices
    add column if not exists has_math_discrepancy boolean not null default false;

alter table public.invoices
    add column if not exists discrepancy_detail text;

create index if not exists invoices_discrepancy_idx
    on public.invoices (has_math_discrepancy)
    where has_math_discrepancy = true;
