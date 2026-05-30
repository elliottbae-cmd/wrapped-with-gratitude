-- Wrapped with Gratitude — migration 005
-- Allow sales_order_lines to represent SERVICE / LABOR lines (e.g. embroidery)
-- in addition to product lines that consume inventory.
--
-- Changes:
--   1. inventory_item_id becomes nullable (services have no inventory).
--   2. New line_type column: 'product' (default) or 'service'.
--   3. New description column so service lines can carry their own label
--      (product lines still derive their display name from inventory_items).
--   4. Check constraint enforces: a product line must have an inventory_item_id;
--      a service line must have a non-empty description.
--
-- Idempotent.

-- 1. Make inventory_item_id nullable.
alter table public.sales_order_lines
    alter column inventory_item_id drop not null;

-- 2. line_type column.
alter table public.sales_order_lines
    add column if not exists line_type text not null default 'product';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'sales_order_lines_type_check'
    ) then
        alter table public.sales_order_lines
            add constraint sales_order_lines_type_check
            check (line_type in ('product', 'service'));
    end if;
end$$;

-- 3. description column (free-form label for service lines).
alter table public.sales_order_lines
    add column if not exists description text;

-- 4. Either inventory_item_id (product) or non-empty description (service).
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'sales_order_lines_has_label'
    ) then
        alter table public.sales_order_lines
            add constraint sales_order_lines_has_label
            check (
                (line_type = 'product' and inventory_item_id is not null)
                or (line_type = 'service' and description is not null and trim(description) <> '')
            );
    end if;
end$$;
