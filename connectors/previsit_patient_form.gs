/** Phase 1.5 — Pre-Visit Intelligent Engine (clinician-reviewed, de-identified). */
const PREVISIT_TIMEZONE = 'Asia/Riyadh';
const PREVISIT_FORM_TITLE = 'استبيان ما قبل زيارة العلاج الطبيعي';
const PREVISIT_REVIEW_SHEET = 'PreVisit_Clinician_Review';

function createPreVisitPatientForm(forceCreate) {
  const props=PropertiesService.getScriptProperties();
  const existing=props.getProperty('PREVISIT_FORM_ID');
  if (existing && forceCreate!==true) return preVisitLinks_();

  const form=FormApp.create(PREVISIT_FORM_TITLE)
    .setDescription(
      'يساعد هذا الاستبيان المعالج على التحضير للزيارة، ولا يشخّص الحالة ولا يستبدل التقييم السريري أو خدمات الطوارئ.\n'+
      'استخدم رمز الحالة الذي زودتك به العيادة. لا تكتب اسمك أو رقم هويتك أو رقم ملفك أو بيانات اتصالك.\n'+
      'إذا كانت لديك أعراض شديدة أو مفاجئة أو حالة طارئة، استخدم خدمات الطوارئ المعتمدة ولا تنتظر الرد على النموذج.'
    ).setConfirmationMessage('تم استلام الإجابات للمراجعة بواسطة المعالج. لا تعتمد على النموذج في الحالات الطارئة.')
    .setCollectEmail(false).setProgressBar(true).setAllowResponseEdits(false);
  const responseBook=SpreadsheetApp.create(PREVISIT_FORM_TITLE+' — بيانات سريرية مقيدة');
  form.setDestination(FormApp.DestinationType.SPREADSHEET,responseBook.getId());

  form.addSectionHeaderItem().setTitle('الموافقة والخصوصية');
  form.addCheckboxItem().setTitle('الموافقة').setChoiceValues([
    'أفهم أن هذا فرز أولي وليس تشخيصًا أو بديلًا عن الطوارئ، وأوافق على استخدام إجاباتي للتحضير للزيارة.'
  ]).setRequired(true);
  form.addTextItem().setTitle('رمز الحالة').setHelpText('مثال: PV-2026-001. لا تكتب اسمك أو رقم ملفك.').setRequired(true);
  form.addDateItem().setTitle('تاريخ الموعد المتوقع');
  form.addTextItem().setTitle('العمر بالسنوات').setValidation(
    FormApp.createTextValidation().requireNumberBetween(5,120).build()
  ).setRequired(true);

  const pathway=form.addMultipleChoiceItem().setTitle('المسار المبدئي الذي حددته العيادة').setRequired(true);
  const general=form.addPageBreakItem().setTitle('الأعراض والوظيفة');
  form.addParagraphTextItem().setTitle('بداية المشكلة وتطورها').setRequired(true);
  form.addScaleItem().setTitle('شدة الأعراض الآن').setBounds(0,10).setLabels('0','10').setRequired(true);
  form.addScaleItem().setTitle('أسوأ شدة للأعراض').setBounds(0,10).setLabels('0','10').setRequired(true);
  form.addParagraphTextItem().setTitle('ما الذي يزيد الأعراض وما الذي يخففها؟').setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل توقظك الأعراض من النوم؟').setChoiceValues(['لا','نعم']).setRequired(true);
  form.addTextItem().setTitle('كم تستمر زيادة الأعراض بعد النشاط بالدقائق؟').setValidation(
    FormApp.createTextValidation().requireNumberGreaterThanOrEqualTo(0).build()
  );
  form.addParagraphTextItem().setTitle('النشاط الأهم الذي تريد استعادته').setRequired(true);

  const cervical=form.addPageBreakItem().setTitle('أسئلة الرقبة والطرف العلوي');
  form.addParagraphTextItem().setTitle('انتشار الأعراض في الذراع أو الأصابع');
  form.addMultipleChoiceItem().setTitle('هل يوجد تنميل أو وخز؟').setChoiceValues(['لا','نعم']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل يوجد ضعف جديد أو متزايد في الذراع أو اليد؟').setChoiceValues(['لا','نعم']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل تتغير الأعراض مع حركة الرقبة أو السعال أو العطس؟').setChoiceValues(['لا','نعم','غير متأكد']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل يخف العرض عند وضع اليد فوق الرأس؟').setChoiceValues(['لا','نعم','غير متأكد']);

  const lumbar=form.addPageBreakItem().setTitle('أسئلة أسفل الظهر والطرف السفلي');
  form.addParagraphTextItem().setTitle('انتشار الأعراض في الساق أو القدم');
  form.addMultipleChoiceItem().setTitle('هل يوجد خدر أو وخز في الساق أو القدم؟').setChoiceValues(['لا','نعم']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل يوجد ضعف جديد أو متزايد في الساق أو القدم؟').setChoiceValues(['لا','نعم']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل تتغير الأعراض مع السعال أو العطس أو الانحناء؟').setChoiceValues(['لا','نعم','غير متأكد']).setRequired(true);

  const shoulder=form.addPageBreakItem().setTitle('أسئلة الكتف');
  form.addMultipleChoiceItem().setTitle('هل يزيد الألم عند رفع الذراع أو العمل فوق الرأس؟').setChoiceValues(['لا','نعم']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل يمنعك الألم من النوم على الكتف؟').setChoiceValues(['لا','نعم']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل بدأ الضعف بعد إصابة واضحة أو خلع؟').setChoiceValues(['لا','نعم']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('هل يوجد مدى محدد أثناء الرفع يزداد فيه الألم؟').setChoiceValues(['لا','نعم','غير متأكد']);

  const safety=form.addPageBreakItem().setTitle('فحص السلامة — مطلوب للجميع');
  addSafetyYesNo_(form,'ضعف مفاجئ أو متزايد بسرعة أو اضطراب مشي جديد');
  addSafetyYesNo_(form,'تغير جديد في التحكم بالبول أو البراز');
  addSafetyYesNo_(form,'خدر جديد في منطقة العجان');
  addSafetyYesNo_(form,'ألم صدر أو ضيق نفس أو إغماء أو أعراض عصبية مفاجئة');
  addSafetyYesNo_(form,'حرارة مستمرة أو قشعريرة أو عدوى حديثة أو شعور شديد بالمرض');
  addSafetyYesNo_(form,'إصابة كبيرة حديثة أو تاريخ سرطان مع أعراض جديدة غير مفسرة');
  form.addScaleItem().setTitle('الخوف من الحركة').setBounds(0,10).setLabels('0 لا أخشى','10 أخشى جدًا').setRequired(true);
  form.addScaleItem().setTitle('تأثير الحالة في المزاج أو النوم أو العمل').setBounds(0,10).setLabels('0','10').setRequired(true);
  form.addMultipleChoiceItem().setTitle('توقعك للتحسن').setChoiceValues(['منخفض','متوسط','مرتفع','غير متأكد']).setRequired(true);

  pathway.setChoices([
    pathway.createChoice('عضلي هيكلي عام',general),
    pathway.createChoice('رقبة مع أعراض بالطرف العلوي',cervical),
    pathway.createChoice('أسفل الظهر مع أعراض بالطرف السفلي',lumbar),
    pathway.createChoice('كتف / كفة مدورة',shoulder)
  ]);
  general.setGoToPage(safety); cervical.setGoToPage(safety); lumbar.setGoToPage(safety); shoulder.setGoToPage(safety);
  safety.setGoToPage(FormApp.PageNavigationType.SUBMIT);

  const review=responseBook.insertSheet(PREVISIT_REVIEW_SHEET,0);
  const headers=['وقت الإرسال','رمز الحالة','المسار','حالة الفرز','إشارات عاجلة','إشارات مراجعة أولوية','الاستثارة','عوامل صفراء','فجوات المقابلة','حالة رسالة المريض','اعتماد المعالج','ملاحظات المعالج'];
  review.getRange(1,1,1,headers.length).setValues([headers]).setFontWeight('bold').setBackground('#7A1F1F').setFontColor('#FFFFFF');
  review.setFrozenRows(1);
  props.setProperties({PREVISIT_FORM_ID:form.getId(),PREVISIT_RESPONSE_SHEET_ID:responseBook.getId()});
  createPreVisitSubmitTrigger();
  return preVisitLinks_();
}

function addSafetyYesNo_(form,title) {
  return form.addMultipleChoiceItem().setTitle(title).setChoiceValues(['لا','نعم']).setRequired(true);
}

function onPreVisitFormSubmit(e) {
  if(!e||!e.response) throw new Error('تعمل عند إرسال النموذج فقط.');
  const a={}; e.response.getItemResponses().forEach(r=>a[r.getItem().getTitle()]=r.getResponse());
  const urgent=[];
  ['ضعف مفاجئ أو متزايد بسرعة أو اضطراب مشي جديد','تغير جديد في التحكم بالبول أو البراز','خدر جديد في منطقة العجان','ألم صدر أو ضيق نفس أو إغماء أو أعراض عصبية مفاجئة'].forEach(k=>{if(preVisitYes_(a[k])) urgent.push(k);});
  const priority=[];
  ['حرارة مستمرة أو قشعريرة أو عدوى حديثة أو شعور شديد بالمرض','إصابة كبيرة حديثة أو تاريخ سرطان مع أعراض جديدة غير مفسرة'].forEach(k=>{if(preVisitYes_(a[k])) priority.push(k);});
  const pain=Number(a['أسوأ شدة للأعراض']||0), duration=Number(a['كم تستمر زيادة الأعراض بعد النشاط بالدقائق؟']||0);
  const sleep=preVisitYes_(a['هل توقظك الأعراض من النوم؟']);
  const irritability=(pain>=8||duration>=60||sleep)?'HIGH':(pain>=5||duration>=15)?'MEDIUM':'LOW_OR_UNCLEAR';
  const yellow=[];
  if(Number(a['الخوف من الحركة']||0)>=7) yellow.push('HIGH_FEAR_OF_MOVEMENT');
  if(Number(a['تأثير الحالة في المزاج أو النوم أو العمل']||0)>=7) yellow.push('HIGH_PSYCHOSOCIAL_IMPACT');
  const status=urgent.length?'URGENT_CLINICIAN_REVIEW':priority.length?'PRIORITY_CLINICIAN_REVIEW':'ROUTINE_CLINICIAN_REVIEW';
  const book=SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty('PREVISIT_RESPONSE_SHEET_ID'));
  const sheet=book.getSheetByName(PREVISIT_REVIEW_SHEET);
  sheet.appendRow([e.response.getTimestamp(),preVisitValue_(a['رمز الحالة']),preVisitValue_(a['المسار المبدئي الذي حددته العيادة']),status,urgent.join('، '),priority.join('، '),irritability,yellow.join('، '),'يحددها المعالج بعد مراجعة الإجابات','DRAFT_REQUIRES_CLINICIAN_APPROVAL','PENDING','']);
  if(urgent.length) MailApp.sendEmail(Session.getEffectiveUser().getEmail(),'URGENT PRE-VISIT REVIEW — '+preVisitValue_(a['رمز الحالة']),'ظهرت إجابة تحتاج مراجعة عاجلة من المعالج. افتح جدول المراجعة المقيد. لا تعتمد على البريد كتقييم طبي.');
}

function createPreVisitSubmitTrigger() {
  const id=PropertiesService.getScriptProperties().getProperty('PREVISIT_FORM_ID');
  if(!id) throw new Error('شغّل createPreVisitPatientForm أولًا.');
  ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()==='onPreVisitFormSubmit').forEach(t=>ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('onPreVisitFormSubmit').forForm(FormApp.openById(id)).onFormSubmit().create();
}

function testPreVisitIntegration() {
  const props=PropertiesService.getScriptProperties();
  const formId=props.getProperty('PREVISIT_FORM_ID'), sheetId=props.getProperty('PREVISIT_RESPONSE_SHEET_ID');
  if(!formId||!sheetId) throw new Error('شغّل createPreVisitPatientForm أولًا.');
  FormApp.openById(formId); SpreadsheetApp.openById(sheetId).getSheetByName(PREVISIT_REVIEW_SHEET);
  const trigger=ScriptApp.getProjectTriggers().some(t=>t.getHandlerFunction()==='onPreVisitFormSubmit');
  if(!trigger) throw new Error('مشغل Pre-Visit غير موجود.');
  return {ok:true,formId:formId,responseSheetId:sheetId,trigger:true};
}

function preVisitLinks_() {
  const p=PropertiesService.getScriptProperties(), form=FormApp.openById(p.getProperty('PREVISIT_FORM_ID'));
  return {formUrl:form.getPublishedUrl(),editUrl:form.getEditUrl(),responseSheetUrl:SpreadsheetApp.openById(p.getProperty('PREVISIT_RESPONSE_SHEET_ID')).getUrl()};
}
function showPreVisitLinks(){const links=preVisitLinks_();Logger.log(JSON.stringify(links));return links;}
function preVisitYes_(v){return String(v||'').trim()==='نعم';}
function preVisitValue_(v){return v==null?'':String(v).trim();}
