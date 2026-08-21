# -*- coding: utf-8 -*-
"""
وحدة العرض — تولّد لوحة قيادة HTML واحدة قابلة للحفظ على سطح المكتب:
تصميم عربي RTL، بلا أي موارد خارجية (تعمل دون إنترنت)، زر طباعة، تبويبات، أزرار نسخ.
"""
import datetime as dt

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

CSS = """
*{box-sizing:border-box}
body{font-family:'Segoe UI',Tahoma,'Arial',sans-serif;direction:rtl;margin:0;background:#edf1f6;color:#1c2b36}
.topbar{position:sticky;top:0;z-index:9;background:linear-gradient(120deg,#0e4a50,#137a74);color:#fff;padding:12px 22px;display:flex;align-items:center;gap:14px;box-shadow:0 2px 10px rgba(14,74,80,.25)}
.logo{width:40px;height:40px;border-radius:12px;background:rgba(255,255,255,.15);display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;flex:none}
.brand{line-height:1.25}
.brand b{font-size:16px}
.brand span{display:block;font-size:11.5px;opacity:.85}
.spacer{flex:1}
.badge{background:#f2c14e;color:#4a3608;font-size:11.5px;font-weight:700;border-radius:20px;padding:4px 12px;white-space:nowrap}
.badge.live{background:#8fe3b0;color:#0b3d24}
.btn{border:none;border-radius:9px;padding:8px 14px;font-size:13px;font-weight:600;cursor:pointer;background:rgba(255,255,255,.16);color:#fff;font-family:inherit}
.btn:hover{background:rgba(255,255,255,.28)}
.btn.pri{background:#f2c14e;color:#4a3608}
.wrap{max-width:980px;margin:0 auto;padding:20px 18px 8px}
.tabs{display:flex;gap:8px;margin:0 auto 16px;max-width:980px;padding:0 18px}
.tabs button{flex:1;border:1px solid #d7dfe8;background:#fff;border-radius:12px;padding:11px 10px;font-size:14.5px;font-weight:700;color:#44586a;cursor:pointer;font-family:inherit;transition:.15s}
.tabs button.active{background:#0e4a50;border-color:#0e4a50;color:#fff;box-shadow:0 3px 10px rgba(14,74,80,.25)}
.hero{background:linear-gradient(120deg,#0e4a50,#137a74);color:#fff;border-radius:16px;padding:20px 24px;margin-bottom:14px}
.hero h1{margin:0 0 6px;font-size:21px}
.hero p{margin:4px 0;font-size:13.5px;opacity:.94}
.hero .num{display:inline-block;background:rgba(255,255,255,.18);border-radius:8px;padding:1px 8px;font-weight:700}
.card{background:#fff;border:1px solid #e3e9f0;border-radius:14px;padding:16px 20px;margin-bottom:14px;box-shadow:0 1px 3px rgba(28,43,54,.05);break-inside:avoid}
.card h2{margin:0 0 10px;font-size:16px;color:#0e4a50;padding-right:10px;border-right:4px solid #17a2a0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:760px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{background:#f2f6f9;color:#0e4a50;padding:8px 10px;text-align:right;border-bottom:2px solid #dde6ec}
td{padding:8px 10px;border-bottom:1px solid #eef2f6}
tr:last-child td{border-bottom:none}
ul{margin:6px 0;padding:0 20px}
li{margin:6px 0;font-size:14px;line-height:1.55}
.pill{display:inline-block;border-radius:20px;padding:2px 11px;font-size:11.5px;font-weight:700;margin-right:6px;background:#eef4f7;color:#44586a;white-space:nowrap}
.pill.ok{background:#e9f7ef;color:#1e6b44}.pill.bad{background:#fdeeec;color:#a93226}
.pill.warn{background:#fdf6e3;color:#9c6d10}.pill.teal{background:#e0f2f1;color:#0e4a50}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:4px 0 6px}
.kpi{background:#f8fafc;border:1px solid #e6ecf2;border-radius:12px;padding:12px;text-align:center}
.kpi b{display:block;font-size:23px;color:#0e4a50}
.kpi span{font-size:12px;color:#5c6f7e}
.kpi .d{display:inline-block;margin-top:5px;font-size:11.5px;font-weight:700;border-radius:14px;padding:1px 9px}
.d.g{background:#e9f7ef;color:#1e6b44}.d.r{background:#fdeeec;color:#a93226}.d.n{background:#eef2f6;color:#5c6f7e}
.alert{border-radius:12px;padding:12px 16px;font-size:14px;line-height:1.6;margin:10px 0}
.alert b{font-size:14.5px}
.alert.red{background:#fdeeec;border-right:5px solid #c0392b}
.alert.amber{background:#fdf6e3;border-right:5px solid #b7791f}
.alert.green{background:#e9f7ef;border-right:5px solid #2f9461}
.draft{position:relative;background:#f6faf7;border:1px solid #dcebe2;border-right:4px solid #2f9461;border-radius:10px;padding:12px 14px;font-size:13.5px;white-space:pre-line;margin:10px 0;line-height:1.7}
.copy{position:absolute;top:8px;left:8px;border:1px solid #bcd9c8;background:#fff;color:#1e6b44;border-radius:8px;padding:4px 10px;font-size:12px;cursor:pointer;font-family:inherit}
.copy:hover{background:#e9f7ef}
.rec{display:flex;gap:12px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.15);border-radius:12px;padding:12px 14px;margin:9px 0}
.rec .n{flex:none;width:30px;height:30px;border-radius:50%;background:#f2c14e;color:#4a3608;font-weight:800;display:flex;align-items:center;justify-content:center}
.rec p{margin:2px 0;font-size:14px;line-height:1.6}
.dark{background:linear-gradient(120deg,#123f52,#0e4a50);border:none;color:#fff}
.dark h2{color:#f2c14e;border-color:#f2c14e}
footer{text-align:center;font-size:12px;color:#6b7c8a;padding:14px 10px 26px;line-height:1.8}
.hint{font-size:12px;color:#6b7c8a;margin-top:8px}
@media print{
 .topbar,.tabs,.copy{display:none!important}
 body{background:#fff}
 .wrap{max-width:100%;padding:0}
 .card,.hero{box-shadow:none;break-inside:avoid}
 .tabsec{display:block!important}
}
"""

JS = """
function showTab(id,btn){
 var s=document.querySelectorAll('.tabsec');
 for(var i=0;i<s.length;i++)s[i].hidden=(s[i].id!=='sec-'+id);
 var b=document.querySelectorAll('.tabs button');
 for(var i=0;i<b.length;i++)b[i].classList.toggle('active',b[i]===btn);
 window.scrollTo({top:0});
}
function fallbackCopyText(btn){var t=btn.getAttribute('data-txt');
 function ok(){btn.textContent='\u2713 تم النسخ';setTimeout(function(){btn.textContent='\U0001F4CB نسخ';},1600);}
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,function(){fb();});}else{fb();}
 function fb(){var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();
  try{document.execCommand('copy');ok();}catch(e){}document.body.removeChild(ta);}}
function copyDraft(btn,id){
 var t=document.getElementById(id).innerText;
 function ok(){btn.textContent='✓ تم النسخ';setTimeout(function(){btn.textContent='📋 نسخ';},1600);}
 function fb(){var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();
  try{document.execCommand('copy');ok();}catch(e){}document.body.removeChild(ta);}
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,fb);}else{fb();}
}
"""

def pill(text, cls=""):
    return f'<span class="pill {cls}">{esc(text)}</span>'

def ul(items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"

# ------------------------------------------------------------------ البريف
def build_brief_body(c):
    h = f"""<div class="hero"><h1>☀️ {esc(c['b_title'])}</h1>
<p>عبدالرحمن، جهّزتُ هذا البريف تلقائيًا من الشيت الرئيسي وأنجزت عنك <span class="num">{c['b_auto']}</span> مهمة روتينية (كشف، حصر، مسودات).</p>
<p>المتبقي لك: القرار والموافقة — كما هي قاعدة النظام.</p></div>

{"".join('<div class="card" style="background:#f0f7fa;border-color:#cfe4ea"><h2>🔄 ما تغيّر منذ البريف السابق</h2>' + ul(f"{esc(x)}" for x in c["changes"]) + "</div>" for _ in [1] if c.get("changes"))}
<div class="card"><h2>🎯 أهم 3 أولويات</h2><ol style="margin:6px 0;padding:0 22px">"""
    for i, t in enumerate(c["top3"], 1):
        late = f' <span class="pill bad">متأخرة {t["late"]} يومًا</span>' if t["late"] else ""
        h += f"""<li style="margin:8px 0;font-size:14.5px"><b>{esc(t['t'])}</b>{late}<br>
{pill(t['type'], 'teal')}{pill('أولوية ' + t['pr'], 'warn' if t['pr'] == 'عالية' else '')}{pill('الموعد: ' + t['due'])}</li>"""
    h += "</ol></div><div class=\"grid2\">"

    h += '<div class="card"><h2>✅ يحتاج قرارك / موافقتك</h2><ul>'
    for d in c["dec_due"]:
        h += f"""<li>مراجعة قرار «<b>{esc(d['t'])}</b>» {pill('مستحقة ' + d['rev'], 'bad')}<br>
المتوقع: {esc(d['exp'])} — الفعلي: <b>{esc(d['act'])}</b>. هل كان القرار صحيحًا؟ سجّل الدرس.</li>"""
    if c["fu_review"]:
        h += f"<li>موافقة على تعديل خطط سريرية: {len(c['fu_review'])} مرضى ({'، '.join(esc(x) for x in c['fu_review'])}) — القرار السريري النهائي يبقى لك.</li>"
    for d in c["dec_run"]:
        h += f"<li>متابعة تنفيذ: «{esc(d['t'])}» {pill('مراجعة ' + d['rev'])}</li>"
    for dr in c.get("drs", []):
        h += (f"<li>📌 طلب قرار مفتوح <b>{esc(dr['id'])}</b>: {esc(dr['t'])} "
              f"{pill('المهلة ' + dr['dl'], 'bad' if dr['late'] else 'warn')}"
              + (" <span class='pill bad'>تجاوز المهلة</span>" if dr["late"] else "")
              + f"<br><span style='color:#5c6f7e'>الخيارات: {esc(dr['opts'])}</span></li>")
    h += "</ul></div>"

    h += '<div class="card"><h2>📅 اجتماعات الأسبوع + التحضير</h2><ul>'
    for m in c["meetings"]:
        cls = "ok" if m["ok"] else "warn"
        ico = "✅" if m["ok"] else "⚠️"
        h += f"""<li><b>{esc(m['t'])}</b> {pill(m['day'] + ' ' + m['d'], 'teal')}{pill(m['time'])}{pill(ico + ' ' + m['st'], cls)}<br><span style="color:#5c6f7e">التحضير: {esc(m['prep'])}</span></li>"""
    h += "</ul></div></div>"

    h += '<div class="card"><h2>⏳ متابعات مستحقة</h2><ul>'
    for l in c["leads_due"]:
        h += f"""<li>عميل: <b>{esc(l['name'])}</b> ({esc(l['svc'])}) {pill('متابعة ' + l['d'], 'teal')}{pill(f"{l['val']:,} ريال", 'warn')}</li>"""
    for f in c["fu_late"]:
        h += f"""<li>مريض <b>{esc(f['code'])}</b> فات موعده {pill(f['d'], 'bad')} {esc(f['note'])}</li>"""
    for f in c["fu_soon"]:
        h += f"<li>مريض {esc(f['code'])} موعده القادم {pill(f['d'])}</li>"
    if c["voice_n"]:
        h += f"<li>🎙️ صندوق الصوت: {c['voice_n']} عنصر بانتظار التحويل — أوله: «{esc(c['voice_first'])}»</li>"
    h += "".join(f"<li>⏸️ ننتظر: {esc(w['t'])} — {'⚠️ متأخر' if w.get('over') else 'منذ'} {w['d']} يومًا</li>" for w in c.get("wait", []))
    h += "".join(f"<li>📚 مراجعة تعلّم: <b>{esc(x['t'])}</b> — {x['m']} دقائق"
                 + (" <span class='pill bad'>مفهوم ضعيف</span>" if x["weak"] else "")
                 + "</li>" for x in c.get("reviews", []))
    h += "</ul></div>"

    r = c["risk"]
    if c.get("calls"):
        h += ('<div class="card" style="background:#f5f0fa;border-color:#ddd0ee">'
              '<h2 style="color:#4b3f80;border-color:#7a5fb5">📞 مكالمات تحتاج انتباهك</h2><ul>')
        for cl in c["calls"]:
            h += (f"<li><b>{cl['id']}</b> — {cl['who']} | {cl['what']}"
                  + (f" <span class='pill warn'>قوة العميل {cl['lead']}</span>" if cl['lead'] in ('HIGH', 'MEDIUM') else "")
                  + (f" <span class='pill bad'>🔔 تحويل: {cl['ho']}</span>" if cl['ho'] else "")
                  + (" <span class='pill bad'>🛡️ حقن مرفوض</span>" if cl['sec'] else "")
                  + f"<br><span style='color:#5c6f7e'>{cl['sm']}</span></li>")
        h += '</ul></div>'
    h += f"""<div class="grid2">
<div class="card" style="background:#fdeeec;border-color:#f3cfc9"><h2 style="color:#a93226;border-color:#c0392b">⚠️ خطر يستحق انتباهك</h2>
<p style="font-size:14px;line-height:1.7"><b>{esc(r['t'])}</b><br>{esc(r['d']) if r else ''}</p></div>
<div class="card" style="background:#e9f7ef;border-color:#cbe8d6"><h2 style="color:#1e6b44;border-color:#2f9461">💡 فرصة تستحق نظرة</h2>
<p style="font-size:14px;line-height:1.7">الخدمة الأكثر طلبًا بين فرصك النشطة: <b>{esc(c['opp']['svc'])}</b> ({c['opp']['n']} فرص، خط أنشط {c['opp']['pipe']:,} ريال).</p></div>
</div>"""

    if c["drafts"]:
        h += '<div class="card"><h2>📝 مسودات جاهزة — أرسلها كما هي أو عدّلها</h2>'
        for i, d in enumerate(c["drafts"], 1):
            h += ('<div style="position:relative">'
                  '<div class="draft" id="draft-' + str(i) + '">' + esc(d) + '</div>'
                  '<button class="copy" onclick="copyDraft(this,\'draft-' + str(i) + '\')">📋 نسخ</button></div>')
        h += "</div>"

    h += '<div class="card"><h2>📉 ما تأخر (يحتاج جدولة)</h2>'
    h += ul([f"{esc(t['t'])} {pill('تأخر ' + str(t['days']) + ' يومًا', 'bad')}" for t in c["overdue"]]) if c["overdue"] else "<p style='margin:4px'>لا شيء متأخر ✅</p>"
    h += "</div>"
    return h

# ------------------------------------------------------------------ المراجعة
def build_weekly_body(c):
    k = ""
    for label, now, prev, delta, _hib in c["kpis"]:
        cls = "g" if "✅" in delta else ("r" if "⚠️" in delta else "n")
        k += f"""<div class="kpi"><b>{esc(now)}</b><span>{esc(label)}</span><br>
<span class="d {cls}">{esc(delta)}</span><span style="font-size:10.5px;color:#8a99a6"> (السابق: {esc(prev)})</span></div>"""

    iss = c["issue"]
    h = f"""<div class="hero"><h1>📊 المراجعة التنفيذية الأسبوعية</h1>
<p>{esc(c['wk'])} — وُلّد تلقائيًا من الشيت الرئيسي. القاعدة: لا 50 توصية — أهم 3 قرارات فقط.</p></div>

<div class="card"><h2>🏥 قسم التأهيل</h2><div class="kpis">{k}</div>
<div class="alert red"><b>المشكلة التي تستحق تدخلك هذا الأسبوع:</b> {esc(iss[1]) if iss else '—'}<br>
{esc(iss[2]) if iss else ''}<br><b>الإجراء المقترح:</b> {esc(iss[3]) if iss else ''}</div>
{'<p class="hint">أحداث مسجلة: ' + esc(' | '.join(c['incidents'])) + '</p>' if c['incidents'] else ''}</div>

<div class="card{' ' if not c['p_stalled'] else ''}" style="{'background:#fdeeec;border-color:#f3cfc9' if c['p_stalled'] else ''}"><h2>🤖 المشاريع</h2>
<ul>
<li>{pill('🟢 نشط ' + str(len(c['p_active'])), 'ok')} {esc('، '.join(p for p, _ in c['p_active']) or '—')}</li>
<li>{pill('🟡 انتظار ' + str(len(c['p_waiting'])), 'warn')} {esc('، '.join(c['p_waiting']) or '—')}</li>
<li>{pill('🔴 متوقف ' + str(len(c['p_stopped'])), 'bad')} {esc('، '.join(c['p_stopped']) or '—')}</li>
<li>{pill('⚪ فكرة ' + str(len(c['p_idea'])))} {esc('، '.join(c['p_idea']) or '—')}</li>
</ul>"""
    if c["p_stalled"]:
        h += '<div class="alert amber"><b>⚠️ نشطة رسميًا لكنها متوقفة فعليًا:</b><br>' + \
             "<br>".join(f"• {esc(p['n'])}: بدون تقدم {p['days']} يومًا → قررك: خطوة واحدة هذا الأسبوع أو تحويلها إلى «متوقف»" for p in c["p_stalled"]) + "</div>"
    h += "<p style='margin:10px 0 4px'><b>الخطوة التالية لكل مشروع نشط:</b></p><ul>"
    for p, s in c["p_active"]:
        h += f"<li><b>{esc(p)}</b>: {esc(s)}</li>"
    h += f"</ul><p class='hint'>كلفة APIs والاشتراكات التشغيلية للمشاريع: <b>{c['api_cost']} ريال/شهر</b>.</p></div>"

    fu = c["funnel"]
    h += f"""<div class="card"><h2>💼 الأعمال والعملاء</h2>
<div class="kpis">
<div class="kpi"><b>{len(c['new_leads'])}</b><span>فرص جديدة</span></div>
<div class="kpi"><b>{c['pipe']:,}</b><span>خط الفرص (ريال)</span></div>
<div class="kpi"><b>{c['conv']:.0%}</b><span>معدل التحويل</span></div>
<div class="kpi"><b>{fu.get('عرض', 0)}</b><span>عروض قائمة</span></div>
</div>
<p style="font-size:13.5px;margin:10px 0 4px">القمع: جديد {fu.get('جديد', 0)} | تم التواصل {fu.get('تم التواصل', 0)} | انتظار رد {fu.get('انتظار رد', 0)} | عرض {fu.get('عرض', 0)} | فاز {fu.get('فاز', 0)} | خسر {fu.get('خسر', 0)}{(' — من الجديد: ' + esc('، '.join(c['new_leads']))) if c['new_leads'] else ''}</p>
<p style="font-size:13.5px">الخدمة الأكثر طلبًا: <b>{esc(c['opp']['svc'])}</b>.</p>
{f'<div class="alert amber"><b>⚠️ {len(c["no2"])} فرص بلا تواصل ثانٍ:</b> {esc("، ".join(c["no2"]))} — المسودات جاهزة في تبويب البريف.</div>' if c['no2'] else ''}
</div>"""

    f_ = c["fin"]
    h += f"""<div class="card"><h2>💰 المالية (الاشتراكات)</h2>
<div class="kpis">
<div class="kpi"><b>{f_['total']}</b><span>ريال/شهر</span></div>
<div class="kpi"><b>{f_['total'] * 12:,}</b><span>ريال/سنة</span></div>
<div class="kpi"><b>{f_['save']}</b><span>توفير محتمل/شهر</span></div>
</div>
<ul>
<li><b>تجديدات خلال 30 يومًا:</b> {esc('، '.join(f_['renew'])) if f_['renew'] else 'لا يوجد'}</li>
<li><b>غير مستخدمة (+30 يومًا):</b> {esc('، '.join(f_['unused'])) if f_['unused'] else 'لا يوجد'}</li>
<li><b>مكررة:</b> {esc('؛ '.join(f_['dups'])) if f_['dups'] else 'لا يوجد'}</li>
</ul>
<div class="alert green"><b>التوفير المحتمل: {f_['save']} ريال/شهر ({f_['save'] * 12:,} ريال/سنة)</b> — بإلغاء غير المستخدم ودمج المكرر.</div></div>"""

    h += '<div class="card"><h2>🧭 سجل القرارات — مراجعات مستحقة</h2>'
    if c["dec_rev"]:
        h += "<ul>" + "".join(
            f"""<li><b>{esc(d['t'])}</b> {pill('الخيار: ' + d['pick'], 'teal')}<br>
المتوقع: {esc(d['exp'])} | الفعلي: <b>{esc(d['act'])}</b> → قيّم: هل كان القرار صحيحًا؟ وسجّل الدرس.</li>"""
            for d in c["dec_rev"]) + "</ul>"
    else:
        h += "<p style='margin:4px'>لا مراجعات مستحقة ✅</p>"
    h += "</div>"

    L = c["learn"]
    h += f"""<div class="card"><h2>📚 التعلم والإنجاز</h2>
<div class="kpis">
<div class="kpi"><b>{L['done']}/{L['tot']}</b><span>تعلم مكتمل</span></div>
<div class="kpi"><b>{L['applied']}/{L['tot']}</b><span>طُبِّق عمليًا</span></div>
<div class="kpi"><b>{c['done_n']}</b><span>مهام أُنجزت</span></div>
<div class="kpi"><b>{c['over_n']}</b><span>متأخرة مفتوحة</span></div>
</div>
{'<p class="hint">غير مكتمل: ' + esc("، ".join(L["open"])) + '</p>' if L['open'] else ''}</div>"""

    h += """<div class="card dark"><h2>🏁 أهم 3 قرارات لهذا الأسبوع</h2>"""
    for i, r in enumerate(c["recs"], 1):
        h += f"""<div class="rec"><div class="n">{i}</div><p><b>{esc(r['t'])}</b><br>→ {esc(r['a'])}</p></div>"""
    h += "</div>"
    return h

# ------------------------------------------------------------------ الغلاف
def _footer(c):
    return f"""<footer>
وُلّد آليًا بواسطة <b>Abdulrahman AI OS v0.1</b> — {esc(c['generated'])} — المصدر: state.json (كاتب واحد)<br>
يعمل دون اتصال بالإنترنت — آمن للحفظ على سطح المكتب 📁 | للطباعة: Ctrl+P
</footer>"""

def wrap_page(c, title, body):
    demo = '<span class="badge">⚠️ بيانات تجريبية</span>' if c["demo"] else '<span class="badge live">✅ بيانات حقيقية</span>'
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<div class="topbar"><div class="logo">ع</div>
<div class="brand"><b>Abdulrahman AI OS</b><span>لوحة القيادة الشخصية — علاج طبيعي · تأهيل · AI · أعمال</span></div>
<div class="spacer"></div>{demo}<button class="btn pri" onclick="window.print()">🖨️ طباعة / PDF</button></div>
<div class="wrap">{body}</div>{_footer(c)}
<script>{JS}</script></body></html>"""

def wrap_dashboard(c, brief_body, weekly_body):
    demo = '<span class="badge">⚠️ بيانات تجريبية</span>' if c["demo"] else '<span class="badge live">✅ بيانات حقيقية</span>'
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Abdulrahman AI OS — لوحة القيادة</title>
<style>{CSS}</style></head><body>
<div class="topbar"><div class="logo">ع</div>
<div class="brand"><b>Abdulrahman AI OS</b><span>لوحة القيادة الشخصية — علاج طبيعي · تأهيل · AI · أعمال</span></div>
<div class="spacer"></div>{demo}<button class="btn pri" onclick="window.print()">🖨️ طباعة / PDF</button></div>
<div class="tabs">
<button class="active" onclick="showTab('weekly',this)">📊 المراجعة التنفيذية الأسبوعية</button>
<button onclick="showTab('brief',this)">☀️ البريف الصباحي</button>
</div>
<div class="wrap">
<section class="tabsec" id="sec-weekly">{weekly_body}</section>
<section class="tabsec" id="sec-brief" hidden>{brief_body}</section>
</div>{_footer(c)}
<script>{JS}</script></body></html>"""
