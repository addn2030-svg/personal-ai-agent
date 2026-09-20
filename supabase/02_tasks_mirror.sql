-- ============================================================================
-- Abdulrahman AI OS — مرآة المهام (tasks mirror)
--
-- شغّله في Supabase → SQL Editor → New query → Run  (مرة واحدة، بعد 01)
--
-- ⚠️ اقرأ هذا أولًا: هذا الجدول **مرآة مشتقة**، وليس مصدر الحقيقة.
--    مصدر الحقيقة الوحيد للمهام يبقى data/state.json داخل النظام، لأن عليه
--    تعمل بوابة الاعتماد (action_queue) ومحرك الاستباقية والتدقيق وسجل الحلقات.
--    لو صار للمهام مصدران، يصبح لديك «حجز مزدوج»: مهمة تُغلق هنا وتبقى مفتوحة
--    هناك، ولا أحد يعرف أيّهما الصحيح.
--
--    الاتجاه واحد: state.json  ──sync──▶  tasks_mirror
--    لا تكتب في هذا الجدول يدويًا — أي صف لا يحمل بصمة آخر مزامنة يُحذف في
--    المزامنة التالية (الجدول قابل لإعادة البناء بالكامل في أي وقت).
--
-- الفائدة: تستعلم عن مهامك بـSQL، من Table Editor على جوالك، من أي أداة
-- تحليلات، أو لاحقًا من لوحة قراءة — دون المساس بمنطق النظام ولا بحوكمته.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) الجدول
-- ---------------------------------------------------------------------------
create table if not exists public.tasks_mirror (
  -- معرّف حتمي يُحسب من (العنوان + الموعد + المصدر + رقم التكرار) داخل الموصل.
  -- ثابت ما دامت هوية المهمة ثابتة، فتكون المزامنة idempotent بلا تكرار.
  id            text primary key,
  owner         text        not null default 'owner',

  -- الحقول كما في state.json (نص عربي كما هو — بلا ترجمة ولا فقدان)
  title         text        not null,
  kind          text,                       -- النوع
  priority      text,                       -- الأولوية
  status        text,                       -- الحالة (النص الأصلي)
  project       text,                       -- السياق/المشروع
  source        text,                       -- المصدر
  notes         text,                       -- ملاحظات (قد تحتوي تفاصيل حساسة)

  -- حقول مشتقة تجعل الاستعلام بسيطًا وموحّدًا (تتجنب اختلاف المفردات العربية)
  status_norm   text        not null default 'unknown'
                check (status_norm in ('not_started','in_progress','done','paused','cancelled','unknown')),
  is_open       boolean     not null default true,
  is_overdue    boolean     not null default false,
  due_date      date,

  -- بيانات المزامنة
  state_version integer,                    -- رقم إصدار state.json الذي أنتج الصف
  sync_run      text        not null,       -- بصمة دورة المزامنة (للتحديث الكامل الآمن)
  synced_at     timestamptz not null default now(),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 2) الفهارس (ما يسأل عنه البوت أكثر: مفتوحة؟ متأخرة؟ هذا الأسبوع؟)
-- ---------------------------------------------------------------------------
create index if not exists tasks_mirror_open_due_idx    on public.tasks_mirror (is_open, due_date);
create index if not exists tasks_mirror_status_idx      on public.tasks_mirror (status_norm);
create index if not exists tasks_mirror_due_idx         on public.tasks_mirror (due_date desc nulls last);
create index if not exists tasks_mirror_project_idx     on public.tasks_mirror (project) where project is not null;
create index if not exists tasks_mirror_priority_idx    on public.tasks_mirror (priority) where is_open;
create index if not exists tasks_mirror_sync_run_idx    on public.tasks_mirror (sync_run);

-- ---------------------------------------------------------------------------
-- 3) تحديث updated_at تلقائيًا (الفكرة الجيدة من الدليل الآخر)
-- ---------------------------------------------------------------------------
create or replace function public.tasks_mirror_touch()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists tasks_mirror_touch_trg on public.tasks_mirror;
create trigger tasks_mirror_touch_trg
  before update on public.tasks_mirror
  for each row execute function public.tasks_mirror_touch();

-- ---------------------------------------------------------------------------
-- 4) الحماية — RLS مفعّل وبلا أي سياسة
--
--    لا قراءة ولا كتابة إلا بالمفتاح السري (service_role) من الخادم.
--    المفتاح العام (anon/publishable) **لا يرى ولا يكتب صفًا واحدًا**، حتى لو
--    نشرتَه في متصفح. هذا هو الفرق الجوهري عن «permissive policies»: سياسة
--    متساهلة + مفتاح عام = قائمة مهامك الشخصية (وسجلّها السريري) مكشوفة للعالم.
-- ---------------------------------------------------------------------------
alter table public.tasks_mirror enable row level security;
revoke all on public.tasks_mirror from anon, authenticated;

-- ---------------------------------------------------------------------------
-- 5) عرض جاهز للقراءة (بلا ملاحظات — آمن للنشر لو أردت لوحة على الجوال)
--    ملاحظة: notes مستبعدة عمدًا لأنها قد تحمل تفاصيل صحية/سريرية.
-- ---------------------------------------------------------------------------
create or replace view public.tasks_dashboard
with (security_invoker = true) as
select id, owner, title, priority, status, status_norm, is_open, is_overdue,
       due_date, project, source, updated_at
from public.tasks_mirror;

revoke all on public.tasks_dashboard from anon, authenticated;

-- للسماح بقراءة هذا العرض بالمفتاح العام لاحقًا (لوحة جوال فقط)، أزل التعليق
-- عن السطرين التاليين — واعلم أنهما يجعلان مهامك (بلا ملاحظات) مقروءة لأي شخص
-- يملك المفتاح العام المنشور. لا تفعلها إلا بقرار واعٍ:
--   grant select on public.tasks_dashboard to anon;
--   create policy "public read dashboard view" on public.tasks_mirror
--     for select to anon using (false);   -- يبقى الجدول نفسه محجوبًا دائمًا

-- ============================================================================
-- 6) التحقق بعد التشغيل (انسخ/ألصق — يجب أن ترى الجدول والأعمدة والفهارس)
-- ============================================================================
-- أعمدة الجدول:
--   select column_name, data_type, is_nullable
--   from information_schema.columns
--   where table_schema = 'public' and table_name = 'tasks_mirror'
--   order by ordinal_position;
-- الفهارس:
--   select indexname from pg_indexes
--   where schemaname = 'public' and tablename = 'tasks_mirror' order by indexname;
-- هل RLS مفعّل؟ (rowsecurity = true، وعدد السياسات = 0)
--   select relrowsecurity as rls_enabled, relforcerowsecurity as rls_forced
--   from pg_class where oid = 'public.tasks_mirror'::regclass;
--   select count(*) as policies from pg_policies
--   where schemaname = 'public' and tablename = 'tasks_mirror';

-- ============================================================================
-- 7) استعلامات المتابعة اليومية (بعد أول مزامنة)
-- ============================================================================
-- كل المهام (الأحدث أولًا):
--   select title, status, priority, due_date, project
--   from public.tasks_mirror order by created_at desc limit 50;
--
-- توزيع الحالات:
--   select status_norm, count(*) from public.tasks_mirror group by status_norm order by 2 desc;
--
-- مهام اليوم:
--   select title, priority, project from public.tasks_mirror
--   where due_date = current_date order by priority;
--
-- المتأخرة (مفتوحة وتجاوزت موعدها) — الأهم للمتابعة:
--   select title, due_date, current_date - due_date as days_late, project
--   from public.tasks_mirror where is_overdue order by due_date;
--
-- المفتوحة بلا موعد (خطر النسيان):
--   select title, priority, project from public.tasks_mirror
--   where is_open and due_date is null order by priority;
--
-- الحمل حسب المشروع:
--   select project, count(*) filter (where is_open) as open,
--          count(*) filter (where is_overdue) as overdue
--   from public.tasks_mirror group by project order by overdue desc, open desc;
--
-- آخر مزامنة (هل البيانات حديثة؟):
--   select max(synced_at) as last_sync, count(*) as rows from public.tasks_mirror;
-- ============================================================================
