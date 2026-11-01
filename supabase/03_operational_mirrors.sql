-- ============================================================================
-- Abdulrahman AI OS — مرايا تشغيلية من خطة المهام (03)
--
-- شغّله في Supabase → SQL Editor → New query → Run (مرة واحدة، بعد 02).
--
-- ⚠️ المرجع: «نسخة احتياطية كاملة — خطة المهام» (2026-09-23).
--    كل جدول هنا مشتق من تاب مطابق في الـSheet. الأعمدة بأسمائها العربية
--    في الـSheet صارت أعمدة SQL إنجليزية قصيرة، والقيم النصية تبقى كما هي.
--
-- ⚠️ مستبعد عمدًا: كل «التحليل المالي» و«الهدف المالي E-S-B-I» —
--    النسخة الاحتياطية هذه هي «قبل إزالة الأرقام المالية»، أي أنها تحمل
--    أرقام دخل/دين حقيقية. لا تُرفع إلى Supabase ولا إلى أي مكان سحابي.
--    لو احتجت لوحة مالية لاحقًا: ابنها من النسخة المنقّحة (بلا أرقام)
--    وبقرار واعٍ.
--
-- مبدأ 02 ينطبق هنا: هذه مرايا مشتقة، مصدر الحقيقة هو الـSheet + state.json.
-- الاتجاه واحد: Sheet/state ──sync──▶ هذه الجداول. لا تكتب فيها يدويًا.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) projects_mirror  ←  تاب «Projects» (A1:O15)
-- ---------------------------------------------------------------------------
create table if not exists public.projects_mirror (
  project_id       text primary key,          -- PRJ-001
  owner            text        not null default 'owner',
  name             text        not null,       -- اسم المشروع
  domain           text,                       -- المجال
  goal             text,                       -- الهدف
  deliverable      text,                       -- النتيجة المطلوبة
  status           text,                       -- الحالة (النص الأصلي)
  status_norm      text        not null default 'unknown'
                   check (status_norm in ('not_started','in_progress','done','paused','cancelled','unknown')),
  priority         text,                       -- الأولوية
  current_phase    text,                       -- المرحلة الحالية
  progress_pct     numeric,                   -- نسبة الإنجاز (رقم من «35%»)
  next_step        text,
  main_blocker     text,
  decision_needed  text,
  deadline         date,
  success_criteria text,                       -- معيار النجاح
  last_update      timestamptz,
  sync_run         text        not null,
  synced_at        timestamptz not null default now(),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists projects_mirror_status_idx on public.projects_mirror (status_norm);
create index if not exists projects_mirror_deadline_idx on public.projects_mirror (deadline desc nulls last);

-- ---------------------------------------------------------------------------
-- 2) smart_inbox  ←  تاب «Smart_Inbox» (A1:M13)
--    صندوق الالتقاط: كل ما يصل قبل التصنيف. قرار عبدالرحمن حقل مستقل
--    لأن تصنيف AI مقترح فقط ولا يصبح حقيقة إلا بموافقة المالك.
-- ---------------------------------------------------------------------------
create table if not exists public.smart_inbox (
  id                       text primary key,   -- بصمة حتمية (النص+التاريخ+المصدر)
  owner                    text    not null default 'owner',
  captured_at              timestamptz,
  source                   text,               -- المصدر
  body                     text    not null,   -- النص
  suggested_classification text,              -- التصنيف المقترح (AI)
  linked_project           text,               -- المشروع المرتبط
  item_type                text,               -- نوع العنصر
  importance               text,
  urgency                  text,
  proposed_action          text,               -- الإجراء المقترح
  status                   text    not null default 'new',
  status_norm              text    not null default 'new'
                           check (status_norm in ('new','triaged','converted','dropped','unknown')),
  ai_confidence            numeric,            -- درجة ثقة AI
  owner_decision           text,               -- قرار عبدالرحمن
  sync_run                 text    not null,
  synced_at                timestamptz not null default now(),
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now()
);
create index if not exists smart_inbox_status_idx on public.smart_inbox (status_norm);
create index if not exists smart_inbox_project_idx on public.smart_inbox (linked_project) where linked_project is not null;

-- ---------------------------------------------------------------------------
-- 3) waiting_for  ←  تاب «Waiting_For» (A1:K11)
-- ---------------------------------------------------------------------------
create table if not exists public.waiting_for (
  waiting_id     text primary key,             -- WAIT-0001
  owner          text    not null default 'owner',
  item           text    not null,             -- العنصر
  waiting_on     text,                         -- بانتظار من؟
  request        text,                          -- ما المطلوب؟
  requested_at   timestamptz,
  expected_at    timestamptz,                  -- الموعد المتوقع
  followup_at    date,                          -- تاريخ المتابعة
  followup_count integer not null default 0,   -- عدد المتابعات
  status         text,
  delay_risk     text,                          -- خطر التأخير
  next_action    text,
  sync_run       text    not null,
  synced_at      timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists waiting_for_followup_idx on public.waiting_for (followup_at) where followup_at is not null;

-- ---------------------------------------------------------------------------
-- 4) blockers  ←  تاب «Blockers» (A1:K11)
-- ---------------------------------------------------------------------------
create table if not exists public.blockers (
  blocker_id         text primary key,
  owner              text    not null default 'owner',
  task_or_project    text,                     -- المهمة/المشروع
  blocker            text    not null,         -- العائق
  blocker_type       text,                     -- نوع العائق
  root_cause         text,                     -- السبب الجذري
  resolver           text,                     -- من يستطيع حله؟
  proposed_fix       text,
  cost_or_time       text,                      -- التكلفة/الوقت (نص حر)
  decision_needed    text,
  expected_resolution date,
  status             text,
  sync_run           text    not null,
  synced_at          timestamptz not null default now(),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists blockers_status_idx on public.blockers (status);

-- ---------------------------------------------------------------------------
-- 5) possibility_stack  ←  تاب «Possibility_Stack» (A1:P16)
--    فرضيات مالية/تشغيلية صغيرة قابلة للتجربة. Cost_SAR حساس نسبيًا لكنه
--    «تكلفة تجربة» لا «رقم دخل» — يُبقى هنا حتى يعمل ترتيب الأولويات.
-- ---------------------------------------------------------------------------
create table if not exists public.possibility_stack (
  possibility_id   text primary key,           -- P-001
  owner            text    not null default 'owner',
  domain           text,                        -- مالي/مهني/...
  source           text,                        -- مصدر الفرضية
  trigger          text,                        -- Trigger
  hypothesis       text,
  micro_experiment text,                        -- Micro_Experiment
  cost_sar         numeric,
  time_hours       numeric,
  expected_value   text,                        -- نص (نطاق) لا رقم دخل
  confidence       numeric,                    -- 0-100
  risk_level       text,
  success_metric   text,
  review_date      date,
  status           text,
  user_approval    text,                         -- لم تُعتمد بعد = null
  evidence_result  text,
  sync_run         text    not null,
  synced_at        timestamptz not null default now(),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists possibility_stack_review_idx on public.possibility_stack (review_date) where review_date is not null;

-- ---------------------------------------------------------------------------
-- 6) decisions  ←  تاب «القرارات» (A1:I9)
-- ---------------------------------------------------------------------------
create table if not exists public.decisions (
  id                text primary key,          -- بصمة (التاريخ+القرار)
  owner             text    not null default 'owner',
  decided_at        date,
  domain            text,                      -- المجال
  decision          text    not null,
  chosen_option     text,                      -- الخيار المعتمد
  evaluation_criteria text,
  confidence        numeric,                   -- نسبة الثقة (70 → 0.70)
  status            text,
  review_at         date,                      -- تاريخ المراجعة
  weekly_progress   text,                       -- متابعة التقدم الأسبوعي
  sync_run          text    not null,
  synced_at         timestamptz not null default now(),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists decisions_review_idx on public.decisions (review_at) where review_at is not null;

-- ---------------------------------------------------------------------------
-- 7) agent_intake / agent_conversations / agent_status_log
--    ← تابات «مدخلات الوكيل» (1371) و«محادثات الوكيل» (963) و«حالة الوكيل»
--    هذه سجلات تشغيل الآلة نفسها — قيمتها تحليلية (توكنز/زمن/أعطال)
--    لا تشغيلية. حجمها أكبر؛ زامنها بلا/Table Editor عند الحاجة فقط.
-- ---------------------------------------------------------------------------
create table if not exists public.agent_intake (
  intake_id      text primary key,             -- IN-D81017B157
  occurred_at    timestamptz,
  source         text,                         -- TELEGRAM/...
  chat_user_id   text,
  input_type     text,                         -- TEXT/VOICE/...
  raw_message    text,
  language       text,
  classification text,
  privacy        text,
  status         text,
  response_id    text,
  processed_at   timestamptz,
  error          text,
  sync_run       text    not null,
  synced_at      timestamptz not null default now()
);
create index if not exists agent_intake_time_idx on public.agent_intake (occurred_at desc);

create table if not exists public.agent_conversations (
  conversation_id text primary key,            -- CV-7398495644-127
  intake_id       text,
  occurred_at     timestamptz,
  provider        text,                         -- AWS_BEDROCK/...
  model           text,
  question        text,
  answer          text,
  input_tokens    integer,
  output_tokens   integer,
  duration_ms     integer,
  status          text,
  human_approval  text,                         -- NOT_REQUIRED/APPROVED/...
  sync_run        text    not null,
  synced_at       timestamptz not null default now()
);
create index if not exists agent_conv_time_idx on public.agent_conversations (occurred_at desc);
create index if not exists agent_conv_model_idx on public.agent_conversations (provider, model);

create table if not exists public.agent_status_log (
  id           bigint generated always as identity primary key,
  occurred_at  timestamptz,
  component    text,                            -- TELEGRAM_BOT/...
  status       text,                            -- OK/ERROR
  details      text,
  version      text,
  aws_region   text,
  bedrock_model text,
  last_check  timestamptz,
  sync_run     text    not null,
  synced_at    timestamptz not null default now()
);
create index if not exists agent_status_component_idx on public.agent_status_log (component, occurred_at desc);

-- ---------------------------------------------------------------------------
-- 8) reading_library  ←  تاب «مكتبة القراءة» (100 صف)
-- ---------------------------------------------------------------------------
create table if not exists public.reading_library (
  id            text primary key,              -- بصمة (الكتاب+الفصل+التاريخ)
  owner         text    not null default 'owner',
  book          text    not null,              -- اسم الكتاب
  chapter       text,                          -- الجزء / الفصل
  key_ideas     text,
  professional_link text,                      -- الربط المهني
  read_at       date,
  doc_file      text,                          -- ملف Doc
  checklist     boolean,
  sync_run      text    not null,
  synced_at     timestamptz not null default now(),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists reading_library_book_idx on public.reading_library (book);

-- ---------------------------------------------------------------------------
-- 9) updated_at تلقائيًا لكل الجداول أعلاه (نفس نمط 02)
-- ---------------------------------------------------------------------------
create or replace function public.mirror_touch()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
declare t text;
begin
  foreach t in array array[
    'projects_mirror','smart_inbox','waiting_for','blockers','possibility_stack',
    'decisions','agent_intake','agent_conversations','reading_library']
  loop
    execute format('drop trigger if exists %I_touch_trg on public.%I', t, t);
    execute format('create trigger %I_touch_trg before update on public.%I
                     for each row execute function public.mirror_touch()', t, t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 10) الحماية — RLS بلا سياسة على كل جدول (نفس مبدأ 02):
--     لا قراءة ولا كتابة إلا بمفتاح service_role من الخادم.
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'projects_mirror','smart_inbox','waiting_for','blockers','possibility_stack',
    'decisions','agent_intake','agent_conversations','agent_status_log','reading_library']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 11) لوحة تشغيلية واحدة للقراءة (بلا أعمدة حساسة):
--     المفتوحة + المتأخرة + بانتظار من؟ + العوائق، في استعلام واحد.
-- ---------------------------------------------------------------------------
create or replace view public.operational_dashboard
with (security_invoker = true) as
select 'task'     as kind, t.title  as label, t.status_norm, t.is_overdue, t.due_date, t.project as context
  from public.tasks_mirror t where t.is_open
union all
select 'waiting', w.item,  'unknown', false, w.followup_at, w.waiting_on
  from public.waiting_for w
union all
select 'blocker', b.blocker, 'unknown', false, b.expected_resolution, b.task_or_project
  from public.blockers b
union all
select 'decision', d.decision, 'unknown', false, d.review_at, d.domain
  from public.decisions d where d.status ilike 'قيد%';

revoke all on public.operational_dashboard from anon, authenticated;

-- ============================================================================
-- 12) التحقق بعد التشغيل (انسخ/ألصق):
--   select table_name from information_schema.tables
--   where table_schema='public' and table_name in (
--     'projects_mirror','smart_inbox','waiting_for','blockers',
--     'possibility_stack','decisions','agent_intake','agent_conversations',
--     'agent_status_log','reading_library');
--   → يجب أن ترى 10 صفوف.
--   select count(*) from pg_policies where schemaname='public'
--   and table_name in (تلك الأسماء);  → 0 (لا سياسات — كما هو مقصود)
-- ============================================================================