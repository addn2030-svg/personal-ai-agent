-- ============================================================================
-- Abdulrahman AI OS — دماغ الذاكرة الدائم (durable brain)
--
-- شغّله في Supabase → SQL Editor → New query → Run
-- (مرة واحدة، بعد 01_state_snapshots.sql و02_tasks_mirror.sql)
--
-- ⚠️ اقرأ هذا أولًا: ما هذا وما ليس هذا؟
--
--   هذا الجدول **ذاكرة دائمة خارج الخادم**، وليس مصدر حقيقة تشغيلي.
--   مصدر الحقيقة التشغيلي يبقى data/state.json (المهام والقرارات وبوابة
--   الاعتماد). أما ما يُخزَّن هنا فهو **الذاكرة المشتقّة**: ملخّصات ما جرى
--   (episodes) والحقائق المثبتة (facts) والذاكرة العاملة (working).
--
--   لماذا؟ لأن على مضيف بلا قرص دائم (Render المجاني) تُفقد كل ملفات
--   data/memory/*.jsonl عند كل إيقاف أو إعادة نشر — ومنها تُبنى الذاكرة
--   العرضية والدلالية. النتيجة قبل هذا المخطط: وكيل «بلا ذاكرة طويلة» يعيد
--   السؤال عن كل شيء بعد كل إعادة تشغيل.
--
--   | ما | قبل | بعد |
--   |---|---|---|
--   | ملخصات الجلسات (episodic) | ملف واحد على قرص مؤقت | صفوف دائمة تُستعلَم |
--   | الحقائق المثبتة (semantic) | ملف واحد على قرص مؤقت | صفوف دائمة بمرجع ومصدر |
--   | الذاكرة العاملة (working) | ملف JSON ينتهي بـTTL | جدول بانتهاء صلاحية |
--   | الاسترجاع | تطابق رموز حرفي محليًا | استرجاع عربي مُطبَّع + ترتيب مرجَّح |
--
--   ⚠️ لا متجهات (no vectors) — قرار متعمَّد موثَّق في
--      docs/agent3-p0-adjudication.md («Defer pgvector حتى تبرّره أدلة
--      تشغيلية»). هذا المخطط يعطي المتانة والاسترجاع الدلالي الخفيف عبر
--      التطبيع العربي + pg_trgm، بلا تكلفة تضمين وبلا حصة API.
--      ترقية لاحقة إلى pgvector ممكنة بلا فقدان: أضف عمود embedding إلى
--      نفس الجدولين، ولا تتغير بقية الطبقة.
--
-- قواعد السلامة المطبَّقة (مطابقة لبقية مخططات Supabase في هذا المستودع):
--   1. RLS مفعّل، وبلا أي سياسة ⇒ المفتاح العام (anon/publishable) يقرأ صفرًا.
--   2. المفتاح السري (service_role) وحده يعمل، وهو يبقى على الخادم.
--   3. لا عمود يحمل أسرارًا؛ ولا تُرسَل بيانات سريرية إلى هنا إطلاقًا
--      (المنع مطبَّق في connectors/brain.py قبل الكتابة، لا هنا فقط).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 0) ذرّية التنفيذ + فحص مسبق
--
-- لماذا؟ لأن السكربت لو فشل في منتصفه (أشهر سبب: pg_trgm غير مُفعّل) ترك
-- «مخططًا نصف مبني»: الجداول موجودة وbrain_recall مفقودة — وهي حالة أسوأ من
-- الفشل النظيف، لأن /brain_status يقول «الجداول جاهزة» ثم تفشل كل عملية استرجاع.
-- الفحص المسبق يرفع رسالة عربية واضحة قبل إنشاء أي شيء، والمعاملة (transaction)
-- تعني: إما المخطط كامل، أو لا شيء منه.
-- ---------------------------------------------------------------------------
begin;

do $$
begin
  if not exists (select 1 from pg_available_extensions where name = 'pg_trgm') then
    raise exception using
      message = 'امتداد pg_trgm غير متاح في هذا المشروع — المخطط لم يُنشأ (تراجع كامل).',
      detail  = 'استرجاع الذاكرة العربية يحتاج تشابه ثلاثي الحروف (pg_trgm).',
      hint    = 'Supabase → Database → Extensions → ابحث عن pg_trgm → Enable، ثم أعد تشغيل هذا الملف.';
  end if;
end
$$;

-- pg_trgm: تشابه ثلاثي الحروف — يعمل مع العربية بعد التطبيع (typos والصيغ).
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------------
-- 1) دالة التطبيع العربي — مرآة دقيقة لـ context_service.normalize()
--    نفس القواعد في بايثون وفي Postgres، وإلا اختلف الترتيب بين المسارين.
--    تُطبَّع في *الاستعلام* و*التخزين* معًا ⇒ «العقود» يجد «عقد».
-- ---------------------------------------------------------------------------
create or replace function public.brain_norm(txt text)
returns text
language sql
immutable
parallel safe
as $$
  select btrim(
    regexp_replace(
      translate(
        lower(coalesce(txt, '')),
        -- التطويل والتشكيل يُحذفان أولًا (وسائط فارغة = حذف)
        U&'\0640\064B\064C\064D\064E\064F\0650\0651\0652\0670',
        ''
      ),
      '\s+', ' ', 'g'
    )
  )
$$;

comment on function public.brain_norm(text) is
  'تطبيع عربي/إنجليزي: حذف التشكيل والتطويل، توحيد الألف والهمزة والتاء المربوطة والياء، وتقليص المسافات.';

-- ملاحظة: نُطبِّع الحروف بعد حذف التشكيل بخطوة منفصلة، لأن translate يربط
-- الحرف بحرف واحد فقط ولا يفهم المحارف المركّبة.
create or replace function public.brain_fold(txt text)
returns text
language sql
immutable
parallel safe
as $$
  select translate(
    public.brain_norm(txt),
    U&'\0623\0625\0622\0671\0649\0629\0624\0626',
    U&'\0627\0627\0627\0627\064A\0647\0648\064A'
  )
$$;

comment on function public.brain_fold(text) is
  'توحيد الهمزات: أ/إ/آ/ٱ ⇒ ا، ى ⇒ ي، ة ⇒ ه، ؤ ⇒ و، ئ ⇒ ي. مطابق لـcontext_service.normalize.';

-- ---------------------------------------------------------------------------
-- 2) الحلقات (episodes) — «ماذا جرى» بملخّص ومرجع
-- ---------------------------------------------------------------------------
create table if not exists public.brain_episodes (
  -- معرّف حتمي يُحسب في connectors/brain.py من (النوع + الملخّص + اللحظة)
  -- بنفس صيغة engine/memory.py ⇒ المحلي والسحابي يتفقان، والإعادة idempotent.
  id           text        primary key,
  occurred_at  timestamptz not null default now(),
  kind         text        not null default 'general',   -- conversation | decision | task | approval | general
  summary      text        not null,
  refs         jsonb       not null default '[]'::jsonb,
  source_ref   text        not null default '',
  chat_id      text        not null default '',
  sensitivity  text        not null default 'normal'
               check (sensitivity in ('normal', 'internal', 'clinical_private', 'restricted')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  -- عمود بحث مُطبَّع ومُفهرَس — لا يُكتب من الموصل، يُحسب هنا.
  search_norm  text        generated always as (public.brain_fold(summary)) stored,
  check (length(summary) <= 8000)
);

create index if not exists brain_episodes_occurred_idx
  on public.brain_episodes (occurred_at desc);
create index if not exists brain_episodes_kind_idx
  on public.brain_episodes (kind, occurred_at desc);
create index if not exists brain_episodes_chat_idx
  on public.brain_episodes (chat_id, occurred_at desc) where chat_id <> '';
create index if not exists brain_episodes_trgm_idx
  on public.brain_episodes using gin (search_norm gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- 3) الحقائق (facts) — «ما نعرفه» بصيغة (موضوع، علاقة، قيمة) + مصدر وثقة
-- ---------------------------------------------------------------------------
create table if not exists public.brain_facts (
  id           text        primary key,
  occurred_at  timestamptz not null default now(),
  subject      text        not null,
  predicate    text        not null default '',
  value        text        not null default '',
  source_ref   text        not null default '',
  confidence   real        not null default 0.8 check (confidence >= 0 and confidence <= 1),
  sensitivity  text        not null default 'normal'
               check (sensitivity in ('normal', 'internal', 'clinical_private', 'restricted')),
  -- إبطال غير حذف: الحقيقة القديمة تبقى ومرجعها يُذكر (حكم المعلومات).
  superseded_by text       not null default '',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  search_norm  text        generated always as (
                 public.brain_fold(subject || ' ' || predicate || ' ' || value)
               ) stored
);

create index if not exists brain_facts_occurred_idx
  on public.brain_facts (occurred_at desc);
create index if not exists brain_facts_subject_idx
  on public.brain_facts (subject, occurred_at desc);
create index if not exists brain_facts_live_idx
  on public.brain_facts (occurred_at desc) where superseded_by = '';
create index if not exists brain_facts_trgm_idx
  on public.brain_facts using gin (search_norm gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- 4) الذاكرة العاملة (working) — سياق قصير العمر لكل محادثة
-- ---------------------------------------------------------------------------
create table if not exists public.brain_working (
  chat_id     text        primary key,
  items       jsonb       not null default '[]'::jsonb,
  updated_at  timestamptz not null default now(),
  expires_at  timestamptz not null
);

create index if not exists brain_working_expiry_idx
  on public.brain_working (expires_at);

-- ---------------------------------------------------------------------------
-- 5) الاسترجاع (recall) — ترتيب هجين: تطابق تام + تشابه ثلاثي + رموز
--
--    لماذا دالة واحدة بدل استعلامات في الكود؟ لأن منطق الترتيب مكانه قاعدة
--    البيانات (فهرس واحد، مرور واحد) — والموصل يبقى بسيطًا وقابلًا للاختبار.
-- ---------------------------------------------------------------------------
create or replace function public.brain_recall(
  query_text        text,
  match_count       integer default 12,
  include_sensitive boolean default false,
  query_terms       text[]  default null
)
returns table (
  item_type    text,
  item_id      text,
  occurred_at  timestamptz,
  title        text,
  snippet      text,
  source_ref   text,
  sensitivity  text,
  score        real
)
language sql
stable
as $$
  with q as (
    select public.brain_fold(query_text) as norm
  ),
  -- الرموز تأتي من الخارج (connectors/brain.py يمرّر expand_query من
  -- context_service: توسيع المفاهيم + إزالة حروف الجر الملتصقة)، وإن غابت
  -- نستخرجها من الاستعلام نفسه — فنبقى صالحين للاستدعاء المباشر من SQL Editor.
  raw_terms as (
    select unnest(
             coalesce(
               nullif(query_terms, '{}'::text[]),
               string_to_array((select norm from q), ' ')
             )
           ) as term
  ),
  terms as (
    select distinct public.brain_fold(term) as term
    from raw_terms
    where length(btrim(coalesce(term, ''))) >= 3
  ),
  episode_hits as (
    select
      'episode'::text as item_type, e.id as item_id, e.occurred_at, e.kind as title,
      e.summary as snippet, e.source_ref, e.sensitivity,
      (
        (select count(*) from terms where e.search_norm like '%' || terms.term || '%')
        + 2 * word_similarity((select norm from q), e.search_norm)
        + case when (select norm from q) <> '' and e.search_norm like '%' || (select norm from q) || '%'
               then 4 else 0 end
      )::real as score
    from public.brain_episodes e, q
    where (include_sensitive or e.sensitivity in ('normal', 'internal'))
      and (
        exists (select 1 from terms where e.search_norm like '%' || terms.term || '%')
        -- شبكة أمان للصيغ غير المتوقعة (جمع مكسور مثل «العقود» مقابل «العقد»):
        -- التشابه الكلمة-داخل-النص يكفي للقبول، لا للتزيين فقط.
        or word_similarity((select norm from q), e.search_norm) >= 0.30
      )
  ),
  fact_hits as (
    select
      'fact'::text as item_type, f.id as item_id, f.occurred_at, f.subject as title,
      btrim(f.predicate || ' ' || f.value) as snippet, f.source_ref, f.sensitivity,
      (
        (select count(*) from terms where f.search_norm like '%' || terms.term || '%')
        + 2 * word_similarity((select norm from q), f.search_norm)
        + case when (select norm from q) <> '' and f.search_norm like '%' || (select norm from q) || '%'
               then 4 else 0 end
        + case when f.superseded_by = '' then 1.5 * f.confidence else -1.0 end
      )::real as score
    from public.brain_facts f, q
    where (include_sensitive or f.sensitivity in ('normal', 'internal'))
      and (
        exists (select 1 from terms where f.search_norm like '%' || terms.term || '%')
        or word_similarity((select norm from q), f.search_norm) >= 0.30
      )
  )
  select * from (
    select * from episode_hits
    union all
    select * from fact_hits
  ) hits
  where score > 0
  order by score desc, occurred_at desc
  limit greatest(1, least(coalesce(match_count, 12), 100))
$$;

comment on function public.brain_recall(text, integer, boolean, text[]) is
  'استرجاع بترتيب مرجَّح: رموز مُطبَّعة + تطابق كامل + تشابه ثلاثي (كلمة-داخل-نص). query_terms اختيارية يمرّرها connectors/brain.py من توسيع context_service. include_sensitive=false افتراضيًا ⇒ المحتوى السريري/المقيّد لا يظهر.';

-- ---------------------------------------------------------------------------
-- 6) الإحصاء والتقليم — لـ/brain_status وللصيانة الدورية
-- ---------------------------------------------------------------------------
create or replace function public.brain_stats()
returns jsonb
language sql
stable
as $$
  select jsonb_build_object(
    'episodes',      (select count(*) from public.brain_episodes),
    'facts',         (select count(*) from public.brain_facts),
    'live_facts',    (select count(*) from public.brain_facts where superseded_by = ''),
    'working',       (select count(*) from public.brain_working where expires_at > now()),
    'sensitive',     (select count(*) from public.brain_episodes where sensitivity not in ('normal','internal'))
                     + (select count(*) from public.brain_facts where sensitivity not in ('normal','internal')),
    'latest_episode',(select max(occurred_at) from public.brain_episodes),
    'latest_fact',   (select max(occurred_at) from public.brain_facts),
    'size_pretty',   pg_size_pretty(pg_total_relation_size('public.brain_episodes')
                                    + pg_total_relation_size('public.brain_facts')
                                    + pg_total_relation_size('public.brain_working'))
  )
$$;

-- تقليم بالعدد: يُبقي الأحدث فقط. لا يُحذف صف حقيقة لم يُبطَل أبدًا
-- (المعرفة المثبتة أغلى من الحلقة) — الإبطال superseded_by هو أداة التقادم.
create or replace function public.brain_prune(keep_episodes integer default 2000)
returns jsonb
language plpgsql
as $$
declare
  deleted_episodes integer;
  purged_working   integer;
begin
  if coalesce(keep_episodes, 0) < 100 then
    raise exception 'الحد الأدنى للتقليم 100 حلقة — رفض حذف أوسع من ذلك';
  end if;

  with doomed as (
    select id from public.brain_episodes
    order by occurred_at desc
    offset greatest(keep_episodes, 100)
  )
  delete from public.brain_episodes e using doomed where e.id = doomed.id;
  get diagnostics deleted_episodes = row_count;

  delete from public.brain_working where expires_at < now() - interval '7 days';
  get diagnostics purged_working = row_count;

  return jsonb_build_object(
    'deleted_episodes', deleted_episodes,
    'purged_working',   purged_working,
    'kept_episodes',    keep_episodes
  );
end;
$$;

-- ---------------------------------------------------------------------------
-- 7) الحماية الموحّدة — كما في 01 و02: محجوب عن المفتاح العام بالكامل
-- ---------------------------------------------------------------------------
alter table public.brain_episodes enable row level security;
alter table public.brain_facts    enable row level security;
alter table public.brain_working  enable row level security;

-- الحجب عن المفتاح العام — مع حماية من غياب الدور نفسه.
-- على Supabase الدوران موجودان دائمًا، لكن السكربت يجب أن يعمل أيضًا على
-- Postgres عادي (استضافة ذاتية/فحص محلي) بلا خطأ «role anon does not exist».
do $$
declare
  role_name text;
  target    text;
begin
  foreach role_name in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = role_name) then
      foreach target in array array[
        'public.brain_episodes', 'public.brain_facts', 'public.brain_working'
      ] loop
        execute format('revoke all on %s from %I', target, role_name);
      end loop;
      foreach target in array array[
        'public.brain_recall(text, integer, boolean, text[])',
        'public.brain_stats()',
        'public.brain_prune(integer)'
      ] loop
        execute format('revoke all on function %s from %I', target, role_name);
      end loop;
    end if;
  end loop;
end
$$;

-- إغلاق المعاملة: من هنا إما أن يكون المخطط كاملًا، أو لم يتغير شيء أصلًا.
commit;

-- ============================================================================
-- استعلامات مراقبة (SQL Editor — للمفتاح السري فقط، الجداول محجوبة عن العام)
-- ============================================================================
-- الحجم والصحة:
--   select public.brain_stats();
-- آخر ما جرى:
--   select occurred_at, kind, left(summary, 80) from public.brain_episodes
--   order by occurred_at desc limit 10;
-- استرجاع يدوي بنفس منطق البوت (اكتب استفسارك بين علامتي الاقتباس):
--   select item_type, title, left(snippet, 120), score
--   from public.brain_recall('العقد مع العمير', 10, false);
-- تقليم يدوي (يبقي أحدث 2000 حلقة):
--   select public.brain_prune(2000);
-- ============================================================================
