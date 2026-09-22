-- ============================================================================
-- Abdulrahman AI OS — فحوص سلوك مخطط الدماغ (اختبار حقيقي على PostgreSQL)
--
-- لماذا هذا الملف موجود؟
--   المخطط `03_brain_memory.sql` لم يكن قد نُفِّذ على قاعدة بيانات فعلية قبل
--   كتابة هذه الفحوص — وهذا الفرق بين «يبدو صحيحًا» و«يعمل». هذه الفحوص تُشغَّل
--   آليًا في CI على PostgreSQL حقيقي مع pg_trgm الحقيقي (انظر
--   .github/workflows/brain-schema.yml)، ويمكن تشغيلها يدويًا في
--   Supabase → SQL Editor.
--
-- آمن على مشروع حقيقي: كل البيانات التجريبية داخل معاملة تُلغى في النهاية
--   (rollback)، فلا يُترك صف واحد ولا يتغير شيء. والفشل يظهر كرسالة عربية.
--
-- التشغيل:  psql -v ON_ERROR_STOP=1 -f supabase/tests/brain_schema_test.sql
--           (أو الصق الملف كاملًا في SQL Editor)
-- ============================================================================

begin;

-- ------------------------------------------------------------------ البيانات
insert into public.brain_episodes (id, occurred_at, kind, summary, source_ref, sensitivity)
values
  ('TEST-EP-1', now() - interval '2 days', 'decision',
   'ناقشنا مسودة العقد مع مؤسسة العمير وأضفنا تحفظات على بند الراتب', 'test:1', 'normal'),
  ('TEST-EP-2', now() - interval '1 day', 'meeting',
   'اجتماع فريق التأهيل الأسبوعي لمناقشة جدول الجلسات', 'test:2', 'normal'),
  ('TEST-EP-3', now(), 'clinical',
   'ملاحظة سريرية عن حالة مريض يعاني ألم أسفل الظهر', 'test:3', 'clinical_private');

insert into public.brain_facts (id, occurred_at, subject, predicate, value, source_ref, confidence, sensitivity)
values
  ('TEST-SM-1', now() - interval '3 days', 'العقد', 'الحالة', 'بانتظار تحفظات العمير', 'test:4', 0.9, 'normal'),
  ('TEST-SM-2', now() - interval '9 days', 'العقد', 'الراتب', 'مرفوض سابقًا', 'test:4', 0.9, 'normal'),
  ('TEST-SM-3', now(), 'المريض', 'ملاحظة', 'بيانات محمية', 'test:5', 0.9, 'clinical_private');

-- الإبطال: الحقيقة القديمة تبقى ومرجعها يُذكر (حكم المعلومات) لكن ترتيبها ينزل.
update public.brain_facts set superseded_by = 'TEST-SM-1' where id = 'TEST-SM-2';

-- ------------------------------------------------------------------- الفحوص
do $$
declare
  found_ids     text;
  live_score    real;
  old_score     real;
  sensitive_cnt integer;
  lowered       text;
begin
  -- 1) التطبيع العربي: مرآة context_service.normalize في بايثون
  if public.brain_norm('مُبْرَمَة') <> 'مبرمة' then
    raise exception 'brain_norm لا يحذف التشكيل: %', public.brain_norm('مُبْرَمَة');
  end if;
  if public.brain_fold('العُقُــود المُبْرَمَة مع العُمَيْر') <> 'العقود المبرمه مع العمير' then
    raise exception 'brain_fold لا يوحّد الهمزات/التاء/التطويل: %',
      public.brain_fold('العُقُــود المُبْرَمَة مع العُمَيْر');
  end if;

  -- 2) الاسترجاع يصل إلى الحلقة الصحيحة
  select string_agg(item_id, ',') into found_ids
  from public.brain_recall('العقد مع العمير', 10, false,
                           array['العقد','عقد','العمير','عمير','اتفاق','شراكة']);
  if found_ids is null or position('TEST-EP-1' in found_ids) = 0 then
    raise exception 'الاسترجاع لم يصل إلى TEST-EP-1 (وجد: %)', coalesce(found_ids, 'لا شيء');
  end if;

  -- 3) المحتوى السريري محجوب افتراضيًا ومسموح بالطلب الصريح فقط
  select count(*) into sensitive_cnt
  from public.brain_recall('ملاحظة سريرية', 20, false);
  if sensitive_cnt <> 0 then
    raise exception 'الاسترجاع الافتراضي أظهر % من المحتوى السريري', sensitive_cnt;
  end if;
  select count(*) into sensitive_cnt
  from public.brain_recall('ملاحظة سريرية', 20, true);
  if sensitive_cnt = 0 then
    raise exception 'الطلب الصريح include_sensitive=true لم يُظهر المحتوى السريري';
  end if;

  -- 4) الصيغ الشائعة: جمع مكسور «العقود» وصيغة ملتصقة «والعقد»
  select coalesce(string_agg(item_id, ','), '') into lowered
  from public.brain_recall('العقود', 10, false);
  if position('TEST-SM-1' in lowered) = 0 and position('TEST-EP-1' in lowered) = 0 then
    raise exception 'الجمع المكسور «العقود» لم يصل إلى «العقد» (وجد: %)', lowered;
  end if;

  -- 5) الإبطال يُنزّل الحقيقة القديمة بلا أن يخفيها
  select h.score into live_score from public.brain_recall('العقد', 20, false) h
   where h.item_id = 'TEST-SM-1';
  select h.score into old_score from public.brain_recall('العقد', 20, false) h
   where h.item_id = 'TEST-SM-2';
  if live_score is null then
    raise exception 'الحقيقة السارية TEST-SM-1 غير مسترجَعة';
  end if;
  if old_score is not null and old_score >= live_score then
    raise exception 'المُبطَلة (%) لم تُنزَّل أمام السارية (%)', old_score, live_score;
  end if;

  -- 6) المصطلحات تُقبل من الخارج، وإن غابت يُستخرج الاستعلام رموزه بنفسه
  if (select count(*) from public.brain_recall('العقد', 10, false, null)) = 0 then
    raise exception 'الاستدعاء بلا query_terms أعاد صفرًا — استخراج الرموز الداخلي معطّل';
  end if;

  -- 7) نداء تافه لا يعيد شيئًا (لا نتائج عشوائية)
  if (select count(*) from public.brain_recall('وصفة طبخ إيطالي', 10, false)) <> 0 then
    raise exception 'استعلام غير ذي صلة أعاد نتائج';
  end if;
end
$$;

-- 8) الإحصاء والتقليم
do $$
declare
  stats    jsonb;
  pruned   jsonb;
  rejected boolean;
begin
  stats := public.brain_stats();
  if (stats ->> 'episodes')::int < 3 then
    raise exception 'brain_stats لا يعدّ الحلقات: %', stats;
  end if;
  if not (stats ? 'sensitive') or (stats ->> 'sensitive')::int < 2 then
    raise exception 'brain_stats لا يعدّ المحتوى الحساس: %', stats;
  end if;

  -- حدّ أدنى يمنع الحذف الواسع بالخطأ.
  -- ⚠️ صياغة مقصودة: نلتقط الخطأ في راية (rejected) ثم نقرّر بعدها. الالتقاط
  -- ثم التجاهل المباشر كان يجعل الفحص ينجح حتى مع الخلل — وفحص لا يستطيع الفشل
  -- ليس فحصًا. هنا: إن مرّ الطلب بلا اعتراض ⇒ نرفع استثناءً يُسقط الاختبار.
  rejected := false;
  begin
    perform public.brain_prune(10);
  exception
    when others then
      rejected := true;
      if position('100' in sqlerrm) = 0 then
        raise exception 'رسالة رفض التقليم لا تذكر الحد الأدنى 100: %', sqlerrm;
      end if;
  end;
  if not rejected then
    raise exception 'brain_prune(10) مرّ بلا اعتراض — يجب رفض حد أقل من 100';
  end if;

  pruned := public.brain_prune(100);
  if (pruned ->> 'deleted_episodes')::int <> 0 then
    raise exception 'brain_prune حذف صفوفًا في قاعدة تحمل أقل من 100 حلقة: %', pruned;
  end if;
  -- الحقيقة المثبتة لا تُحذف بالتقليم — الإبطال هو أداة التقادم
  if (select count(*) from public.brain_facts where id like 'TEST-%') <> 3 then
    raise exception 'التقليم مسّ الحقائق';
  end if;
end
$$;

-- 9) الحماية: RLS مفعّل والمفتاح العام محجوب (يُتخطّى إن لم يوجد الدوران)
do $$
declare
  t text;
  r text;
  leaked text := '';
begin
  foreach t in array array['brain_episodes', 'brain_facts', 'brain_working'] loop
    if not (select relrowsecurity from pg_class where oid = format('public.%s', t)::regclass) then
      raise exception 'RLS غير مفعّل على %', t;
    end if;
  end loop;

  foreach r in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array['brain_episodes', 'brain_facts', 'brain_working'] loop
        if has_table_privilege(r, format('public.%s', t), 'select')
           or has_table_privilege(r, format('public.%s', t), 'insert') then
          leaked := leaked || format('%s على %s ', r, t);
        end if;
      end loop;
      if has_function_privilege(r, 'public.brain_recall(text, integer, boolean, text[])', 'execute') then
        leaked := leaked || format('%s على brain_recall ', r);
      end if;
    end if;
  end loop;

  if leaked <> '' then
    raise exception 'صلاحيات مسرّبة للمفتاح العام: %', leaked;
  end if;
end
$$;

select 'BRAIN SCHEMA TESTS PASSED' as result;

-- لا نترك أثرًا على مشروع حقيقي
rollback;
