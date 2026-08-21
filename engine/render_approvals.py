# -*- coding: utf-8 -*-
"""صفحة طابور الإجراءات (approvals) — واجهة الاعتماد البشري لإصلاح C2."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_html import esc

def build_approvals_body(q):
    pend = [a for a in q if a["status"] == "PENDING_APPROVAL"]
    appr = [a for a in q if a["status"] == "APPROVED"]
    done = [a for a in q if a["status"] in ("EXECUTED", "EXPIRED", "REJECTED")]

    def cmd_box(text):
        return ('<div style="position:relative;background:#f4f7f9;border:1px dashed #b9c8d4;'
                'border-radius:8px;padding:8px 12px;margin-top:8px;font-size:12.5px;'
                'font-family:Consolas,monospace;direction:ltr;text-align:left">' + esc(text) +
                f'<button class="copy" onclick="fallbackCopyText(this)" data-txt="{esc(text)}">📋 نسخ</button></div>')

    h = ('<div class="hero"><h1>🛂 طابور الإجراءات — اعتماد قبل أي تنفيذ خارجي</h1>'
         '<p>قاعدة إصلاح C2: لا إرسال ولا نشر ولا حذف دون <b>اعتماد مرتبط ببصمة محتوى الإجراء</b>، '
         'بصلاحية زمنية 48 ساعة ومفتاح idempotency يمنع التكرار — وكل شيء يُسجَّل في التدقيق.</p></div>')

    h += '<div class="card"><h2>⏳ بانتظار اعتمادك</h2>'
    if not pend:
        h += "<p style='margin:4px'>لا شيء بانتظار الاعتماد ✅</p>"
    for a in pend:
        h += (f'<div class="rec"><b>{esc(a["action_id"])}</b> '
              f'<span class="pill teal">{esc(a["type"])}</span>'
              f'<span class="pill warn">ينتهي {esc(a["expires_at"])}</span>'
              f'<div class="draft" style="margin-top:8px">{esc(a["content"])}</div>'
              + cmd_box(f'python3 engine/approve.py approve {a["action_id"]} --hash {a["content_hash"]}')
              + cmd_box(f'python3 engine/approve.py reject {a["action_id"]} --reason "..."')
              + '</div>')
    h += '</div>'

    h += '<div class="card" style="background:#e9f7ef;border-color:#cbe8d6"><h2 style="color:#1e6b44;border-color:#2f9461">✅ معتمدة — جاهزة للتنفيذ</h2>'
    if not appr:
        h += "<p style='margin:4px'>لا إجراءات معتمدة قيد التنفيذ.</p>"
    for a in appr:
        h += (f'<div class="rec"><b>{esc(a["action_id"])}</b> عُتمدت {esc(a.get("approved_at", ""))}'
              f'<div class="draft" style="margin-top:8px">{esc(a["content"])}</div>'
              + cmd_box(f'python3 engine/approve.py executed {a["action_id"]}')
              + '</div>')
    h += '</div>'

    if done:
        h += '<div class="card"><h2>📜 سجل الإجراءات المغلقة</h2><ul>'
        for a in done:
            st = {"EXECUTED": "📤 نُفّذ", "EXPIRED": "🕐 انتهت صلاحيته", "REJECTED": "🚫 مرفوض"}[a["status"]]
            h += f"<li>{esc(a['action_id'])} — {st} — {esc(a['type'])}</li>"
        h += '</ul></div>'

    h += ('<div class="card"><h2>⚙️ كيف تعمل البوابة؟</h2><ul>'
          '<li><b>ربط البصمة:</b> أمر الاعتماد يحمل بصمة SHA-256 (مقتطعة) لنص الإجراء — أي تعديل للنص يُبطل الأمر.</li>'
          '<li><b>الصلاحية الزمنية:</b> 48 ساعة ثم EXPIRED تلقائيًا — لا اعتمادات معلقة للأبد.</li>'
          '<li><b>Idempotency:</b> الإجراء نفسه لا يُدرج في الطابور مرتين (تُفحص البصمة عند الإدراج).</li>'
          '<li><b>التدقيق:</b> approve/reject/executed/expire كلها أحداث في <code>data/audit.jsonl</code>.</li>'
          '<li><b>المرحلة القادمة:</b> زر اعتماد مباشر من تيليجرام/ويب يكتب في نفس الطابور، وأدوات إرسال تنفّذ EXECUTED فعليًا.</li>'
          '</ul></div>')
    return h
