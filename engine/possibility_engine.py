# -*- coding: utf-8 -*-
"""
Possibility Stack Engine — محرك استكشاف الفرص التلقائي.

نظام موازٍ لقائمة المهام - يستكشف الفرص بدلاً من إدارة التنفيذ.
يولد إمكانيات جديدة بناءً على الأنماط والمحفزات، ويعرض فرصة واحدة يومياً.

الوظائف الرئيسية:
1. توليد الإمكانيات من الحالة الحالية
2. تتبع حالة كل إمكانية (PROPOSED → TESTING → VALIDATED → REJECTED)
3. عرض إمكانية واحدة يومياً في البريف الصباحي
4. تسجيل النتائج والتعلم من التجارب

الاستخدام:
  python3 engine/possibility_engine.py generate
  python3 engine/possibility_engine.py daily
  python3 engine/possibility_engine.py list
  python3 engine/possibility_engine.py test P-001
  python3 engine/possibility_engine.py complete P-001 --outcome "نجح"
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys
from typing import Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TODAY = dt.date.today()


class PossibilityStack:
    """محرك استكشاف الفرص التلقائي."""
    
    def __init__(self, store: Optional[Store] = None):
        self.store = store or Store()
        self.state = self.store.rows_all()
    
    def generate_possibilities(self) -> List[Dict]:
        """توليد الإمكانيات من الحالة الحالية.
        
        يحلل:
        - المحفزات المالية (نسبة الدين، العجز)
        - أنماط العمل السريري (تكرار الحالات)
        - الصراعات القيادية
        - فرص التعلم
        - الفجوات في المشاريع
        
        Returns:
            List of possibilities
        """
        possibilities = []
        
        # المحفز 1: الأزمة المالية
        possibilities.extend(self._financial_triggers())
        
        # المحفز 2: أنماط العمل السريري
        possibilities.extend(self._clinical_triggers())
        
        # المحفز 3: القيادة والصراعات
        possibilities.extend(self._leadership_triggers())
        
        # المحفز 4: فرص التعلم
        possibilities.extend(self._learning_triggers())
        
        # المحفز 5: المشاريع المتوقفة
        possibilities.extend(self._project_triggers())
        
        # تصفية المكررات (بناءً على content_hash)
        unique = {}
        for p in possibilities:
            h = self._hash(p["experiment"])
            if h not in unique:
                p["content_hash"] = h
                unique[h] = p
        
        return list(unique.values())
    
    def _financial_triggers(self) -> List[Dict]:
        """محفزات مالية - توليد فرص الدخل."""
        possibilities = []
        febsi = self.state.get("finance_ebsi") or {}
        
        debt_ratio = febsi.get("debt_ratio", 0)
        net_flow = febsi.get("net_flow", 0)
        
        # محفز: نسبة دين عالية
        if debt_ratio > 0.70:
            possibilities.append({
                "possibility_id": self._next_id(),
                "domain": "Finance",
                "trigger": f"نسبة الدين عالية ({debt_ratio:.0%})",
                "experiment": "تقديم استشارات PT لـ3 عيادات خاصة",
                "description": "بروتوكول تقييم SIJ متخصص للعيادات الخاصة",
                "cost": 0,
                "confidence": 0.65,
                "potential_value": "2000-3000 ريال/شهر",
                "time_investment": "4 ساعات/أسبوع",
                "next_step": "صياغة عرض من صفحة واحدة (الجمعة)",
                "success_criteria": "عيادة واحدة توافق خلال أسبوعين",
                "status": "PROPOSED",
                "created_at": TODAY.isoformat(),
                "priority": "HIGH" if debt_ratio > 0.75 else "MEDIUM"
            })
        
        # محفز: عجز شهري كبير
        if net_flow < -5000:
            possibilities.append({
                "possibility_id": self._next_id(),
                "domain": "Finance + Leadership",
                "trigger": f"عجز شهري كبير ({abs(net_flow):,.0f} ريال)",
                "experiment": "ورشة Lean Healthcare للمستشفيات",
                "description": "ورشة يوم كامل عن تطبيق Lean في التأهيل الطبي",
                "cost": 500,
                "confidence": 0.60,
                "potential_value": "5000 ريال/ورشة",
                "time_investment": "8 ساعات/شهر",
                "next_step": "إنشاء مخطط الورشة (الأسبوع القادم)",
                "success_criteria": "حجز ورشة واحدة خلال شهر",
                "status": "PROPOSED",
                "created_at": TODAY.isoformat(),
                "priority": "HIGH"
            })
        
        return possibilities
    
    def _clinical_triggers(self) -> List[Dict]:
        """محفزات سريرية - أنماط الحالات."""
        possibilities = []
        followups = self.state.get("followups", [])
        
        # تحليل أنماط الحالات
        case_types = {}
        for f in followups:
            case_type = f.get("نوع الحالة", "غير محدد")
            if case_type not in case_types:
                case_types[case_type] = 0
            case_types[case_type] += 1
        
        # محفز: تكرار حالات SIJ
        sij_count = case_types.get("SIJ", 0) + case_types.get("SI Joint", 0)
        if sij_count >= 5:
            possibilities.append({
                "possibility_id": self._next_id(),
                "domain": "Clinical + Content",
                "trigger": f"نمط حالات SIJ ({sij_count} حالات هذا الشهر)",
                "experiment": "إنشاء سلسلة فيديو 'SIJ Masterclass'",
                "description": "دورة فيديو متخصصة في تقييم وعلاج مفصل SI",
                "cost": 200,
                "confidence": 0.70,
                "potential_value": "دخل سلبي + بناء سلطة",
                "time_investment": "20 ساعة (إنتاج أولي)",
                "next_step": "مخطط الوحدة الأولى (الأسبوع القادم)",
                "success_criteria": "3 مبيعات في الشهر الأول",
                "status": "PROPOSED",
                "created_at": TODAY.isoformat(),
                "priority": "MEDIUM"
            })
        
        # محفز: حالات معقدة متكررة
        if len(followups) > 20:
            possibilities.append({
                "possibility_id": self._next_id(),
                "domain": "Clinical + AI",
                "trigger": f"حجم كبير من المتابعات ({len(followups)} حالة)",
                "experiment": "نظام توثيق سريري ذكي",
                "description": "أتمتة التوثيق السريري باستخدام قوالب ذكية",
                "cost": 0,
                "confidence": 0.75,
                "potential_value": "توفير 30 دقيقة/يوم",
                "time_investment": "10 ساعات (تطوير)",
                "next_step": "رسم خريطة سير العمل الحالي",
                "success_criteria": "تقليل وقت التوثيق بنسبة 40%",
                "status": "PROPOSED",
                "created_at": TODAY.isoformat(),
                "priority": "MEDIUM"
            })
        
        return possibilities
    
    def _leadership_triggers(self) -> List[Dict]:
        """محفزات قيادية - الصراعات والفرص."""
        possibilities = []
        
        # محفز: صراع مع المشرف (من ملاحظات أو قرارات)
        decisions = self.state.get("decisions", [])
        conflict_keywords = ["صراع", "خلاف", "مشرف", "مدير"]
        
        has_conflict = any(
            any(keyword in str(d.get("القرار", "")).lower() for keyword in conflict_keywords)
            for d in decisions[-10:]  # آخر 10 قرارات
        )
        
        if has_conflict:
            possibilities.append({
                "possibility_id": self._next_id(),
                "domain": "Leadership",
                "trigger": "نمط صراع مع المشرف",
                "experiment": "تطبيق بروتوكول 'الاجتماع الصامت'",
                "description": "اجتماع منظم بدون مقاطعات - الكتابة أولاً ثم النقاش",
                "cost": 0,
                "confidence": 0.80,
                "potential_value": "تحسين ديناميكية الفريق",
                "time_investment": "ساعة واحدة (تجربة)",
                "next_step": "اختبار في الاجتماع القادم",
                "success_criteria": "تقليل التوتر والوصول لقرارات أسرع",
                "status": "PROPOSED",
                "created_at": TODAY.isoformat(),
                "priority": "HIGH"
            })
        
        # محفز: مؤشرات القسم تحتاج تحسين
        kpis = self.state.get("kpis", [])
        if kpis:
            latest_kpi = kpis[-1] if kpis else {}
            no_show_rate = latest_kpi.get("عدم حضور", 0) / max(latest_kpi.get("المرضى", 1), 1)
            
            if no_show_rate > 0.20:
                possibilities.append({
                    "possibility_id": self._next_id(),
                    "domain": "Leadership + Operations",
                    "trigger": f"نسبة عدم حضور عالية ({no_show_rate:.0%})",
                    "experiment": "تجربة تأكيد واتساب مساء اليوم السابق",
                    "description": "إرسال تذكير واتساب للمرضى مساء اليوم السابق",
                    "cost": 0,
                    "confidence": 0.85,
                    "potential_value": "تقليل عدم الحضور بنسبة 30-40%",
                    "time_investment": "15 دقيقة/يوم",
                    "next_step": "تجربة لمدة أسبوعين",
                    "success_criteria": "تقليل نسبة عدم الحضور إلى <15%",
                    "status": "PROPOSED",
                    "created_at": TODAY.isoformat(),
                    "priority": "HIGH"
                })
        
        return possibilities
    
    def _learning_triggers(self) -> List[Dict]:
        """محفزات التعلم - فرص التطوير."""
        possibilities = []
        learning = self.state.get("learning", [])
        
        # محفز: مهارة جديدة تم تعلمها لكن لم تُطبق
        not_applied = [l for l in learning 
                       if l.get("الحالة") == "منجزة" 
                       and l.get("طُبِّق عمليًا") in (None, "لا")]
        
        if not_applied:
            skill = not_applied[0].get("المهارة/الموضوع", "المهارة المكتسبة")
            possibilities.append({
                "possibility_id": self._next_id(),
                "domain": "Learning + Application",
                "trigger": f"مهارة مكتسبة لم تُطبق: {skill}",
                "experiment": f"تطبيق {skill} في مشروع صغير",
                "description": "تحويل التعلم النظري إلى تطبيق عملي",
                "cost": 0,
                "confidence": 0.75,
                "potential_value": "ترسيخ المهارة + قيمة عملية",
                "time_investment": "5 ساعات",
                "next_step": "تحديد مشروع تطبيقي صغير",
                "success_criteria": "تطبيق ناجح خلال أسبوعين",
                "status": "PROPOSED",
                "created_at": TODAY.isoformat(),
                "priority": "MEDIUM"
            })
        
        return possibilities
    
    def _project_triggers(self) -> List[Dict]:
        """محفزات المشاريع - المتوقفة والفرص."""
        possibilities = []
        projects = self.state.get("projects", [])
        
        # محفز: مشروع نشط لكن متوقف فعلياً
        stalled = [p for p in projects 
                   if p.get("الحالة") == "نشط" 
                   and isinstance(p.get("آخر تقدم"), dt.date)
                   and (TODAY - p["آخر تقدم"]).days > 30]
        
        if stalled:
            project = stalled[0]
            possibilities.append({
                "possibility_id": self._next_id(),
                "domain": "Projects",
                "trigger": f"مشروع متوقف: {project.get('المشروع', 'غير محدد')}",
                "experiment": "خطوة واحدة صغيرة أو تحويل إلى متوقف",
                "description": "إما استئناف بخطوة محددة أو الاعتراف بالتوقف",
                "cost": 0,
                "confidence": 0.70,
                "potential_value": "وضوح ذهني + تقليل الحمل المعرفي",
                "time_investment": "ساعة واحدة (قرار)",
                "next_step": "اتخاذ قرار: استئناف أو إيقاف",
                "success_criteria": "حالة واضحة للمشروع",
                "status": "PROPOSED",
                "created_at": TODAY.isoformat(),
                "priority": "MEDIUM"
            })
        
        return possibilities
    
    def surface_daily_possibility(self) -> Optional[Dict]:
        """عرض إمكانية واحدة يومياً في البريف الصباحي.
        
        يختار الإمكانية بناءً على:
        1. الأولوية (HIGH أولاً)
        2. الثقة (أعلى ثقة)
        3. الحداثة (الأحدث)
        
        Returns:
            Possibility dict or None
        """
        # تحميل الإمكانيات الحالية
        current_possibilities = self.state.get("possibility_stack", [])
        
        # تصفية الإمكانيات المقترحة فقط
        proposed = [p for p in current_possibilities if p.get("status") == "PROPOSED"]
        
        if not proposed:
            # توليد إمكانيات جديدة إذا لم يكن هناك مقترحات
            new_possibilities = self.generate_possibilities()
            if new_possibilities:
                # إضافة إلى الحالة
                self._add_possibilities(new_possibilities)
                proposed = new_possibilities
        
        if not proposed:
            return None
        
        # ترتيب حسب الأولوية والثقة
        priority_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        sorted_possibilities = sorted(
            proposed,
            key=lambda p: (
                priority_order.get(p.get("priority", "LOW"), 0),
                p.get("confidence", 0),
                p.get("created_at", "")
            ),
            reverse=True
        )
        
        return sorted_possibilities[0]
    
    def test_possibility(self, possibility_id: str) -> bool:
        """بدء اختبار إمكانية.
        
        Args:
            possibility_id: معرف الإمكانية (مثل P-001)
        
        Returns:
            True if successful
        """
        def mutate(S):
            possibilities = S.get("possibility_stack", [])
            possibility = next((p for p in possibilities if p.get("possibility_id") == possibility_id), None)
            
            if not possibility:
                return False, None
            
            if possibility["status"] != "PROPOSED":
                return False, f"الإمكانية في حالة {possibility['status']} - لا يمكن اختبارها"
            
            possibility["status"] = "TESTING"
            possibility["tested_at"] = TODAY.isoformat()
            
            return True, possibility
        
        result = self.store.transaction(mutate, "possibility_test_started", possibility_id=possibility_id)
        
        if result:
            log_event("possibility_test_started", possibility_id=possibility_id)
            return True
        return False
    
    def complete_possibility(self, possibility_id: str, outcome: str, validated: bool = True) -> bool:
        """إكمال اختبار إمكانية وتسجيل النتيجة.
        
        Args:
            possibility_id: معرف الإمكانية
            outcome: النتيجة (نص حر)
            validated: هل نجحت التجربة؟
        
        Returns:
            True if successful
        """
        def mutate(S):
            possibilities = S.get("possibility_stack", [])
            possibility = next((p for p in possibilities if p.get("possibility_id") == possibility_id), None)
            
            if not possibility:
                return False, None
            
            if possibility["status"] != "TESTING":
                return False, f"الإمكانية في حالة {possibility['status']} - يجب أن تكون TESTING"
            
            possibility["status"] = "VALIDATED" if validated else "REJECTED"
            possibility["completed_at"] = TODAY.isoformat()
            possibility["outcome"] = outcome
            
            return True, possibility
        
        result = self.store.transaction(
            mutate, 
            "possibility_completed", 
            possibility_id=possibility_id,
            validated=validated
        )
        
        if result:
            log_event("possibility_completed", 
                     possibility_id=possibility_id,
                     validated=validated,
                     outcome=outcome[:100])
            return True
        return False
    
    def _add_possibilities(self, possibilities: List[Dict]):
        """إضافة إمكانيات جديدة إلى الحالة."""
        def mutate(S):
            current = S.get("possibility_stack", [])
            
            # تصفية المكررات
            existing_hashes = {p.get("content_hash") for p in current}
            new_possibilities = [p for p in possibilities if p.get("content_hash") not in existing_hashes]
            
            if not new_possibilities:
                return False, None
            
            S["possibility_stack"] = current + new_possibilities
            return True, len(new_possibilities)
        
        count = self.store.transaction(mutate, "possibilities_generated")
        
        if count:
            log_event("possibilities_generated", count=count)
        
        return count
    
    def _next_id(self) -> str:
        """توليد معرف إمكانية جديد."""
        current = self.state.get("possibility_stack", [])
        return f"P-{len(current) + 1:03d}"
    
    def _hash(self, text: str) -> str:
        """حساب بصمة SHA-256 للنص."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def cmd_generate():
    """توليد إمكانيات جديدة."""
    engine = PossibilityStack()
    possibilities = engine.generate_possibilities()
    
    print("=" * 60)
    print("💡 الإمكانيات المولدة")
    print("=" * 60)
    print(f"العدد: {len(possibilities)}")
    
    for i, p in enumerate(possibilities, 1):
        print(f"\n{i}. [{p['possibility_id']}] {p['experiment']}")
        print(f"   المجال: {p['domain']}")
        print(f"   المحفز: {p['trigger']}")
        print(f"   القيمة المحتملة: {p['potential_value']}")
        print(f"   الثقة: {p['confidence']:.0%}")
        print(f"   الأولوية: {p['priority']}")
        print(f"   الخطوة التالية: {p['next_step']}")
    
    # إضافة إلى الحالة
    if possibilities:
        engine._add_possibilities(possibilities)
        print(f"\n✅ تم إضافة {len(possibilities)} إمكانية إلى الحالة")


def cmd_daily():
    """عرض الإمكانية اليومية."""
    engine = PossibilityStack()
    possibility = engine.surface_daily_possibility()
    
    print("=" * 60)
    print("💡 إمكانية اليوم")
    print("=" * 60)
    
    if not possibility:
        print("لا توجد إمكانيات مقترحة حالياً")
        return
    
    print(f"\n🎯 {possibility['experiment']}")
    print(f"المجال: {possibility['domain']}")
    print(f"المحفز: {possibility['trigger']}")
    print(f"\n📝 الوصف:")
    print(f"   {possibility['description']}")
    print(f"\n💰 القيمة المحتملة: {possibility['potential_value']}")
    print(f"⏱️  الوقت المطلوب: {possibility['time_investment']}")
    print(f"💵 التكلفة: {possibility['cost']} ريال")
    print(f"📊 الثقة: {possibility['confidence']:.0%}")
    print(f"\n📋 الخطوة التالية:")
    print(f"   {possibility['next_step']}")
    print(f"\n✅ معيار النجاح:")
    print(f"   {possibility['success_criteria']}")
    print(f"\n🔖 لبدء الاختبار:")
    print(f"   python3 engine/possibility_engine.py test {possibility['possibility_id']}")


def cmd_list():
    """عرض كل الإمكانيات."""
    engine = PossibilityStack()
    possibilities = engine.state.get("possibility_stack", [])
    
    print("=" * 60)
    print("📋 كل الإمكانيات")
    print("=" * 60)
    
    if not possibilities:
        print("لا توجد إمكانيات")
        return
    
    # تجميع حسب الحالة
    by_status = {}
    for p in possibilities:
        status = p.get("status", "UNKNOWN")
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(p)
    
    for status in ["PROPOSED", "TESTING", "VALIDATED", "REJECTED"]:
        if status in by_status:
            print(f"\n{status} ({len(by_status[status])}):")
            for p in by_status[status]:
                print(f"  [{p['possibility_id']}] {p['experiment']}")
                print(f"     {p['domain']} | {p['confidence']:.0%} | {p['priority']}")


def cmd_test(possibility_id: str):
    """بدء اختبار إمكانية."""
    engine = PossibilityStack()
    success = engine.test_possibility(possibility_id)
    
    if success:
        print(f"✅ بدأ اختبار {possibility_id}")
        print("سجل تقدمك واستخدم 'complete' عند الانتهاء")
    else:
        print(f"❌ فشل بدء الاختبار لـ {possibility_id}")


def cmd_complete(possibility_id: str, outcome: str, validated: bool):
    """إكمال اختبار إمكانية."""
    engine = PossibilityStack()
    success = engine.complete_possibility(possibility_id, outcome, validated)
    
    if success:
        status = "✅ نجح" if validated else "❌ فشل"
        print(f"{status} اختبار {possibility_id}")
        print(f"النتيجة: {outcome}")
    else:
        print(f"❌ فشل إكمال {possibility_id}")


def main():
    """نقطة الدخول الرئيسية."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Possibility Stack Engine")
    parser.add_argument("command", choices=["generate", "daily", "list", "test", "complete"],
                        help="الأمر المطلوب")
    parser.add_argument("id", nargs="?", help="معرف الإمكانية (لـ test و complete)")
    parser.add_argument("--outcome", help="النتيجة (لـ complete)")
    parser.add_argument("--validated", action="store_true", help="هل نجحت التجربة؟")
    
    args = parser.parse_args()
    
    if args.command == "generate":
        cmd_generate()
    elif args.command == "daily":
        cmd_daily()
    elif args.command == "list":
        cmd_list()
    elif args.command == "test":
        if not args.id:
            print("❌ يجب تحديد معرف الإمكانية")
            sys.exit(1)
        cmd_test(args.id)
    elif args.command == "complete":
        if not args.id or not args.outcome:
            print("❌ يجب تحديد معرف الإمكانية والنتيجة")
            sys.exit(1)
        cmd_complete(args.id, args.outcome, args.validated)


if __name__ == "__main__":
    main()
