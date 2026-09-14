# -*- coding: utf-8 -*-
"""Build the SC / Enneagram-5 growth library workbook (xlsx + CSV per tab).

Usage:  python3 scripts/build_reading_list.py [out_dir]
Default out_dir: research_capsules/reading-list/
The .xlsx imports directly into Google Sheets (File → Import) with one tab per category.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADERS = ["الفئة", "اسم الكتاب", "المؤلف", "الرابط", "التقييم", "الصفحات", "الملخص", "لماذا يناسبك", "أشهر اقتباس"]

BOOKS = {
    "1- فهم طريقة التفكير": [
        ("Thinking, Fast and Slow", "Daniel Kahneman",
         "https://www.goodreads.com/book/show/11468377-thinking-fast-and-slow", 4.18, 499,
         "الكتاب المرجعي عن النظامين: النظام 1 السريع الحدسي والنظام 2 البطيء التحليلي. يشرح كيف تنشأ الانحيازات المعرفية من هذا التفاعل ولماذا نثق بأحكامنا أكثر مما ينبغي.",
         "النمط 5 يعشق النماذج الذهنية العميقة، وهذا الكتاب يعطيك 'خريطة' عقلك بلغة الأدلة التي تحترمها. سيكشف لك أن التحليل الزائد (النظام 2) ليس دائماً أدق، وأن الثقة المفرطة بالتحليل انحياز بحد ذاته.",
         "Nothing in life is as important as you think it is, while you are thinking about it."),
        ("The Scout Mindset", "Julia Galef",
         "https://www.goodreads.com/book/show/42041926-the-scout-mindset", 4.08, 288,
         "تقارن بين 'عقلية الجندي' التي تدافع عن معتقداتها و'عقلية الكشاف' التي تريد رؤية الواقع كما هو. تقدم أدوات عملية لقياس ثقتك وتحديث معتقداتك دون أن تشعر بالتهديد.",
         "حساسيتك للنقد تنبع من ربط الخطأ بالهوية؛ الكشاف يرى الخطأ معلومة لا هزيمة. الكتاب قصير وعملي — مضاد للكمالية التي تخشى أن تكون مخطئة.",
         "The scout mindset is what allows you to recognize when you were wrong, to seek out your blind spots, to test your assumptions and change course."),
        ("Think Again", "Adam Grant",
         "https://www.goodreads.com/book/show/56701185-think-again", 4.13, 320,
         "لماذا نتمسك بآرائنا ككاهن أو محامٍ أو سياسي بدل أن نفكر كعالِم؟ يشرح فن إعادة التفكير وكيف تبني 'شبكة تحدٍ' حولك.",
         "أنت تجمع المعرفة بعمق لكنك قد تتحصّن بها؛ غرانت يعلّمك أن تحب 'أن تكون مخطئاً' وتستقبل النقد كبيانات جديدة، وهو تدريب مباشر على نقطتي الحساسية للنقد وتراكم المعرفة.",
         "If knowledge is power, knowing what we don't know is wisdom."),
        ("Mistakes Were Made (But Not by Me)", "Carol Tavris & Elliot Aronson",
         "https://www.goodreads.com/book/show/522525.Mistakes_Were_Made_But_Not_by_Me_", 4.04, 292,
         "دراسة التنافر المعرفي وكيف نبرر قراراتنا الخاطئة لأنفسنا بدل الاعتراف بها. مليء بأمثلة من الطب والقانون والعلاقات.",
         "للنمط 5 المهني الذي يخشى أن يبدو غير كفء: يفكك آلية التبرير الذاتي التي تجعل النقد جارحاً، ويبيّن أن الاعتراف بالخطأ هو قمة الكفاءة لا نقيضها.",
         "Dissonance is what happens when we are confronted with evidence that we are wrong."),
        ("The Art of Thinking Clearly", "Rolf Dobelli",
         "https://www.goodreads.com/book/show/16248196-the-art-of-thinking-clearly", 3.86, 384,
         "99 خطأً في التفكير، كل واحد في صفحتين أو ثلاث: من انحياز البقاء إلى مغالطة التكلفة الغارقة. مرجع سريع قابل للرجوع إليه.",
         "يناسب SC الذي يفضّل البنية والتنظيم: فصول قصيرة يمكن قراءتها فصلاً واحداً يومياً وتطبيقها فوراً على قرار حقيقي، بدل الغرق في نظرية طويلة.",
         "Whether we like it or not, we are puppets of our emotions. We make complex decisions by consulting our feelings, not our thoughts."),
    ],
    "2- كسر دوامة التحليل": [
        ("Decisive: How to Make Better Choices in Life and Work", "Chip Heath & Dan Heath",
         "https://www.goodreads.com/book/show/15798078-decisive", 3.96, 320,
         "إطار WRAP الرباعي: وسّع الخيارات، اختبر افتراضاتك بالواقع، خذ مسافة قبل القرار، استعد للخطأ. أمثلة عملية من الشركات والحياة.",
         "يحوّل القرار من 'بحث عن الجواب المثالي' إلى عملية مضبوطة بخطوات — وهذا بالضبط ما يحتاجه SC/5 الذي يجمّد أمام الخيارات. تقنية 10/10/10 و'الفشل المسبق' مضادات مباشرة لشلل التحليل.",
         "Our normal habit in life is to develop a quick belief about a situation and then seek out information that bolsters our belief."),
        ("Thinking in Bets", "Annie Duke",
         "https://www.goodreads.com/book/show/35957157-thinking-in-bets", 3.81, 288,
         "لاعبة بوكر محترفة تعلّمك اتخاذ القرار تحت عدم اليقين: افصل جودة القرار عن جودة النتيجة، وفكر بالاحتمالات لا باليقين.",
         "الكمالية عندك تريد يقيناً 100% قبل التحرك؛ الكتاب يعيد تعريف 'القرار الجيد' بأنه الرهان الأفضل بالمعلومات المتاحة، مما يمنحك إذناً علمياً بالتحرك بمعلومات ناقصة.",
         "What makes a decision great is not that it has a great outcome. A great decision is the result of a good process."),
        ("The Perfectionist's Guide to Losing Control", "Katherine Morgan Schafler",
         "https://www.goodreads.com/book/show/60880794-the-perfectionist-s-guide-to-losing-control", 4.12, 336,
         "معالجة نفسية تصنّف الكمالية إلى 5 أنواع (منها المماطِل والمسوِّف والكلاسيكي) وتعلمك تحويل الكمالية من قوة مدمرة إلى قوة دافعة بدل محاولة التخلص منها.",
         "لا يطلب منك أن تتوقف عن كونك دقيقاً — وهو طلب مستحيل لـ C في DISC — بل يفرق بين الكمالية التكيفية والمعطِّلة، ويعالج 'كمالية تعطّل الإنجاز' مباشرة بتعاطف.",
         "Perfectionism is not the problem. The problem is that you've been taught to fight your perfectionism instead of channel it."),
        ("Finish: Give Yourself the Gift of Done", "Jon Acuff",
         "https://www.goodreads.com/book/show/35397160-finish", 4.13, 208,
         "الكمالية — لا الكسل — هي قاتلة الأهداف رقم 1. استراتيجيات مثل: اقطع هدفك للنصف، اختر ماذا ستفشل فيه عمداً، واجعل المهمة ممتعة.",
         "خفيف وسريع (يمكن إنهاؤه في جلستين) وهذا بحد ذاته تمرين لك على 'الإنهاء'. يناقض ميلك لتعقيد الأهداف والانسحاب عند أول انحراف عن الخطة المثالية.",
         "The day after perfect is what separates finishers from starters."),
        ("The Paradox of Choice", "Barry Schwartz",
         "https://www.goodreads.com/book/show/10639.The_Paradox_of_Choice", 3.84, 265,
         "كثرة الخيارات تُشلّ ولا تُحرّر. يفرق بين 'الباحث عن الأقصى' (Maximizer) الذي يعاني و'المكتفي' (Satisficer) الأسعد والأسرع قراراً.",
         "أنت Maximizer بالفطرة؛ الكتاب يعطيك الدليل العلمي بأن 'الجيد بما يكفي' يؤدي لنتائج أفضل ورضا أعلى، ويمنحك قواعد عملية لتقليل الخيارات قبل التحليل.",
         "Learning to choose is hard. Learning to choose well is harder. And learning to choose well in a world of unlimited possibilities is harder still."),
    ],
    "3- القيادة والذكاء العاطفي": [
        ("Emotional Intelligence 2.0", "Travis Bradberry & Jean Greaves",
         "https://www.goodreads.com/book/show/6486483-emotional-intelligence-2-0", 3.85, 255,
         "دليل تطبيقي للمهارات الأربع: الوعي الذاتي، إدارة الذات، الوعي الاجتماعي، إدارة العلاقات — مع 66 استراتيجية قصيرة واختبار EQ إلكتروني.",
         "نقطة دخول مثالية للنمط 5: منظّم، مرقّم، بلا 'كلام عاطفي' زائد. يعطيك استراتيجيات محددة يمكن التدرب عليها واحدة كل أسبوع بدل مفاهيم مجردة.",
         "Emotional intelligence is your ability to recognize and understand emotions in yourself and others, and your ability to use this awareness to manage your behavior and relationships."),
        ("Emotional Agility", "Susan David",
         "https://www.goodreads.com/book/show/34204326-emotional-agility", 3.98, 288,
         "عالمة نفس من هارفارد تشرح كيف 'تُظهر' مشاعرك وتسمّيها ثم تتخذ مسافة منها وتتحرك وفق قيمك، بدل كبتها أو الغرق فيها.",
         "النمط 5 ينفصل عن مشاعره ويعالجها لاحقاً بعزلة؛ ديفيد تعلّمك المعالجة في اللحظة بدون انسحاب. أداتها 'أنا ألاحظ أنني أشعر…' تناسب عقلك التحليلي وتكسر الانسحاب تحت الضغط.",
         "Courage is not an absence of fear; courage is fear walking."),
        ("The Five Dysfunctions of a Team", "Patrick Lencioni",
         "https://www.goodreads.com/book/show/21343.The_Five_Dysfunctions_of_a_Team", 4.09, 229,
         "رواية إدارية قصيرة تشرح هرم الخلل في الفرق: غياب الثقة → الخوف من الصراع → غياب الالتزام → تجنب المساءلة → إهمال النتائج.",
         "SC يتجنب الصراع ويؤثر الانسجام الظاهري؛ الكتاب يُظهر أن الصراع الصحي حول الأفكار هو أساس الثقة. صيغته القصصية تجعل ديناميكيات الفريق ملموسة لمن يميل للتجريد.",
         "Trust is knowing that when a team member does push you, they're doing it because they care about the team."),
        ("Radical Candor", "Kim Scott",
         "https://www.goodreads.com/book/show/29939161-radical-candor", 4.05, 272,
         "إطار القيادة على محورين: اهتم شخصياً + تحدَّ مباشرة. يشرح لماذا 'التعاطف المدمّر' (تجنب الملاحظات الصعبة حفاظاً على المشاعر) يضر الفريق أكثر من الصراحة.",
         "مصمم لمن يجد صعوبة في إعطاء أو تلقي النقد: يعيد تأطير الملاحظات كفعل رعاية لا هجوم — ما يخفف حساسيتك للنقد ويكسر ميل SC لتجنب المواجهة.",
         "Radical Candor really just means saying what you think while also giving a damn about the person you're saying it to."),
        ("Thanks for the Feedback", "Douglas Stone & Sheila Heen",
         "https://www.goodreads.com/book/show/18114120-thanks-for-the-feedback", 4.05, 348,
         "من فريق مشروع هارفارد للتفاوض: علم تلقي النقد. يفكك 3 محفزات ترفض بها الملاحظات (الحقيقة، العلاقة، الهوية) وكيف تستخرج القيمة حتى من النقد السيء.",
         "الكتاب الوحيد المخصص لتلقي النقد لا إعطائه — وهو نقطة ضعفك الحرجة. تحليلي ومنهجي بما يرضي C، ويعطيك بروتوكولاً واضحاً للحظة سماع النقد بدل الانسحاب.",
         "Receiving feedback well is a process of sorting and filtering—of learning how the other person sees things; of trying on ideas that at first seem a poor fit."),
    ],
    "4- التطبيق والإنجاز": [
        ("Atomic Habits", "James Clear",
         "https://www.goodreads.com/book/show/40121378-atomic-habits", 4.35, 320,
         "نظام العادات المكوّن من 4 قوانين: اجعلها واضحة، جذابة، سهلة، ومُرضية. يركز على الأنظمة لا الأهداف وعلى تحسين 1% يومياً.",
         "يستبدل 'الدافع' غير المضمون بـ'التصميم' المنهجي — لغة يفهمها SC. قاعدة الدقيقتين تكسر الكمالية: ابدأ بنسخة صغيرة ورديئة بدل انتظار الظروف المثالية.",
         "You do not rise to the level of your goals. You fall to the level of your systems."),
        ("Tiny Habits", "BJ Fogg",
         "https://www.goodreads.com/book/show/43261127-tiny-habits", 4.13, 296,
         "عالم سلوك من ستانفورد يقدم نموذج B=MAP (السلوك = دافع × قدرة × محفز) ووصفة: اجعل السلوك صغيراً جداً، اربطه بعادة موجودة، واحتفل فوراً.",
         "يعتمد على بحث أكاديمي حقيقي (يرضي المحقق) لكنه يصر على أن التغيير يبدأ بأصغر خطوة ممكنة اليوم لا بعد اكتمال الفهم. الاحتفال الفوري يعالج ندرة المكافآت العاطفية في يومك.",
         "Simplicity changes behavior."),
        ("The Knowing-Doing Gap", "Jeffrey Pfeffer & Robert Sutton",
         "https://www.goodreads.com/book/show/139851.The_Knowing_Doing_Gap", 3.96, 314,
         "بحث من ستانفورد عن سبب فشل المؤسسات والأفراد في تطبيق ما يعرفونه: الكلام يحل محل الفعل، الخوف يمنع التجربة، والقياس الخاطئ يعاقب المحاولة.",
         "عنوانه هو تشخيصك الحرفي: 'تراكم معرفة بلا تطبيق'. يشرح لماذا التخطيط والنقاش يخلقان وهم الإنجاز، ولماذا 'الفعل ثم التعلم' يتفوق على 'التعلم ثم الفعل'.",
         "Knowing what to do is not enough. Knowledge is only useful when it is put into action."),
        ("The 12 Week Year", "Brian Moran & Michael Lennington",
         "https://www.goodreads.com/book/show/10009377-the-12-week-year", 3.85, 208,
         "تعامل مع كل 12 أسبوعاً كسنة كاملة: أهداف قليلة، خطة أسبوعية مكتوبة، قياس تنفيذ أسبوعي (هدفك ≥85%)، ومراجعة صادقة كل أسبوع.",
         "يعطي SC البنية والإيقاع الذي يحتاجه، ويمنع الكمالية من تأجيل التنفيذ لأن المهلة قصيرة والنجاح يُقاس بالتنفيذ لا بكمال النتيجة. نظام تشغيل جاهز لخطة التطبيق التي ستُبنى على هذه القائمة.",
         "Clarity creates freedom."),
        ("Ultralearning", "Scott H. Young",
         "https://www.goodreads.com/book/show/43245576-ultralearning", 3.95, 304,
         "9 مبادئ للتعلم الذاتي المكثف، أهمها: المباشرة (تعلّم بالممارسة الفعلية)، الاسترجاع، التغذية الراجعة، والتجريب. أمثلة من متعلمين أنجزوا منهج MIT في سنة.",
         "يوجّه شغفك بالمعرفة إلى قنوات تطبيقية: مبدأ 'المباشرة' يحرّم التعلم المعزول عن التطبيق، ومبدأ 'التغذية الراجعة' يدربك على طلب النقد كوقود للإتقان لا كتهديد.",
         "The best way to learn something is to do the thing you want to be good at."),
    ],
}

PODCASTS = [
    # (الفئة, الاسم, المقدم, الرابط, لماذا, حلقة/نقطة بداية مقترحة)
    ("1- فهم طريقة التفكير", "Hidden Brain", "Shankar Vedantam (NPR)", "https://hiddenbrain.org/",
     "علم السلوك والانحيازات بصيغة قصصية موثقة — عمق علمي بلا جفاف.", "ابدأ بحلقات 'You 2.0'"),
    ("1- فهم طريقة التفكير", "You Are Not So Smart", "David McRaney", "https://youarenotsosmart.com/podcasts/",
     "بودكاست مخصص للانحيازات المعرفية والتفكير النقدي مع مقابلات باحثين.", "حلقات 'How Minds Change'"),
    ("1- فهم طريقة التفكير", "The Knowledge Project", "Shane Parrish (Farnam Street)", "https://fs.blog/knowledge-project-podcast/",
     "نماذج ذهنية وقرارات واتخاذ قرار تحت عدم اليقين — المفضل لدى النمط 5 التحليلي.", "حلقة Annie Duke / Daniel Kahneman"),
    ("2- كسر دوامة التحليل", "Deep Questions", "Cal Newport", "https://www.thedeeplife.com/listen/",
     "أستاذ حاسوب يجيب أسئلة المستمعين عن العمل العميق والإنتاجية بمنهج بلا ضجيج تحفيزي.", "حلقات عن 'productivity dragon'"),
    ("2- كسر دوامة التحليل", "The Happiness Lab", "Dr. Laurie Santos (Yale)", "https://www.pushkin.fm/podcasts/the-happiness-lab-with-dr-laurie-santos",
     "علم النفس الإيجابي بالأدلة: الكمالية، المقارنة، وشلل الخيارات.", "حلقة 'The Perfectionism Trap'"),
    ("2- كسر دوامة التحليل", "The Tim Ferriss Show", "Tim Ferriss", "https://tim.blog/podcast/",
     "مقابلات طويلة تفكك أنظمة القرار عند أفضل المنفذين (Fear-Setting بديل للتحليل اللانهائي).", "حلقة Fear-Setting + Annie Duke"),
    ("3- القيادة والذكاء العاطفي", "WorkLife with Adam Grant", "Adam Grant (TED)", "https://www.ted.com/podcasts/worklife",
     "علم النفس التنظيمي: النقد، الثقة، الفرق، وإعادة التفكير — من مؤلف Think Again.", "حلقة 'How to love criticism'"),
    ("3- القيادة والذكاء العاطفي", "Coaching for Leaders", "Dave Stachowiak", "https://coachingforleaders.com/",
     "حلقات أسبوعية عملية ومنظمة عن مهارات القيادة والملاحظات وإدارة الفرق — أسلوب هادئ يناسب SC.", "حلقات Radical Candor / feedback"),
    ("3- القيادة والذكاء العاطفي", "Dare to Lead", "Brené Brown", "https://brenebrown.com/podcast-show/dare-to-lead/",
     "الشجاعة والضعف كأدوات قيادة؛ يعالج جذر الحساسية للنقد.", "حلقة 'Armored vs Daring Leadership'"),
    ("4- التطبيق والإنجاز", "Huberman Lab", "Dr. Andrew Huberman (Stanford)", "https://www.hubermanlab.com/podcast",
     "بروتوكولات علمية للتركيز والدافعية وتكوين العادات — دليل مفصّل يرضي المحقق ويدفعه للتطبيق.", "حلقة 'The Science of Making & Breaking Habits'"),
    ("4- التطبيق والإنجاز", "The 3 Books / Atomic Habits talks", "James Clear (ضيف دائم)", "https://jamesclear.com/articles",
     "خلاصات قصيرة قابلة للتطبيق (نشرة 3-2-1 الأسبوعية + المقالات المسموعة).", "نشرة 3-2-1 Thursday"),
    ("4- التطبيق والإنجاز", "فنجان (عربي)", "عبدالرحمن أبومالح — ثمانية", "https://thmanyah.com/podcasts/fnjan",
     "حوارات عربية طويلة مع منجزين ومفكرين — يمنحك نماذج تطبيق محلية بلغتك.", "حلقات عن الإنتاجية والقرار"),
]

SUMMARIES = [
    # (النوع, الاسم, الرابط, ما يقدمه, لماذا يناسبك)
    ("ملخصات كتب (يوتيوب)", "Productivity Game", "https://www.youtube.com/@ProductivityGame",
     "ملخصات مرئية 8–10 دقائق لكتب الإنتاجية والقرار (Atomic Habits، Decisive، Essentialism).", "مركّز وبلا حشو — يناسب من يريد الفكرة الأساسية ثم التطبيق."),
    ("ملخصات كتب (يوتيوب)", "Ali Abdaal", "https://www.youtube.com/@aliabdaal",
     "طبيب سابق يشرح كتب الإنتاجية والتعلم مع تطبيقه الشخصي لها.", "نموذج لمهني تحليلي حوّل القراءة إلى أنظمة."),
    ("ملخصات كتب (منصة)", "Shortform", "https://www.shortform.com/",
     "ملخصات مطوّلة مع نقد وربط بين الكتب.", "أعمق من Blinkist — يرضي المحقق دون قراءة 400 صفحة."),
    ("ملخصات كتب (منصة)", "Blinkist", "https://www.blinkist.com/",
     "ملخصات 15 دقيقة نصية ومسموعة لأغلب الكتب في هذه القائمة.", "لفرز الكتب قبل الالتزام بقراءتها كاملة."),
    ("ملخصات كتب (عربي)", "أخضر", "https://www.youtube.com/@Akhdar",
     "ملخصات عربية مرئية ومسموعة لأشهر كتب التطوير والتفكير.", "تسريع الاستيعاب بلغتك ومشاركتها مع فريقك."),
    ("ملخصات كتب (نشرة)", "Farnam Street (fs.blog)", "https://fs.blog/",
     "مقالات ونماذج ذهنية وملخصات كتب في التفكير والقرار.", "المرجع الأول لنماذج التفكير عند النمط 5."),
    ("مدربون/متعلمون", "Scott H. Young", "https://www.scotthyoung.com/blog/",
     "مؤلف Ultralearning — مقالات ودورات عن التعلم بالممارسة.", "يحوّل هوس التعلم إلى مشاريع تطبيق محددة المدة."),
    ("مدربون/متعلمون", "Cal Newport", "https://calnewport.com/",
     "العمل العميق والحياة العميقة — كتب، مدونة، بودكاست.", "بروفيسور تحليلي مثلك يحمي التركيز ويحد من التراكم."),
    ("مدربون/متعلمون", "Brené Brown", "https://brenebrown.com/",
     "أبحاث الضعف والشجاعة والقيادة الجريئة.", "الجسر الأنسب للذكاء العاطفي لمن يخشى المشاعر."),
    ("مدربون/متعلمون", "James Clear", "https://jamesclear.com/",
     "نشرة 3-2-1 الأسبوعية وأدلة العادات.", "أقصر مسافة من المعرفة إلى العادة."),
    ("متطورون (مجتمعات)", "Enneagram Institute — Type 5", "https://www.enneagraminstitute.com/type-5/",
     "الوصف الرسمي للنمط 5 مع مستويات التطور وتوصيات النمو.", "قائمة 'توصيات النمو الشخصي' فيه تكمّل هذه القائمة."),
    ("متطورون (مجتمعات)", "Farnam Street Learning Community", "https://fs.blog/membership/",
     "مجتمع نقاش كتب ونماذج ذهنية.", "بيئة آمنة للتعلم مع غيرك دون ضغط اجتماعي مرتفع."),
]

PLAN = [
    ("الأسبوع 1–2", "Finish (208ص)", "الأقصر — ابدأ به لتكسب 'انتصار إنهاء' سريع.", "قاعدة: طبّق فكرة واحدة (اقطع هدفك للنصف) قبل فتح كتاب آخر."),
    ("الأسبوع 3–5", "Tiny Habits", "ثبّت عادة قراءة 20 دقيقة + عادة تطبيق واحدة.", "لا تنتقل للكتاب التالي قبل 7 أيام متتالية من العادة."),
    ("الأسبوع 6–8", "Decisive", "طبّق WRAP على قرار مهني حقيقي واحد.", "اكتب القرار والنتيجة في الشيت."),
    ("الأسبوع 9–11", "Thanks for the Feedback", "اطلب ملاحظة واحدة أسبوعياً من زميل.", "سجّل رد فعلك وما تعلمت."),
    ("الأسبوع 12", "مراجعة 12 Week Year", "قيّم نسبة التنفيذ (الهدف ≥85%).", "اختر الدورة التالية من التبويبات 1 و3."),
    ("قاعدة عامة", "1 كتاب معرفة : 1 كتاب تطبيق", "لكل كتاب 'فهم' يجب أن يقابله كتاب 'تنفيذ'.", "مضاد مباشر لتراكم المعرفة بلا تطبيق."),
]


def style_sheet(ws, widths):
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.sheet_view.rightToLeft = True


def write_csv(path: Path, headers, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def main(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)

    for cat, books in BOOKS.items():
        ws = wb.create_sheet(cat[:31])
        ws.append(HEADERS)
        rows = [[cat, *b] for b in books]
        for r in rows:
            ws.append(r)
        style_sheet(ws, [18, 30, 22, 40, 9, 9, 55, 60, 50])
        write_csv(out_dir / f"tab{cat[0]}.csv", HEADERS, rows)

    ph = ["الفئة", "اسم البودكاست", "المقدم", "الرابط المباشر", "لماذا يناسبك", "نقطة بداية مقترحة"]
    ws = wb.create_sheet("5- البودكاست والمحتوى")
    ws.append(ph)
    for p in PODCASTS:
        ws.append(list(p))
    style_sheet(ws, [22, 28, 26, 45, 55, 32])
    write_csv(out_dir / "tab5-podcasts.csv", ph, [list(p) for p in PODCASTS])

    sh = ["النوع", "الاسم", "الرابط", "ما يقدمه", "لماذا يناسبك"]
    ws = wb.create_sheet("6- ملخصات ومدربون ومجتمعات")
    ws.append(sh)
    for s in SUMMARIES:
        ws.append(list(s))
    style_sheet(ws, [22, 30, 45, 55, 50])
    write_csv(out_dir / "tab6-summaries.csv", sh, [list(s) for s in SUMMARIES])

    plh = ["المرحلة", "المادة", "الهدف", "قاعدة الحماية من التراكم"]
    ws = wb.create_sheet("7- مسار قراءة مقترح")
    ws.append(plh)
    for p in PLAN:
        ws.append(list(p))
    style_sheet(ws, [16, 30, 50, 55])

    # Profile tab
    ws = wb.create_sheet("0- ملف الشخصية", 0)
    ws.sheet_view.rightToLeft = True
    for r in [
        ["DISC", "SC (Steadiness + Conscientiousness)"],
        ["Enneagram", "النمط 5 — المحقق"],
        ["نقاط الضعف الحرجة", "كمالية تعطّل الإنجاز · تراكم معرفة بلا تطبيق · حساسية للنقد · صعوبة الذكاء العاطفي · انسحاب تحت الضغط"],
        ["مصدر التقييمات", "Goodreads (متوسط المجتمع وقت البحث، سبتمبر 2026) — قد يتغير بفارق ±0.05"],
        ["عدد الصفحات", "الطبعة الإنجليزية الأكثر شيوعاً على Goodreads"],
    ]:
        ws.append(r)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 110
    for row in ws.iter_rows():
        row[0].font = Font(bold=True)
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)

    out = out_dir / "enneagram5-sc-growth-library.xlsx"
    wb.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("research_capsules/reading-list"))
