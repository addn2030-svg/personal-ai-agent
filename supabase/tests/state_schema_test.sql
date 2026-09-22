-- ============================================================================
-- فحص تنفيذ الملفين ١ و٢ على PostgreSQL حقيقي
--
-- لماذا: `01_state_snapshots.sql` و`02_tasks_mirror.sql` كانا يُفحصان **نصًّا**
-- فقط (وجود أسماء الجداول داخل الملف) — ولم يُنفَّذا على قاعدة حقيقية قط. وأول
-- مرة يُنفَّذان فيها فعليًا هي على قاعدة بيانات المستخدم الحقيقية. هذا الفحص
-- ينقل تلك المخاطرة إلى CI.
--
-- يُشغَّل بعد الملفين على قاعدة PostgreSQL (وفيه دورَا anon/authenticated كما
-- على Supabase)، ويجري داخل معاملة ثم يتراجع فلا يترك أثرًا.
-- ============================================================================
begin;

do $$
declare
  missing text[] := '{}';
  problems text[] := '{}';
  n integer;
  acl text;
begin
  -- ١) جدول النسخ الكاملة
  if not exists (select 1 from information_schema.tables
                  where table_schema = 'public' and table_name = 'state_snapshots') then
    problems := problems || 'جدول state_snapshots غير موجود';
  end if;

  -- ٢) الأعمدة المطلوبة للموصل (الدفع والاستعادة يكتبانها بأسمائها)
  foreach missing in array array[
      'id','created_at','schema','state_version','reason','sha256','byte_size','payload']
  loop
    if not exists (select 1 from information_schema.columns
                    where table_schema='public' and table_name='state_snapshots'
                      and column_name = missing) then
      problems := problems || format('عمود مفقود في state_snapshots: %s', missing);
    end if;
  end loop;

  -- ٣) البصمة مطلوبة وفريدة المنطق: صف بلا sha256 يفسد التحقق عند الاستعادة
  if exists (select 1 from information_schema.columns
              where table_schema='public' and table_name='state_snapshots'
                and column_name='sha256' and is_nullable='YES') then
    problems := problems || 'sha256 يقبل NULL — التحقق عند الاستعادة يفقد معناه';
  end if;

  -- ٤) مرآة المهام + عمود المعرّف الحتمي + سياق المزامنة
  if not exists (select 1 from information_schema.tables
                  where table_schema = 'public' and table_name = 'tasks_mirror') then
    problems := problems || 'جدول tasks_mirror غير موجود';
  end if;
  foreach missing in array array['task_uid','sync_run','synced_at','is_open']
  loop
    if not exists (select 1 from information_schema.columns
                    where table_schema='public' and table_name='tasks_mirror'
                      and column_name = missing) then
      problems := problems || format('عمود مفقود في tasks_mirror: %s', missing);
    end if;
  end loop;

  -- ٥) عرض القراءة
  if not exists (select 1 from information_schema.views
                  where table_schema='public' and table_name='tasks_dashboard') then
    problems := problems || 'عرض tasks_dashboard غير موجود';
  end if;

  -- ٦) الفهارس (الاستعلام على الجوال/التحليلات يعتمد عليها)
  select count(*) into n from pg_indexes
   where schemaname='public' and tablename='tasks_mirror' and indexname like 'tasks_mirror_%';
  if n < 6 then
    problems := problems || format('فهارس tasks_mirror ناقصة (%s من 6)', n);
  end if;

  -- ٧) مشغّل updated_at
  if not exists (select 1 from pg_trigger
                  where tgname = 'tasks_mirror_touch_trg' and not tgisinternal) then
    problems := problems || 'مشغّل tasks_mirror_touch_trg غير موجود';
  end if;

  -- ٨) RLS مفعّل على الجدولين — لا شيء مكشوف للعام
  foreach missing in array array['state_snapshots','tasks_mirror']
  loop
    if not exists (select 1 from pg_class c join pg_namespace ns on ns.oid=c.relnamespace
                    where ns.nspname='public' and c.relname = missing and c.relrowsecurity) then
      problems := problems || format('RLS غير مفعّل على %s', missing);
    end if;
  end loop;

  -- ٩) الدور العام لا يملك أي صلاحية على الجدولين (هذا هو المعنى الحقيقي لـRLS هنا)
  foreach missing in array array['state_snapshots','tasks_mirror']
  loop
    acl := coalesce((select array_to_string(c.relacl, ' ') from pg_class c
                      join pg_namespace ns on ns.oid=c.relnamespace
                     where ns.nspname='public' and c.relname = missing), '');
    if acl like '%anon=%' or acl like '%authenticated=%' then
      problems := problems || format('الدوران anon/authenticated لهما صلاحية صريحة على %s', missing);
    end if;
  end loop;

  -- ١٠) اختبار عملي: الإدراج والقراءة يعملان فعلًا (لا مجرد وجود الجدول)
  insert into public.state_snapshots (schema, state_version, reason, sha256, byte_size, payload)
  values ('state/1', 1, 'فحص CI', repeat('a', 64), 12, '{"meta":{},"tasks":[]}'::jsonb)
  returning id into n;
  if n is null then
    problems := problems || 'الإدراج في state_snapshots لم يُعِد معرّفًا';
  end if;

  if not exists (select 1 from public.state_snapshots where sha256 = repeat('a', 64)) then
    problems := problems || 'القراءة من state_snapshots لا تُرجع ما أُدرج';
  end if;

  if coalesce(array_length(problems, 1), 0) > 0 then
    raise exception E'فحص مخطط النسخ/المرآة فشل:\n  - %', array_to_string(problems, E'\n  - ');
  end if;

  raise notice '✅ فحص الملفين ١ و٢ نجح: جداول · أعمدة · فهارس · مشغّل · RLS · إدراج وقراءة.';
end $$;

rollback;
