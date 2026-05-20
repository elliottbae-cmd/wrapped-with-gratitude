-- Wrapped with Gratitude — migration 003
-- Add pack_size to invoice_line_items so we can audit pack expansion
-- (e.g. "ordered 1 pack of 30 bags → inventory qty 30").
-- Idempotent.

alter table public.invoice_line_items
    add column if not exists pack_size integer not null default 1
        check (pack_size >= 1);
