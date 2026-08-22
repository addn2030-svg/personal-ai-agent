# -*- coding: utf-8 -*-
import json, os, shutil, sys, tempfile, unittest

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,"engine"))
import skill_registry as sr
import reflection_engine as re
import behavior_model as bm

class SelfImprovementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.mkdtemp(prefix="aios-v06-")
        sr.DATA_DIR=os.path.join(self.tmp,"self"); sr.SKILLS_DIR=os.path.join(self.tmp,"skills"); sr.REGISTRY=os.path.join(sr.DATA_DIR,"skills.json")
        re.DIR=sr.DATA_DIR; re.EXP=os.path.join(re.DIR,"experiences.jsonl"); re.LESSONS=os.path.join(re.DIR,"lessons.json")
        bm.DIR=sr.DATA_DIR; bm.PATH=os.path.join(bm.DIR,"behavior_model.json")
    def tearDown(self): shutil.rmtree(self.tmp,ignore_errors=True)
    def test_repeated_experience_creates_lesson(self):
        for i in range(3): re.capture("workflow","administrative",f"same workflow {i}",outcome="success",tags=["handoff"])
        lessons=re.reflect(min_repeats=3)
        self.assertEqual(len(lessons),1)
        self.assertEqual(lessons[0]["domain"],"administrative")
    def test_review_skill_cannot_activate_without_approval(self):
        s=sr.create_candidate("handoff","administrative","handoff","1. Draft\n2. approval required",["EX-1"])
        with self.assertRaises(PermissionError): sr.set_status(s["id"],"ACTIVE")
        sr.set_status(s["id"],"APPROVED"); sr.set_status(s["id"],"ACTIVE")
        self.assertEqual(sr.list_skills("ACTIVE")[0]["id"],s["id"])
    def test_inference_is_not_confirmation(self):
        x=bm.add("prefers short morning brief","observed",.75,False,"work")
        self.assertEqual(x["status"],"INFERRED")
        self.assertLess(x["confidence"],1.0)
        y=bm.confirm(x["id"]); self.assertEqual(y["status"],"CONFIRMED"); self.assertEqual(y["confidence"],1.0)

if __name__=="__main__": unittest.main()
