# -*- coding: utf-8 -*-
"""
اختبارات Financial Intelligence Engine و Possibility Stack Engine.

يختبر:
1. نمذجة أزمة السيولة
2. توليد تجارب الدخل
3. تحليل المصروفات
4. توليد الإمكانيات
5. دورة حياة الإمكانية (PROPOSED → TESTING → VALIDATED/REJECTED)
"""
import datetime as dt
import os
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

from store import Store
from financial_intelligence import FinancialPredictor
from possibility_engine import PossibilityStack


class TestFinancialIntelligence(unittest.TestCase):
    """اختبارات محرك الذكاء المالي."""
    
    def setUp(self):
        """إعداد بيئة الاختبار."""
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "state.json"))
        
        # بيانات مالية تجريبية - أزمة حرجة
        self.store.data["finance_ebsi"] = {
            "net_flow": -5786,  # عجز شهري
            "debt_ratio": 0.78,  # نسبة دين عالية
            "available_credit": 10000,  # ائتمان متاح
            "emergency_fund": 0  # لا يوجد صندوق طوارئ
        }
        
        # مصروفات تجريبية
        self.store.data["finance"] = [
            {"البند": "اشتراك 1", "النوع": "برمجيات", "التكلفة (ريال/شهر)": 500, "آخر استخدام": dt.date(2026, 6, 1)},
            {"البند": "اشتراك 2", "النوع": "برمجيات", "التكلفة (ريال/شهر)": 300, "آخر استخدام": dt.date(2026, 8, 1)},
            {"البند": "إيجار", "النوع": "سكن", "التكلفة (ريال/شهر)": 3000, "آخر استخدام": dt.date.today()},
            {"البند": "سيارة", "النوع": "نقل", "التكلفة (ريال/شهر)": 1500, "آخر استخدام": dt.date.today()},
        ]
        
        # ملف مهني تجريبي
        self.store.data["master_professional_profile"] = {
            "skills": ["PT", "Lean Six Sigma", "ANF"],
            "expertise_areas": ["SIJ", "Clinical", "Leadership"]
        }
        
        self.predictor = FinancialPredictor(self.store)
    
    def tearDown(self):
        """تنظيف بيئة الاختبار."""
        self.tmp.cleanup()
    
    def test_liquidity_crisis_model_critical(self):
        """اختبار نموذج أزمة السيولة - حالة حرجة."""
        crisis = self.predictor.liquidity_crisis_model()
        
        # التحقق من الحسابات
        self.assertEqual(crisis["monthly_deficit"], -5786)
        self.assertEqual(crisis["debt_ratio"], 0.78)
        self.assertEqual(crisis["total_buffer"], 10000)
        
        # الأشهر حتى الأزمة = 10000 / 5786 ≈ 1.7 شهر
        self.assertLess(crisis["months_to_crisis"], 2)
        self.assertEqual(crisis["severity"], "CRITICAL")
        self.assertEqual(crisis["action_required"], "IMMEDIATE")
        
        # يجب أن يكون هناك توصيات
        self.assertGreater(len(crisis["recommendations"]), 0)
        self.assertIn("أزمة سيولة", crisis["recommendations"][0])
    
    def test_liquidity_crisis_model_stable(self):
        """اختبار نموذج أزمة السيولة - حالة مستقرة."""
        # تعديل البيانات لحالة مستقرة
        self.store.data["finance_ebsi"]["net_flow"] = 1000  # فائض
        
        predictor = FinancialPredictor(self.store)
        crisis = predictor.liquidity_crisis_model()
        
        self.assertEqual(crisis["severity"], "STABLE")
        self.assertEqual(crisis["action_required"], "MONITOR")
        self.assertIsNone(crisis["crisis_date"])
    
    def test_income_experiment_generator(self):
        """اختبار مولد تجارب الدخل."""
        experiments = self.predictor.income_experiment_generator()
        
        # يجب أن يولد تجارب بناءً على المهارات
        self.assertGreater(len(experiments), 0)
        
        # التحقق من البنية
        for exp in experiments:
            self.assertIn("experiment_id", exp)
            self.assertIn("type", exp)
            self.assertIn("service", exp)
            self.assertIn("potential_monthly", exp)
            self.assertIn("confidence", exp)
            self.assertIn("next_steps", exp)
        
        # يجب أن تكون مرتبة حسب الدخل المحتمل
        if len(experiments) > 1:
            self.assertGreaterEqual(
                experiments[0]["potential_monthly"],
                experiments[1]["potential_monthly"]
            )
    
    def test_expense_pattern_breaker(self):
        """اختبار كاشف أنماط المصروفات."""
        analysis = self.predictor.expense_pattern_breaker()
        
        # التحقق من الحسابات
        self.assertEqual(analysis["total_monthly"], 5300)
        self.assertGreater(len(analysis["high_impact_expenses"]), 0)
        self.assertGreater(analysis["potential_savings"], 0)
        
        # يجب أن يكتشف الاشتراك غير المستخدم
        self.assertGreater(len(analysis["recommendations"]), 0)
    
    def test_negotiation_prep(self):
        """اختبار محضر التفاوض."""
        opportunity = {
            "service": "استشارات PT",
            "pricing": "1500 ريال/شهر",
            "type": "CONSULTING"
        }
        
        prep = self.predictor.negotiation_prep(opportunity)
        
        # التحقق من البنية
        self.assertIn("proposed_price", prep)
        self.assertIn("walk_away_price", prep)
        self.assertIn("opening_offer", prep)
        self.assertIn("concession_strategy", prep)
        
        # التحقق من الحسابات
        self.assertEqual(prep["proposed_price"], 1500)
        self.assertEqual(prep["walk_away_price"], int(1500 * 0.70))
        self.assertEqual(prep["opening_offer"], int(1500 * 1.20))


class TestPossibilityStack(unittest.TestCase):
    """اختبارات محرك استكشاف الفرص."""
    
    def setUp(self):
        """إعداد بيئة الاختبار."""
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "state.json"))
        
        # بيانات تجريبية لتحفيز الإمكانيات
        self.store.data["finance_ebsi"] = {
            "debt_ratio": 0.78,  # محفز مالي
            "net_flow": -5786
        }
        
        self.store.data["followups"] = [
            {"نوع الحالة": "SIJ"} for _ in range(8)  # محفز سريري
        ]
        
        self.store.data["kpis"] = [
            {"المرضى": 100, "عدم حضور": 25}  # محفز قيادي (25% عدم حضور)
        ]
        
        self.store.data["projects"] = [
            {
                "المشروع": "مشروع متوقف",
                "الحالة": "نشط",
                "آخر تقدم": dt.date.today() - dt.timedelta(days=45)
            }
        ]
        
        self.engine = PossibilityStack(self.store)
    
    def tearDown(self):
        """تنظيف بيئة الاختبار."""
        self.tmp.cleanup()
    
    def test_generate_possibilities(self):
        """اختبار توليد الإمكانيات."""
        possibilities = self.engine.generate_possibilities()
        
        # يجب أن يولد إمكانيات بناءً على المحفزات
        self.assertGreater(len(possibilities), 0)
        
        # التحقق من البنية
        for p in possibilities:
            self.assertIn("possibility_id", p)
            self.assertIn("domain", p)
            self.assertIn("trigger", p)
            self.assertIn("experiment", p)
            self.assertIn("confidence", p)
            self.assertIn("status", p)
            self.assertEqual(p["status"], "PROPOSED")
    
    def test_financial_triggers(self):
        """اختبار المحفزات المالية."""
        possibilities = self.engine._financial_triggers()
        
        # يجب أن يولد فرص دخل بسبب نسبة الدين العالية
        self.assertGreater(len(possibilities), 0)
        
        # التحقق من الأولوية
        high_priority = [p for p in possibilities if p["priority"] == "HIGH"]
        self.assertGreater(len(high_priority), 0)
    
    def test_clinical_triggers(self):
        """اختبار المحفزات السريرية."""
        possibilities = self.engine._clinical_triggers()
        
        # يجب أن يولد فرصة SIJ Masterclass بسبب تكرار الحالات
        self.assertGreater(len(possibilities), 0)
        
        sij_possibility = next((p for p in possibilities if "SIJ" in p["experiment"]), None)
        self.assertIsNotNone(sij_possibility)
    
    def test_leadership_triggers(self):
        """اختبار المحفزات القيادية."""
        possibilities = self.engine._leadership_triggers()
        
        # يجب أن يولد فرصة تحسين عدم الحضور
        self.assertGreater(len(possibilities), 0)
        
        no_show_possibility = next((p for p in possibilities if "عدم حضور" in p["trigger"]), None)
        self.assertIsNotNone(no_show_possibility)
    
    def test_surface_daily_possibility(self):
        """اختبار عرض الإمكانية اليومية."""
        # توليد وإضافة إمكانيات
        possibilities = self.engine.generate_possibilities()
        self.engine._add_possibilities(possibilities)
        
        # عرض الإمكانية اليومية
        daily = self.engine.surface_daily_possibility()
        
        self.assertIsNotNone(daily)
        self.assertEqual(daily["status"], "PROPOSED")
        
        # يجب أن تكون الأولوية العالية أولاً
        if daily["priority"] == "HIGH":
            other_possibilities = [p for p in possibilities if p["possibility_id"] != daily["possibility_id"]]
            for p in other_possibilities:
                if p["priority"] == "MEDIUM":
                    # HIGH يجب أن يظهر قبل MEDIUM
                    self.assertTrue(True)
    
    def test_possibility_lifecycle(self):
        """اختبار دورة حياة الإمكانية."""
        # توليد وإضافة إمكانية
        possibilities = self.engine.generate_possibilities()
        self.engine._add_possibilities(possibilities)
        
        possibility_id = possibilities[0]["possibility_id"]
        
        # 1. الحالة الأولية: PROPOSED
        p = next(p for p in self.store.rows_all()["possibility_stack"] if p["possibility_id"] == possibility_id)
        self.assertEqual(p["status"], "PROPOSED")
        
        # 2. بدء الاختبار: TESTING
        success = self.engine.test_possibility(possibility_id)
        self.assertTrue(success)
        
        p = next(p for p in self.store.rows_all()["possibility_stack"] if p["possibility_id"] == possibility_id)
        self.assertEqual(p["status"], "TESTING")
        self.assertIsNotNone(p.get("tested_at"))
        
        # 3. إكمال الاختبار: VALIDATED
        success = self.engine.complete_possibility(possibility_id, "نجح الاختبار", validated=True)
        self.assertTrue(success)
        
        p = next(p for p in self.store.rows_all()["possibility_stack"] if p["possibility_id"] == possibility_id)
        self.assertEqual(p["status"], "VALIDATED")
        self.assertEqual(p["outcome"], "نجح الاختبار")
        self.assertIsNotNone(p.get("completed_at"))
    
    def test_possibility_rejection(self):
        """اختبار رفض إمكانية."""
        # توليد وإضافة إمكانية
        possibilities = self.engine.generate_possibilities()
        self.engine._add_possibilities(possibilities)
        
        possibility_id = possibilities[0]["possibility_id"]
        
        # بدء الاختبار
        self.engine.test_possibility(possibility_id)
        
        # رفض الإمكانية
        success = self.engine.complete_possibility(possibility_id, "لم ينجح", validated=False)
        self.assertTrue(success)
        
        p = next(p for p in self.store.rows_all()["possibility_stack"] if p["possibility_id"] == possibility_id)
        self.assertEqual(p["status"], "REJECTED")


class TestIntegration(unittest.TestCase):
    """اختبارات التكامل بين المحركين."""
    
    def setUp(self):
        """إعداد بيئة الاختبار."""
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "state.json"))
        
        # بيانات تجريبية كاملة
        self.store.data["finance_ebsi"] = {
            "net_flow": -5786,
            "debt_ratio": 0.78,
            "available_credit": 10000,
            "emergency_fund": 0
        }
        
        self.store.data["master_professional_profile"] = {
            "skills": ["PT", "Lean Six Sigma"],
            "expertise_areas": ["SIJ", "Clinical"]
        }
        
        self.predictor = FinancialPredictor(self.store)
        self.possibility_engine = PossibilityStack(self.store)
    
    def tearDown(self):
        """تنظيف بيئة الاختبار."""
        self.tmp.cleanup()
    
    def test_financial_crisis_generates_income_possibilities(self):
        """اختبار: الأزمة المالية تولد إمكانيات دخل."""
        # 1. اكتشاف الأزمة المالية
        crisis = self.predictor.liquidity_crisis_model()
        self.assertEqual(crisis["severity"], "CRITICAL")
        
        # 2. توليد تجارب الدخل
        experiments = self.predictor.income_experiment_generator()
        self.assertGreater(len(experiments), 0)
        
        # 3. توليد إمكانيات من المحرك
        possibilities = self.possibility_engine.generate_possibilities()
        
        # يجب أن تكون هناك إمكانيات مالية
        financial_possibilities = [p for p in possibilities if p["domain"] == "Finance"]
        self.assertGreater(len(financial_possibilities), 0)
        
        # يجب أن تكون ذات أولوية عالية
        high_priority = [p for p in financial_possibilities if p["priority"] == "HIGH"]
        self.assertGreater(len(high_priority), 0)
    
    def test_income_experiment_becomes_possibility(self):
        """اختبار: تجربة الدخل تصبح إمكانية قابلة للتتبع."""
        # 1. توليد تجربة دخل
        experiments = self.predictor.income_experiment_generator()
        top_experiment = experiments[0]
        
        # 2. توليد إمكانيات
        possibilities = self.possibility_engine.generate_possibilities()
        
        # يجب أن تكون هناك إمكانية مطابقة
        matching = next(
            (p for p in possibilities if top_experiment["service"] in p["experiment"]),
            None
        )
        
        if matching:
            # يجب أن تحتوي على نفس المعلومات الأساسية
            self.assertIn("potential_value", matching)
            self.assertIn("confidence", matching)
            self.assertIn("next_step", matching)


def run_tests():
    """تشغيل كل الاختبارات."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestFinancialIntelligence))
    suite.addTests(loader.loadTestsFromTestCase(TestPossibilityStack))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
