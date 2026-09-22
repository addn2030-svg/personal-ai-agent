-- ============================================================================
-- فحص تنفيذ الملفين ١ و٢ على PostgreSQL حقيقي
--
-- لماذا: `01_state_snapshots.sql` و`02_tasks_mirror.sql` كانا يُفحصان **نصًّا**
-- فقط (وجود أسماء الجداول داخل الملف) — ولم يُنفَّذا على قاعدة حقيقية قط. وأول
-- مرة يُنفَّذان فيها فعليًا كانت ستكون على قاعدة بيانات المستخدم الحقيقية. هذا
-- الفحص ينقل تلك المخاطرة إلى CI وإلى أي جهاز فيه PostgreSQL.
--
-- يُشغَّل بعد الملفين على قاعدة PostgreSQL (وفيه دورَا anon/authenticated كما
-- على Supabase)، ويجري داخل معاملة ثم يتراجع فلا يترك أثرًا.
-- ============================================================================
begin;

do $$
declare
  item text;
  problems text[] := '{}';
  n integer;
  acl text;
begin
  -- ١) جدول النسخ الكاملة
  if not exists (select 1 from information_schema.tables
                  where table_schema = 'public' and table_name = 'state_snapshots') then
    problems := array_append(problems, 'جدول state_snapshots غير موجود');
  end if;

  -- ٢) الأعمدة المطلوبة للموصل (الدفع والاستعادة يكتبانها بأسمائها)
  foreach item in array array[
      'id','created_at','schema','state_version','reason','sha256','byte_size','payload']
  loop
    if not exists (select 1 from information_schema.columns
                    where table_schema = 'public' and table_name = 'state_snapshots'
                      and column_name = item) then
      problems := array_append(problems, format('عمود مفقود في state_snapshots: %s', item));
    end if;
  end loop;

  -- ٣) البصمة لا تقبل NULL: صف بلا sha256 يفقد التحقق عند الاستعادة معناه
  if exists (select 1 from information_schema.columns
              where table_schema = 'public' and table_name = 'state_snapshots'
                and column_name = 'sha256' and is_nullable = 'YES') then
    problems := array_append(problems, 'sha256 يقبل NULL — التحقق عند الاستعادة يفقد معناه');
  end if;

  -- ٤) مرآة المهام + المعرّف الحتمي + سياق المزامنة
  if not exists (select 1 from information_schema.tables
                  where table_schema = 'public' and table_name = 'tasks_mirror') then
    problems := array_append(problems, 'جدول tasks_mirror غير موجود');
  end if;
  foreach item in array array['id','sync_run','synced_at','is_open','status_norm']
  loop
    if not exists (select 1 from information_schema.columns
                    where table_schema = 'public' and table_name = 'tasks_mirror'
                      and column_name = item) then
      problems := array_append(problems, format('عمود مفقود في tasks_mirror: %s', item));
    end if;
  end loop;

  -- ٥) عرض القراءة
  if not exists (select 1 from information_schema.views
                  where table_schema = 'public' and table_name = 'tasks_dashboard') then
    problems := array_append(problems, 'عرض tasks_dashboard غير موجود');
  end if;

  -- ٦) الفهارس (الاستعلام من الجوال أو أي أداة تحليلات يعتمد عليها)
  select count(*) into n from pg_indexes
   where schemaname = 'public' and tablename = 'tasks_mirror'
     and indexname like 'tasks_mirror_%';
  if n < 6 then
    problems := array_append(problems, format('فهارس tasks_mirror ناقصة (%s من 6)', n));
  end if;

  -- ٧) مشغّل updated_at
  if not exists (select 1 from pg_trigger
                  where tgname = 'tasks_mirror_touch_trg' and not tgisinternal) then
    problems := array_append(problems, 'مشغّل tasks_mirror_touch_trg غير موجود');
  end if;

  -- ٨) RLS مفعّل على الجدولين — لا شيء مكشوف للعام
  foreach item in array array['state_snapshots','tasks_mirror']
  loop
    if not exists (select 1 from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
                    where ns.nspname = 'public' and c.relname = item and c.relrowsecurity) then
      problems := array_append(problems, format('RLS غير مفعّل على %s', item));
    end if;
  end loop;

  -- ٩) الدور العام لا يملك صلاحية صريحة على الجدولين
  foreach item in array array['state_snapshots','tasks_mirror']
  loop
    acl := coalesce((select array_to_string(c.relacl, ' ') from pg_class c
                      join pg_namespace ns on ns.oid = c.relnamespace
                     where ns.nspname = 'public' and c.relname = item), '');
    if acl like '%anon=%' or acl like '%authenticated=%' then
      problems := array_append(problems, format('الدوران anon/authenticated لهما صلاحية صريحة على %s', item));
    end if;
  end loop;

  -- ١٠) اختبار عملي: الإدراج والقراءة يعملان فعلًا (لا مجرد وجود الجدول)
  -- محميّ بشرط الوجود: لو غاب الجدول، الرسالة المطلوبة هي «الجدول غير موجود»
  -- لا خطأ SQL غامض من عبارة الإدراج.
  if exists (select 1 from information_schema.tables
              where table_schema = 'public' and table_name = 'state_snapshots') then
    insert into public.state_snapshots (schema, state_version, reason, sha256, byte_size, payload)
    values ('state/1', 1, 'فحص CI', repeat('a', 64), 12, '{"meta":{},"tasks":[]}'::jsonb)
    returning id into n;
    if n is null then
      problems := array_append(problems, 'الإدراج في state_snapshots لم يُعِد معرّفًا');
    end if;
    if not exists (select 1 from public.state_snapshots where sha256 = repeat('a', 64)) then
      problems := array_append(problems, 'القراءة من state_snapshots لا تُرجع ما أُدرج');
    end if;
  end if;

  -- ١١) نفس الاختبار على المرآة: الإدراج + مشغّل updated_at
  -- ملاحظة عن المنهج: داخل معاملة واحدة يكون `now()` ثابتًا، فلا يصلح فحص
  -- «updated_at أحدث من created_at» (سيتساويان دائمًا). فنكتب قيمة قديمة صراحةً
  -- ونفحص أن المشغّل **دهسها**: هذا هو الأثر الذي لا يمكن أن يظهر بلا مشغّل عامل.
  if exists (select 1 from information_schema.tables
              where table_schema = 'public' and table_name = 'tasks_mirror') then
  insert into public.tasks_mirror (id, title, status_norm, is_open, sync_run)
  values ('ci-test-uid', 'مهمة فحص', 'not_started', true, 'فحص CI');
  if not exists (select 1 from public.tasks_mirror where id = 'ci-test-uid') then
    problems := array_append(problems, 'الإدراج في tasks_mirror لا يُرجع الصف');
  end if;
  update public.tasks_mirror
     set title = 'مهمة فحص معدّلة', updated_at = timestamptz '2000-01-01'
   where id = 'ci-test-uid';
  if not exists (select 1 from public.tasks_mirror
                  where id = 'ci-test-uid' and updated_at > timestamptz '2000-01-02') then
    problems := array_append(problems, 'مشغّل updated_at لا يعمل على tasks_mirror');
  end if;
  end if;

  if coalesce(array_length(problems, 1), 0) > 0 then
    raise exception E'فحص مخطط النسخ/المرآة فشل:\n  - %', array_to_string(problems, E'\n  - ');
  end if;

  raise notice '✅ فحص الملفين ١ و٢ نجح: جداول · أعمدة · فهارس · مشغّل · RLS · إدراج وقراءة وتحديث.';
end $$;

rollback;
