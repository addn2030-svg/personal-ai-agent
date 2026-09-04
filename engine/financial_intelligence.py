# -*- coding: utf-8 -*-
"""
Financial Intelligence Engine — نظام التنبؤ المالي والتحليل الاستباقي.

الوظائف الرئيسية:
1. نمذجة أزمة السيولة (متى تحدث الأزمة المالية)
2. مولد تجارب الدخل (S-side من E-S-B-I)
3. كاشف أنماط المصروفات (تحليل باريتو)
4. محضر التفاوض التلقائي

الاستخدام:
  python3 engine/financial_intelligence.py status
  python3 engine/financial_intelligence.py predict
  python3 engine/financial_intelligence.py experiments
  python3 engine/financial_intelligence.py expenses
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from typing import Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TODAY = dt.date.today()


class FinancialPredictor:
    """محرك التنبؤ المالي والتحليل الاستباقي."""
    
    def __init__(self, store: Optional[Store] = None):
        self.store = store or Store()
        self.state = self.store.rows_all()
    
    def liquidity_crisis_model(self) -> Dict:
        """نمذجة أزمة السيولة - متى تحدث الأزمة المالية؟
        
        Returns:
            Dict containing:
                - crisis_date: تاريخ الأزمة المتوقع
                - months_to_crisis: عدد الأشهر المتبقية
                - severity: CRITICAL | WARNING | STABLE
                - action_required: IMMEDIATE | URGENT | MONITOR
                - recommendations: قائمة التوصيات
        """
        febsi = self.state.get("finance_ebsi") or {}
        
        # البيانات المالية الحالية
        monthly_deficit = febsi.get("net_flow", 0)  # العجز الشهري
        debt_ratio = febsi.get("debt_ratio", 0)  # نسبة الدين
        available_credit = febsi.get("available_credit", 0)  # الائتمان المتاح
        emergency_fund = febsi.get("emergency_fund", 0)  # صندوق الطوارئ
        
        # حساب الأشهر حتى الأزمة
        if monthly_deficit >= 0:
            # لا يوجد عجز - الوضع مستقر
            return {
                "crisis_date": None,
                "months_to_crisis": float("inf"),
                "severity": "STABLE",
                "action_required": "MONITOR",
                "recommendations": ["الوضع المالي مستقر - استمر في المراقبة"]
            }
        
        # إجمالي السيولة المتاحة
        total_buffer = available_credit + emergency_fund
        
        if total_buffer <= 0:
            months_to_crisis = 0
        else:
            months_to_crisis = total_buffer / abs(monthly_deficit)
        
        # تحديد الخطورة
        if months_to_crisis < 2:
            severity = "CRITICAL"
            action_required = "IMMEDIATE"
        elif months_to_crisis < 6:
            severity = "WARNING"
            action_required = "URGENT"
        else:
            severity = "STABLE"
            action_required = "MONITOR"
        
        # حساب تاريخ الأزمة
        crisis_date = TODAY + dt.timedelta(days=int(30 * months_to_crisis))
        
        # التوصيات
        recommendations = self._generate_crisis_recommendations(
            months_to_crisis, debt_ratio, monthly_deficit
        )
        
        result = {
            "crisis_date": crisis_date.isoformat() if crisis_date else None,
            "months_to_crisis": round(months_to_crisis, 1),
            "severity": severity,
            "action_required": action_required,
            "monthly_deficit": monthly_deficit,
            "debt_ratio": debt_ratio,
            "total_buffer": total_buffer,
            "recommendations": recommendations
        }
        
        # تسجيل في Audit Log
        log_event("financial_crisis_prediction", **result)
        
        return result
    
    def _generate_crisis_recommendations(
        self, months_to_crisis: float, debt_ratio: float, monthly_deficit: float
    ) -> List[str]:
        """توليد التوصيات بناءً على الوضع المالي."""
        recs = []
        
        if months_to_crisis < 2:
            recs.append("🚨 أزمة سيولة خلال شهرين - اتخذ إجراءات فورية")
            recs.append("1. ابدأ تجربة دخل S فوراً (استشارات PT)")
            recs.append("2. قلل المصروفات غير الضرورية بنسبة 30%")
            recs.append("3. تفاوض على تأجيل الديون قصيرة الأجل")
        elif months_to_crisis < 6:
            recs.append("⚠️ تحذير: أزمة سيولة خلال 6 أشهر")
            recs.append("1. ابدأ تجربة دخل S خلال أسبوعين")
            recs.append("2. راجع المصروفات الكبيرة (تحليل باريتو)")
        
        if debt_ratio > 0.70:
            recs.append(f"📊 نسبة الدين عالية ({debt_ratio:.0%}) - استهدف تقليلها إلى 50%")
        
        if abs(monthly_deficit) > 5000:
            recs.append(f"💰 العجز الشهري كبير ({abs(monthly_deficit):,.0f} ريال)")
            recs.append("   الهدف: تقليله إلى 2000 ريال خلال 3 أشهر")
        
        return recs
    
    def income_experiment_generator(self) -> List[Dict]:
        """مولد تجارب الدخل - S-side من إطار E-S-B-I.
        
        يحلل المهارات والخبرات ويولد تجارب دخل محتملة.
        
        Returns:
            List of experiments sorted by potential_monthly (highest first)
        """
        experiments = []
        
        # تحميل الملف المهني والمهارات
        profile = self.state.get("master_professional_profile") or {}
        skills = profile.get("skills", [])
        expertise = profile.get("expertise_areas", [])
        
        # تجربة 1: استشارات العلاج الطبيعي (SIJ)
        if any("PT" in str(s) or "علاج طبيعي" in str(s) for s in skills):
            experiments.append({
                "experiment_id": "EXP-FIN-001",
                "type": "CONSULTING",
                "domain": "Clinical",
                "service": "بروتوكول تقييم SIJ للعيادات الخاصة",
                "description": "تقديم استشارات تقييم وعلاج مفصل SI للعيادات الخاصة",
                "target_market": "3 عيادات خاصة في الجبيل/الدمام",
                "pricing": "1500 ريال/عيادة/شهر",
                "potential_monthly": 4500,
                "time_investment_hours": 4,  # 4 ساعات/أسبوع
                "startup_cost": 0,
                "confidence": 0.70,
                "next_steps": [
                    "صياغة عرض من صفحة واحدة (الجمعة)",
                    "تحديد 3 عيادات مستهدفة",
                    "إرسال العروض (الأسبوع القادم)"
                ],
                "success_criteria": "عيادة واحدة توافق خلال أسبوعين",
                "status": "PROPOSED"
            })
        
        # تجربة 2: ورش Lean Six Sigma للمستشفيات
        if any("Lean" in str(s) or "Six Sigma" in str(s) for s in skills):
            experiments.append({
                "experiment_id": "EXP-FIN-002",
                "type": "TRAINING",
                "domain": "Leadership",
                "service": "ورشة Lean Healthcare لأقسام التأهيل",
                "description": "ورشة عمل يوم كامل عن تطبيق Lean في التأهيل الطبي",
                "target_market": "مستشفيات المنطقة الشرقية",
                "pricing": "5000 ريال/ورشة",
                "potential_monthly": 5000,  # ورشة واحدة/شهر
                "time_investment_hours": 8,  # 8 ساعات/شهر
                "startup_cost": 500,  # مواد تدريبية
                "confidence": 0.65,
                "next_steps": [
                    "إنشاء مخطط الورشة (الأسبوع القادم)",
                    "تصميم المواد التدريبية",
                    "التواصل مع 5 مستشفيات"
                ],
                "success_criteria": "حجز ورشة واحدة خلال شهر",
                "status": "PROPOSED"
            })
        
        # تجربة 3: محتوى تعليمي (SIJ Masterclass)
        experiments.append({
            "experiment_id": "EXP-FIN-003",
            "type": "CONTENT",
            "domain": "Clinical + Content",
            "service": "سلسلة فيديو SIJ Masterclass",
            "description": "دورة فيديو متخصصة في تقييم وعلاج مفصل SI",
            "target_market": "أخصائيو العلاج الطبيعي (عربي/إنجليزي)",
            "pricing": "299 ريال/دورة",
            "potential_monthly": 1500,  # 5 مبيعات/شهر (متحفظ)
            "time_investment_hours": 20,  # 20 ساعة إنتاج أولي
            "startup_cost": 200,  # معدات تصوير
            "confidence": 0.60,
            "next_steps": [
                "مخطط الوحدة الأولى (الأسبوع القادم)",
                "تصوير فيديو تجريبي",
                "اختبار السوق (مجموعة صغيرة)"
            ],
            "success_criteria": "3 مبيعات في الشهر الأول",
            "status": "PROPOSED",
            "notes": "دخل سلبي محتمل بعد الإنتاج الأولي"
        })
        
        # تجربة 4: استشارات ANF (إذا كانت لديك خبرة)
        if any("ANF" in str(s) for s in expertise):
            experiments.append({
                "experiment_id": "EXP-FIN-004",
                "type": "CONSULTING",
                "domain": "Clinical",
                "service": "استشارات تطبيق ANF في المستشفيات",
                "description": "مساعدة المستشفيات في دمج تقنية ANF",
                "target_market": "مستشفيات خاصة تبحث عن تقنيات جديدة",
                "pricing": "3000 ريال/مستشفى/شهر",
                "potential_monthly": 3000,
                "time_investment_hours": 6,
                "startup_cost": 0,
                "confidence": 0.55,
                "next_steps": [
                    "إعداد دراسة حالة من تجربتك",
                    "تحديد مستشفيات مستهدفة",
                    "عرض تجريبي مجاني"
                ],
                "success_criteria": "مستشفى واحد يوافق على تجربة",
                "status": "PROPOSED"
            })
        
        # ترتيب حسب الدخل المحتمل
        experiments.sort(key=lambda x: x["potential_monthly"], reverse=True)
        
        # تسجيل في Audit Log
        log_event("income_experiments_generated", count=len(experiments))
        
        return experiments
    
    def expense_pattern_breaker(self) -> Dict:
        """كاشف أنماط المصروفات - تحليل باريتو (20/80).
        
        يحدد 20% من المصروفات التي تسبب 80% من الاستنزاف.
        
        Returns:
            Dict containing:
                - high_impact_expenses: المصروفات عالية التأثير
                - potential_savings: التوفير المحتمل
                - recommendations: توصيات التقليل
        """
        finance = self.state.get("finance", [])
        
        if not finance:
            return {
                "high_impact_expenses": [],
                "potential_savings": 0,
                "total_monthly": 0,
                "recommendations": ["لا توجد بيانات مصروفات"]
            }
        
        # حساب الإجمالي
        total_monthly = sum(f.get("التكلفة (ريال/شهر)", 0) or 0 for f in finance)
        
        # ترتيب حسب التكلفة
        sorted_expenses = sorted(
            finance,
            key=lambda x: x.get("التكلفة (ريال/شهر)", 0) or 0,
            reverse=True
        )
        
        # تحليل باريتو: أعلى 20% من المصروفات
        cumulative = 0
        target = total_monthly * 0.8
        high_impact = []
        
        for expense in sorted_expenses:
            cost = expense.get("التكلفة (ريال/شهر)", 0) or 0
            cumulative += cost
            high_impact.append({
                "item": expense.get("البند", "غير محدد"),
                "type": expense.get("النوع", "غير محدد"),
                "cost": cost,
                "last_used": expense.get("آخر استخدام"),
                "renewal_date": expense.get("تاريخ التجديد"),
                "cumulative_percentage": (cumulative / total_monthly * 100) if total_monthly > 0 else 0
            })
            
            if cumulative >= target:
                break
        
        # حساب التوفير المحتمل (30% من المصروفات عالية التأثير)
        high_impact_total = sum(e["cost"] for e in high_impact)
        potential_savings = high_impact_total * 0.30
        
        # توليد التوصيات
        recommendations = self._generate_expense_recommendations(high_impact)
        
        result = {
            "high_impact_expenses": high_impact,
            "high_impact_count": len(high_impact),
            "high_impact_total": high_impact_total,
            "potential_savings": potential_savings,
            "potential_savings_annual": potential_savings * 12,
            "total_monthly": total_monthly,
            "recommendations": recommendations
        }
        
        # تسجيل في Audit Log
        log_event("expense_analysis", 
                  high_impact_count=len(high_impact),
                  potential_savings=potential_savings)
        
        return result
    
    def _generate_expense_recommendations(self, high_impact: List[Dict]) -> List[str]:
        """توليد توصيات تقليل المصروفات."""
        recs = []
        
        # تحليل الاشتراكات غير المستخدمة
        unused = [e for e in high_impact 
                  if e.get("last_used") and 
                  isinstance(e.get("last_used"), dt.date) and
                  (TODAY - e["last_used"]).days > 60]
        
        if unused:
            recs.append(f"🔴 إلغاء الاشتراكات غير المستخدمة ({len(unused)} بنود):")
            for e in unused[:3]:  # أعلى 3
                recs.append(f"   - {e['item']}: {e['cost']:,.0f} ريال/شهر (آخر استخدام: {(TODAY - e['last_used']).days} يوماً)")
        
        # تحليل الاشتراكات المكررة
        by_type = {}
        for e in high_impact:
            t = e.get("type", "غير محدد")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)
        
        duplicates = {t: items for t, items in by_type.items() if len(items) > 1}
        if duplicates:
            recs.append(f"🔴 دمج الاشتراكات المكررة ({len(duplicates)} أنواع):")
            for t, items in list(duplicates.items())[:2]:  # أعلى 2
                total = sum(i["cost"] for i in items)
                recs.append(f"   - {t}: {len(items)} اشتراكات = {total:,.0f} ريال/شهر")
        
        # توصيات عامة
        if high_impact:
            top_expense = high_impact[0]
            recs.append(f"💡 أكبر مصروف: {top_expense['item']} ({top_expense['cost']:,.0f} ريال/شهر)")
            recs.append(f"   هل يمكن تقليله أو إيجاد بديل أرخص؟")
        
        return recs
    
    def negotiation_prep(self, opportunity: Dict) -> Dict:
        """محضر التفاوض التلقائي.
        
        Args:
            opportunity: فرصة الدخل (من income_experiment_generator)
        
        Returns:
            Dict containing negotiation strategy
        """
        service = opportunity.get("service", "")
        pricing = opportunity.get("pricing", "")
        
        # استخراج السعر المقترح
        import re
        price_match = re.search(r"(\d+)", pricing)
        proposed_price = int(price_match.group(1)) if price_match else 0
        
        # حساب القيمة المقدمة
        value_proposition = self._calculate_value_proposition(opportunity)
        
        # بحث سعر السوق (تقديري - يحتاج بيانات حقيقية)
        market_rate = self._estimate_market_rate(opportunity)
        
        # حساب الحد الأدنى المقبول (70% من المقترح)
        walk_away_price = int(proposed_price * 0.70)
        
        # حساب العرض الافتتاحي (120% من المقترح)
        opening_offer = int(proposed_price * 1.20)
        
        # استراتيجية التنازلات
        concession_strategy = self._plan_concessions(proposed_price, walk_away_price)
        
        return {
            "service": service,
            "your_value": value_proposition,
            "market_rate": market_rate,
            "proposed_price": proposed_price,
            "walk_away_price": walk_away_price,
            "opening_offer": opening_offer,
            "concession_strategy": concession_strategy,
            "talking_points": self._generate_talking_points(opportunity),
            "objection_responses": self._generate_objection_responses(opportunity)
        }
    
    def _calculate_value_proposition(self, opportunity: Dict) -> str:
        """حساب القيمة المقدمة للعميل."""
        service_type = opportunity.get("type", "")
        
        if service_type == "CONSULTING":
            return "تحسين نتائج المرضى + تقليل وقت التقييم + بروتوكول موحد"
        elif service_type == "TRAINING":
            return "تحسين كفاءة الفريق + تقليل الهدر + زيادة رضا المرضى"
        elif service_type == "CONTENT":
            return "تعليم مستمر + مرجع دائم + شهادة معتمدة"
        else:
            return "قيمة مضافة للعميل"
    
    def _estimate_market_rate(self, opportunity: Dict) -> str:
        """تقدير سعر السوق (يحتاج بيانات حقيقية)."""
        service_type = opportunity.get("type", "")
        
        if service_type == "CONSULTING":
            return "1000-2000 ريال/يوم (متوسط السوق)"
        elif service_type == "TRAINING":
            return "3000-7000 ريال/ورشة (حسب المدة)"
        elif service_type == "CONTENT":
            return "199-499 ريال/دورة (حسب المحتوى)"
        else:
            return "غير محدد"
    
    def _plan_concessions(self, proposed: int, walk_away: int) -> List[Dict]:
        """تخطيط استراتيجية التنازلات."""
        diff = proposed - walk_away
        
        return [
            {
                "round": 1,
                "offer": proposed,
                "message": "السعر المقترح بناءً على القيمة المقدمة"
            },
            {
                "round": 2,
                "offer": proposed - int(diff * 0.3),
                "message": "خصم 10% للعميل الأول"
            },
            {
                "round": 3,
                "offer": proposed - int(diff * 0.6),
                "message": "الحد الأدنى مع شروط إضافية (شهادة، إحالات)"
            },
            {
                "round": 4,
                "offer": walk_away,
                "message": "الحد الأدنى المطلق - أقل من هذا غير مجدٍ"
            }
        ]
    
    def _generate_talking_points(self, opportunity: Dict) -> List[str]:
        """توليد نقاط الحديث للتفاوض."""
        return [
            f"خبرة {opportunity.get('domain', 'متخصصة')} في المجال",
            "نتائج مثبتة مع حالات سابقة",
            "بروتوكول موحد وقابل للتكرار",
            "دعم مستمر بعد التسليم"
        ]
    
    def _generate_objection_responses(self, opportunity: Dict) -> Dict[str, str]:
        """توليد ردود على الاعتراضات المحتملة."""
        return {
            "السعر مرتفع": "السعر يعكس القيمة - توفير الوقت والنتائج الأفضل يعوض التكلفة",
            "نحتاج وقت للتفكير": "مفهوم - يمكنني تقديم تجربة مجانية لمدة أسبوع",
            "لدينا حل حالي": "ممتاز - هل يحقق النتائج المطلوبة؟ يمكنني إضافة قيمة إضافية",
            "الميزانية محدودة": "يمكننا تقسيم الدفع أو البدء بنطاق أصغر"
        }


def cmd_status():
    """عرض الحالة المالية الحالية."""
    predictor = FinancialPredictor()
    crisis = predictor.liquidity_crisis_model()
    
    print("=" * 60)
    print("📊 الحالة المالية الحالية")
    print("=" * 60)
    print(f"العجز الشهري: {crisis['monthly_deficit']:,.0f} ريال")
    print(f"نسبة الدين: {crisis['debt_ratio']:.0%}")
    print(f"السيولة المتاحة: {crisis['total_buffer']:,.0f} ريال")
    print(f"\n⏰ الأشهر حتى الأزمة: {crisis['months_to_crisis']:.1f}")
    print(f"📅 تاريخ الأزمة المتوقع: {crisis['crisis_date']}")
    print(f"🚨 الخطورة: {crisis['severity']}")
    print(f"⚡ الإجراء المطلوب: {crisis['action_required']}")
    
    print(f"\n📋 التوصيات:")
    for i, rec in enumerate(crisis['recommendations'], 1):
        print(f"{i}. {rec}")


def cmd_predict():
    """التنبؤ بالأزمة المالية."""
    predictor = FinancialPredictor()
    crisis = predictor.liquidity_crisis_model()
    
    print("=" * 60)
    print("🔮 نموذج التنبؤ بأزمة السيولة")
    print("=" * 60)
    
    if crisis['months_to_crisis'] == float("inf"):
        print("✅ الوضع المالي مستقر - لا توجد أزمة متوقعة")
    else:
        print(f"⚠️ أزمة سيولة متوقعة خلال {crisis['months_to_crisis']:.1f} شهر")
        print(f"📅 التاريخ المتوقع: {crisis['crisis_date']}")
        print(f"🚨 مستوى الخطورة: {crisis['severity']}")
        
        if crisis['severity'] == "CRITICAL":
            print("\n🔴 تحذير حرج: اتخذ إجراءات فورية!")
        elif crisis['severity'] == "WARNING":
            print("\n🟡 تحذير: ابدأ التخطيط الآن")


def cmd_experiments():
    """عرض تجارب الدخل المقترحة."""
    predictor = FinancialPredictor()
    experiments = predictor.income_experiment_generator()
    
    print("=" * 60)
    print("💡 تجارب الدخل المقترحة (S-side من E-S-B-I)")
    print("=" * 60)
    
    for i, exp in enumerate(experiments, 1):
        print(f"\n{i}. {exp['service']}")
        print(f"   النوع: {exp['type']} | المجال: {exp['domain']}")
        print(f"   💰 الدخل المحتمل: {exp['potential_monthly']:,.0f} ريال/شهر")
        print(f"   ⏱️  الوقت المطلوب: {exp['time_investment_hours']} ساعة/أسبوع")
        print(f"   💵 تكلفة البدء: {exp['startup_cost']:,.0f} ريال")
        print(f"   📊 الثقة: {exp['confidence']:.0%}")
        print(f"   📋 الخطوات التالية:")
        for step in exp['next_steps']:
            print(f"      - {step}")


def cmd_expenses():
    """تحليل المصروفات (باريتو)."""
    predictor = FinancialPredictor()
    analysis = predictor.expense_pattern_breaker()
    
    print("=" * 60)
    print("📊 تحليل المصروفات (قاعدة 20/80)")
    print("=" * 60)
    print(f"الإجمالي الشهري: {analysis['total_monthly']:,.0f} ريال")
    print(f"المصروفات عالية التأثير: {analysis['high_impact_count']} بند")
    print(f"إجمالي عالي التأثير: {analysis['high_impact_total']:,.0f} ريال")
    print(f"💰 التوفير المحتمل: {analysis['potential_savings']:,.0f} ريال/شهر")
    print(f"💰 التوفير السنوي: {analysis['potential_savings_annual']:,.0f} ريال/سنة")
    
    print(f"\n📋 المصروفات عالية التأثير:")
    for i, exp in enumerate(analysis['high_impact_expenses'][:10], 1):
        print(f"{i}. {exp['item']}: {exp['cost']:,.0f} ريال/شهر ({exp['cumulative_percentage']:.0f}% تراكمي)")
    
    print(f"\n💡 التوصيات:")
    for i, rec in enumerate(analysis['recommendations'], 1):
        print(f"{i}. {rec}")


def main():
    """نقطة الدخول الرئيسية."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Financial Intelligence Engine")
    parser.add_argument("command", choices=["status", "predict", "experiments", "expenses"],
                        help="الأمر المطلوب")
    
    args = parser.parse_args()
    
    if args.command == "status":
        cmd_status()
    elif args.command == "predict":
        cmd_predict()
    elif args.command == "experiments":
        cmd_experiments()
    elif args.command == "expenses":
        cmd_expenses()


if __name__ == "__main__":
    main()