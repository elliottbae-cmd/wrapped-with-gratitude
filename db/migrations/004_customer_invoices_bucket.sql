-- Wrapped with Gratitude — migration 004
-- Storage policies for the customer-invoices bucket.
-- The bucket must be created via the Supabase dashboard first
-- (Storage → New bucket → name "customer-invoices", private,
--  MIME types: application/pdf).
-- Idempotent.

drop policy if exists customer_invoices_bucket_auth_read   on storage.objects;
drop policy if exists customer_invoices_bucket_auth_write  on storage.objects;
drop policy if exists customer_invoices_bucket_auth_update on storage.objects;
drop policy if exists customer_invoices_bucket_auth_delete on storage.objects;

create policy customer_invoices_bucket_auth_read on storage.objects
    for select using (
        bucket_id = 'customer-invoices' and auth.uid() is not null
    );

create policy customer_invoices_bucket_auth_write on storage.objects
    for insert with check (
        bucket_id = 'customer-invoices' and auth.uid() is not null
    );

create policy customer_invoices_bucket_auth_update on storage.objects
    for update using (
        bucket_id = 'customer-invoices' and auth.uid() is not null
    );

create policy customer_invoices_bucket_auth_delete on storage.objects
    for delete using (
        bucket_id = 'customer-invoices' and auth.uid() is not null
    );
