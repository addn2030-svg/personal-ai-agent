# -*- coding: utf-8 -*-
"""يولّد صفحة إعداد SQL من **ملفات SQL نفسها** — لا نسخًا يدويًا منها.

لماذا مولِّد؟
-----------
الصفحة الغرضية (أن يفتحها المستخدم في المتصفح، ينسخ، يلصق في Supabase) تحتاج نص
SQL كاملًا. ولو نُسخ النص يدويًا لصارت لدينا **نسختان** من المخطط: تُعدَّل إحداهما
وتُنسى الأخرى، فيُنفَّذ SQL قديم على قاعدة بيانات حقيقية بلا أن يلاحظ أحد. هذا
بالضبط ما نرفضه في هذا المستودع (مصدر حقيقة واحد).

الحل: الصفحة **مولَّدة** من `supabase/*.sql`، وبصمة كل ملف مكتوبة داخلها.
اختبار `tests/test_sql_setup_page.py` يفشل إن تغيّر ملف SQL ولم تُعِد التوليد.

التشغيل:
    python3 scripts/make_sql_setup_page.py
    python3 scripts/make_sql_setup_page.py --check     # يفشل إن كانت الصفحة قديمة
"""
from __future__ import annotations

import hashlib
import html
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "docs", "sql-setup-page.html")

FILES = (
    {
        "file": "supabase/01_state_snapshots.sql",
        "step": "١",
        "title": "جدول النسخ الكاملة (state_snapshots)",
        "why": "يحمي الحالة من فقدان الخادم. خطة Render المجانية بلا قرص دائم، "
               "فهذا الجدول هو الذاكرة التي يستعيدها البوت عند كل إقلاع.",
    },
    {
        "file": "supabase/02_tasks_mirror.sql",
        "step": "٢",
        "title": "مرآة المهام (tasks_mirror)",
        "why": "تتيح لك استعلام مهامك بـSQL أو من Table Editor على جوالك. "
               "الاتجاه واحد: النظام ← Supabase، ولا كتابة يدوية.",
    },
    {
        "file": "supabase/03_brain_memory.sql",
        "step": "٣",
        "title": "الدماغ الدائم (brain_episodes · brain_facts · brain_working)",
        "why": "ذاكرة الوكيل طويلة المدى: حلقات · حقائق مُثبتة · سياق مؤقت. "
               "يفعّل أوامر /brain و/brain_recall و/brain_stats.",
    },
)

VERIFY_SQL = """-- التحقق بعد تنفيذ الملفات الثلاثة: المتوقّع 11 سطرًا
-- 5 جداول + 5 دوال + امتداد pg_trgm واحد
select 'جدول' as النوع, table_name as الاسم
  from information_schema.tables
 where table_schema = 'public'
   and table_name in ('state_snapshots','tasks_mirror',
                      'brain_episodes','brain_facts','brain_working')
union all
select 'دالة', p.proname
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = 'public'
   and p.proname in ('brain_norm','brain_fold','brain_recall','brain_stats','brain_prune')
union all
select 'امتداد', extname from pg_extension where extname = 'pg_trgm'
order by 1, 2;"""

SMOKE_SQL = """-- اختبار حيّ: يجب أن يعيد صفًا واحدًا بأصفار (الجداول فارغة الآن — هذا صحيح)
select jsonb_pretty(public.brain_stats()) as حالة_الدماغ;"""

PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>إعداد SQL في Supabase — خطوة بخطوة</title>
<style>
  :root {{ --ink:#0f172a; --muted:#5b6b85; --line:#d8e0ec; --ok:#0a7d55;
           --warn:#a35a00; --bg:#f6f8fc; --card:#fff; --accent:#1b5fd9; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:0 0 60px; background:var(--bg); color:var(--ink);
          font:16px/1.7 -apple-system,"Segoe UI",Tahoma,sans-serif; }}
  header {{ background:linear-gradient(135deg,#12306b,#1b5fd9); color:#fff;
            padding:26px 22px; }}
  header h1 {{ margin:0 0 6px; font-size:24px; }}
  header p {{ margin:0; opacity:.9; font-size:15px; }}
  main {{ max-width:900px; margin:0 auto; padding:0 18px; }}
  section {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
             padding:18px 20px; margin:18px 0; }}
  h2 {{ font-size:19px; margin:0 0 12px; }}
  h3 {{ font-size:16px; margin:18px 0 8px; }}
  a {{ color:var(--accent); }}
  .linkbox {{ background:#eef4ff; border:1px solid #c8daff; border-radius:10px;
              padding:12px 14px; margin:10px 0; }}
  .linkbox a {{ font-weight:600; word-break:break-all; }}
  .step {{ border-right:5px solid var(--accent); padding-right:14px; }}
  .step h2 {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
  .pill {{ font-size:12px; background:#eef4ff; color:var(--accent);
           border-radius:99px; padding:2px 10px; font-weight:600; }}
  .file {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:13px;
           background:#f2f5fa; border:1px solid var(--line); border-radius:6px;
           padding:1px 6px; direction:ltr; display:inline-block; }}
  .why {{ color:var(--muted); font-size:15px; margin:6px 0 10px; }}
  .sqlwrap {{ position:relative; margin:10px 0; }}
  textarea.sql {{ width:100%; height:230px; direction:ltr; text-align:left;
      font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12.5px;
      line-height:1.5; border:1px solid var(--line); border-radius:10px;
      padding:12px; background:#fbfcfe; color:#12233d; resize:vertical;
      white-space:pre; overflow:auto; }}
  button.copy {{ position:absolute; top:8px; left:8px; z-index:2;
      background:var(--accent); color:#fff; border:0; border-radius:8px;
      padding:6px 12px; font-size:13px; cursor:pointer; }}
  button.copy:hover {{ background:#14479f; }}
  .expect {{ background:#eafaf3; border:1px solid #b6e7d2; border-radius:10px;
             padding:10px 14px; font-size:15px; margin-top:8px; }}
  .warnbox {{ background:#fff8e8; border:1px solid #f0d9a8; border-radius:10px;
              padding:12px 14px; margin:10px 0; }}
  .danger {{ background:#fdecec; border:1px solid #f3c9c9; }}
  ul {{ padding-right:20px; }}
  li {{ margin:5px 0; }}
  code {{ background:#f2f5fa; padding:1px 5px; border-radius:5px;
          font-family:ui-monospace,Menlo,Consolas,monospace; font-size:13.5px;
          direction:ltr; display:inline-block; }}
  table {{ width:100%; border-collapse:collapse; margin:10px 0; font-size:15px; }}
  th, td {{ border:1px solid var(--line); padding:8px 10px; text-align:right; }}
  th {{ background:#f2f5fa; }}
  .fp {{ font-size:12px; color:var(--muted); direction:ltr;
         font-family:ui-monospace,monospace; }}
</style>
</head>
<body>
<header>
  <h1>إعداد SQL في Supabase — نفّذها بالترتيب</h1>
  <p>ثلاث لصقات · لا يحتاج أي أمر على جهازك · صفحة مولَّدة من ملفات SQL نفسها</p>
</header>
<main>

<section>
  <h2>قبل أن تبدأ: أين أنت الآن؟</h2>
  <table>
    <tr><th>حالتك</th><th>ما تفعله</th></tr>
    <tr><td>لا يوجد مشروع Supabase بعد</td>
        <td>افتح <a href="https://supabase.com/dashboard/new" target="_blank">supabase.com/dashboard/new</a>
            → اختر اسمًا → اختر المنطقة (الأقرب: <code>Frankfurt</code> أو
            <code>Mumbai</code>) → احفظ كلمة مرور قاعدة البيانات في مكان آمن →
            انتظر دقيقة حتى يجهز المشروع.</td></tr>
    <tr><td>المشروع موجود</td>
        <td>انتقل مباشرة إلى محرّر SQL:
            <a href="https://supabase.com/dashboard/project/_/sql/new" target="_blank">
            Supabase → SQL Editor → New query</a> (استبدل <code>_</code> بمعرّف مشروعك).</td></tr>
  </table>
  <div class="linkbox">
    <strong>معرّف مشروعك</strong> هو الجزء الظاهر في رابط المشروع:<br>
    <span class="fp">https://<b>&lt;ref&gt;</b>.supabase.co</span> — تجده في
    <strong>Settings → API Keys</strong> أو زر <strong>Connect</strong>. وهو نفسه
    الرابط الذي سيوضع في <code>SUPABASE_URL</code> لاحقًا.
  </div>
</section>

<section class="danger">
  <h2>⛔ ثلاثة خطوط لا تتجاوزها</h2>
  <ul>
    <li><strong>لا تُلصق أي مفتاح في أي محادثة</strong> — لا معي ولا في تيليجرام.</li>
    <li>مفتاح <code>service_role</code> / <code>sb_secret_…</code> يقرأ ويكتب كل شيء:
        مكانه خادم Render فقط، لا المتصفح ولا GitHub.</li>
    <li>هذه الصفحة <strong>لا تحذف شيئًا</strong>: كل ملف يستخدم
        <code>create … if not exists</code>. تكرار التنفيذ آمن.</li>
  </ul>
</section>

<section>
  <h2>كيف تنفّذ كل خطوة (نفس الطريقة ثلاث مرات)</h2>
  <ul>
    <li>اضغط <strong>Copy</strong> في الصندوق.</li>
    <li>في Supabase: <strong>SQL Editor → New query</strong> → الصق.</li>
    <li>اضغط <strong>Run</strong> (أو <code>Ctrl</code>+<code>Enter</code>).</li>
    <li>النتيجة المتوقّعة: <strong>Success. No rows returned</strong> — هذه علامة نجاح
        لا خطأ (المخطط لا يعيد صفوفًا).</li>
  </ul>
</section>

{steps}

<section>
  <h2>التحقق النهائي — الصق هذا بعد الملف الثلاثة</h2>
  <div class="sqlwrap">
    <button class="copy" onclick="cp(this)">Copy</button>
    <textarea class="sql" readonly>{verify}</textarea>
  </div>
  <div class="expect">
    <strong>المتوقّع: 11 سطرًا</strong> — ٥ جداول
    (<code>state_snapshots</code> · <code>tasks_mirror</code> · <code>brain_episodes</code> ·
    <code>brain_facts</code> · <code>brain_working</code>) · ٥ دوال
    (<code>brain_norm</code> · <code>brain_fold</code> · <code>brain_recall</code> ·
    <code>brain_stats</code> · <code>brain_prune</code>) · امتداد <code>pg_trgm</code>.
    إن ظهر أقل من ذلك، فالملف الناقص لم يُنفَّذ — أعد تشغيله وحده.
  </div>
</section>

<section>
  <h2>اختبار حيّ (اختياري لكن مفيد)</h2>
  <div class="sqlwrap">
    <button class="copy" onclick="cp(this)">Copy</button>
    <textarea class="sql" readonly>{smoke}</textarea>
  </div>
  <div class="expect">
    يجب أن يعيد صفًا واحدًا فيه <code>episodes: 0</code> و<code>facts: 0</code>.
    الأصفار صحيحة تمامًا: الدماغ فارغ لأننا لم نبدأ الاستخدام بعد. المهم أن الدالة
    تعمل — هذا يعني أن الـRPC الذي سيستدعيه البوت جاهز.
  </div>
</section>

<section>
  <h2>كيف تعرف أن الإعداد بدأ؟ (بلا أي مفتاح سري)</h2>
  <p class="why">
    لا تحتاج المفتاح السري — ولا قراءة صف واحد — لتعرف هل نُفِّذت الملفات. يكفي
    سؤال PostgREST عن كل جدول بالـ<strong>مفتاح العام</strong> (وهو مخصَّص للنشر
    العام، فوجوده في رابط لا يكشف شيئًا لأن RLS يحجب كل صف عنه).
  </p>
  <table>
    <tr><th>ما تراه</th><th>المعنى</th></tr>
    <tr><td><code>PGRST205</code> أو <code>PGRST202</code></td>
        <td><strong>غير موجود</strong> — الملف لم يُنفَّذ بعد.</td></tr>
    <tr><td><code>permission denied</code></td>
        <td><strong>موجود ومحجوب عن العام</strong> — وهذا هو الوضع الصحيح تمامًا.</td></tr>
    <tr><td>قائمة <code>[]</code> فارغة</td>
        <td>موجود <em>وله صلاحية قراءة للعام</em> — راجع <code>REVOKE</code> في الملف.</td></tr>
  </table>

  <h3>الطريقة الأسرع: من المتصفح</h3>
  <p class="why">الصق هذا الرابط بعد استبدال <code>&lt;ref&gt;</code> و
     <code>&lt;publishable-key&gt;</code>، واقرأ النتيجة:</p>
  <div class="sqlwrap">
    <button class="copy" onclick="cp(this)">Copy</button>
    <textarea class="sql" readonly>https://&lt;ref&gt;.supabase.co/rest/v1/state_snapshots?select=id&amp;limit=1&amp;apikey=&lt;publishable-key&gt;</textarea>
  </div>

  <h3>الطريقة الأنسب: أداة الفحص</h3>
  <p class="why">تفحص الجداول الخمسة والدوال الخمس كلها وتطبع خلاصة واحدة:</p>
  <div class="sqlwrap">
    <button class="copy" onclick="cp(this)">Copy</button>
    <textarea class="sql" readonly>export SUPABASE_URL="https://&lt;ref&gt;.supabase.co"
export SUPABASE_ANON_KEY="&lt;publishable-key&gt;"
python3 -m connectors.supabase_probe</textarea>
  </div>
  <div class="expect">
    <strong>النتيجة المتوقّعة:</strong>
    <code>لم يبدأ الإعداد</code> قبل التنفيذ ·
    <code>الإعداد مكتمل: 10 من 10 موجود</code> بعده.
    <br><strong>ملاحظة أمنية مُنفَّذة في الكود:</strong> الأداة <strong>ترفض</strong>
    المفتاح السري صراحةً (<code>sb_secret_…</code> أو JWT بـ
    <code>role=service_role</code>) وتطبع رسالة توجّهك إلى المفتاح العام — لأن هذا
    الفحص لا يحتاجه، ولكل مسار يمر فيه المفتاح السري احتمال أن يُسجَّل.
  </div>
</section>

<section>
  <h2>إن ظهر خطأ</h2>
  <table>
    <tr><th>الرسالة</th><th>المعنى والحل</th></tr>
    <tr>
      <td>رسالة تذكر <code>pg_trgm</code></td>
      <td>الامتداد غير متاح في مشروعك. المشروع يتراجع بالكامل (لا مخطط نصف مبني).
          الحل: <strong>Database → Extensions</strong> → ابحث <code>pg_trgm</code> →
          <strong>Enable</strong> → ثم أعد تنفيذ ملف ٣.</td>
    </tr>
    <tr>
      <td><code>already exists</code></td>
      <td>طبيعي: الملف نُفِّذ قبل ذلك. الملفات آمنة التكرار —
          <code>if not exists</code> في كل مكان. تجاهلها وواصل.</td>
    </tr>
    <tr>
      <td><code>permission denied</code></td>
      <td>أنت في المشروع الخطأ أو بحساب لا يملك التحرير. تأكد أنك في
          <strong>SQL Editor</strong> الخاص بمشروعك أنت.</td>
    </tr>
    <tr>
      <td><code>relation "state_snapshots" does not exist</code> عند تشغيل البوت</td>
      <td>ملف ١ لم يُنفَّذ. نفّذه ثم أعد المحاولة.</td>
    </tr>
  </table>
</section>

<section>
  <h2>ماذا بعد هذه الخطوة؟</h2>
  <ul>
    <li><strong>الخطوة التالية مباشرة</strong>: ترحيل الشيت إلى الحالة على جهازك
        (<code>python3 engine/migrate.py</code>) — التفاصيل في
        <span class="file">docs/git-data-to-sql.md</span>.</li>
    <li>ثم ربط Render بالمفاتيح نفسها، وفحص <code>/brain_status</code> في تيليجرام.</li>
    <li><strong>لا ترسل لي أي مفتاح.</strong> أخبرني فقط: نجحت الخطوات، أو الصق نص
        الخطأ كما هو (بلا مفاتيح).</li>
  </ul>
</section>

<section>
  <h2>لماذا هذه الصفحة مولَّدة؟</h2>
  <p class="why">
    نص SQL هنا ليس منسوخًا يدويًا: يولّده
    <span class="file">scripts/make_sql_setup_page.py</span> من ملفات
    <span class="file">supabase/*.sql</span> نفسها، وتُطبع بصمة كل ملف أدناه. ولو
    عُدِّل ملف SQL ولم تُعِد التوليد، يفشل اختبار
    <span class="file">tests/test_sql_setup_page.py</span> — فلا يمكن أن يُنفَّذ على
    قاعدة بياناتك مخطط قديم بلا أن يظهر ذلك. مصدر حقيقة واحد.
  </p>
  <table>
    <tr><th>الملف</th><th>البصمة (sha256)</th></tr>
    {fingerprints}
  </table>
</section>

</main>
<script>
function cp(button) {{
  var area = button.parentNode.querySelector('textarea');
  area.select();
  var done = function () {{
    var old = button.textContent;
    button.textContent = '✓ نُسخ';
    setTimeout(function () {{ button.textContent = old; }}, 1500);
  }};
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(area.value).then(done, function () {{ document.execCommand('copy'); done(); }});
  }} else {{
    document.execCommand('copy'); done();
  }}
}}
</script>
</body>
</html>
"""


def read_sql(relative: str) -> str:
    with open(os.path.join(BASE, relative), encoding="utf-8") as handle:
        return handle.read().rstrip("\n")


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build() -> str:
    blocks = []
    prints = []
    for meta in FILES:
        sql = read_sql(meta["file"])
        digest = fingerprint(sql)
        prints.append(
            f'    <tr><td><span class="file">{meta["file"]}</span></td>'
            f'<td class="fp">{digest[:32]}…</td></tr>'
        )
        blocks.append(f"""<section class="step">
  <h2><span class="pill">الخطوة {meta['step']}</span> {html.escape(meta['title'])}
      <span class="file">{meta['file']}</span></h2>
  <p class="why">{html.escape(meta['why'])}</p>
  <div class="sqlwrap">
    <button class="copy" onclick="cp(this)">Copy</button>
    <textarea class="sql" readonly>{html.escape(sql)}</textarea>
  </div>
  <div class="expect"><strong>النتيجة المتوقّعة:</strong> Success. No rows returned
      &nbsp;·&nbsp; <strong>عدد الأسطر:</strong> {len(sql.splitlines())}
      &nbsp;·&nbsp; <strong>البصمة:</strong> <span class="fp">{digest[:16]}…</span></div>
</section>""")
    return PAGE.format(steps="\n\n".join(blocks),
                       verify=html.escape(VERIFY_SQL),
                       smoke=html.escape(SMOKE_SQL),
                       fingerprints="\n".join(prints))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    page = build()
    if "--check" in argv:
        try:
            with open(OUT, encoding="utf-8") as handle:
                current = handle.read()
        except FileNotFoundError:
            print(f"❌ الصفحة غير موجودة: {OUT}")
            return 1
        if current != page:
            print("❌ الصفحة قديمة — أعد التوليد: python3 scripts/make_sql_setup_page.py")
            return 1
        print("✅ الصفحة مطابقة لملفات SQL الحالية.")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(page)
    total = sum(len(read_sql(m["file"]).splitlines()) for m in FILES)
    print(f"✅ كُتبت الصفحة: {os.path.relpath(OUT, BASE)}")
    print(f"   {len(FILES)} ملفات SQL · {total} سطر · {len(page) // 1024} كيلوبايت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
