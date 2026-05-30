-- Wrapped with Gratitude — migration 006
-- Marketing module: photo studio + future email campaigns.
--
-- Includes: marketing_photos table (gallery of original + enhanced images
-- plus the chosen caption), and storage policies for the new
-- `marketing-photos` bucket (create the bucket via dashboard first).
-- Idempotent.

create table if not exists public.marketing_photos (
    id              uuid primary key default gen_random_uuid(),
    original_path   text,
    enhanced_path   text not null,
    backdrop        text,
    caption_text    text,
    caption_tone    text,
    sale_order_id   uuid references public.sales_orders(id) on delete set null,
    notes           text,
    created_at      timestamptz not null default now(),
    created_by      uuid references auth.users(id)
);

create index if not exists marketing_photos_created_idx
    on public.marketing_photos (created_at desc);

alter table public.marketing_photos enable row level security;

drop policy if exists marketing_photos_auth_all on public.marketing_photos;
create policy marketing_photos_auth_all on public.marketing_photos
    for all
    using (auth.uid() is not null)
    with check (auth.uid() is not null);

-- Storage bucket policies for `marketing-photos`.
-- The bucket must exist before these policies attach.
drop policy if exists marketing_photos_bucket_auth_read   on storage.objects;
drop policy if exists marketing_photos_bucket_auth_write  on storage.objects;
drop policy if exists marketing_photos_bucket_auth_update on storage.objects;
drop policy if exists marketing_photos_bucket_auth_delete on storage.objects;

create policy marketing_photos_bucket_auth_read on storage.objects
    for select using (
        bucket_id = 'marketing-photos' and auth.uid() is not null
    );

create policy marketing_photos_bucket_auth_write on storage.objects
    for insert with check (
        bucket_id = 'marketing-photos' and auth.uid() is not null
    );

create policy marketing_photos_bucket_auth_update on storage.objects
    for update using (
        bucket_id = 'marketing-photos' and auth.uid() is not null
    );

create policy marketing_photos_bucket_auth_delete on storage.objects
    for delete using (
        bucket_id = 'marketing-photos' and auth.uid() is not null
    );
