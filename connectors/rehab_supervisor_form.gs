/** Rehabilitation supervisor form and dashboard integration — v1.1. */
const REHAB_DASHBOARD_SPREADSHEET_ID = '1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc';
const REHAB_EXECUTIVE_BRIEF_SHEET = 'Executive_Brief';
const REHAB_REPORT_LOG_SHEET = 'تقارير المشرفين';
const REHAB_AGENT_INPUT_SHEET = 'مدخلات الوكيل';

function createRehabSupervisorForm(forceCreate) {
  const props = PropertiesService.getScriptProperties();
  const oldId = props.getProperty('REHAB_FORM_ID');
  if (oldId && forceCreate !== true) return rehabFormLinks_();

  const title = 'تقارير المشرفين الأسبوعية | قسم التأهيل';
  const form = FormApp.create(title)
    .setDescription('يُرسل مرة في نهاية الأسبوع. استخدم البلاغ الطارئ فورًا. لا تدخل اسم المريض أو رقم ملفه أو أي بيانات صحية شخصية.')
    .setConfirmationMessage('تم استلام التقرير بنجاح. شكرًا لك.')
    .setProgressBar(true).setCollectEmail(false).setAllowResponseEdits(true);
  const responses = SpreadsheetApp.create(title + ' — الردود');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, responses.getId());

  form.addSectionHeaderItem().setTitle('المعلومات الأساسية');
  form.addListItem().setTitle('اسم المشرف').setChoiceValues(['عبدالمجيد','شهد','سمية','مشرف آخر']).setRequired(true);
  form.addTextItem().setTitle('اسم المشرف الآخر');
  form.addDateItem().setTitle('تاريخ إرسال التقرير').setRequired(true);
  form.addDateItem().setTitle('بداية الأسبوع').setRequired(true);
  form.addDateItem().setTitle('نهاية الأسبوع').setRequired(true);
  form.addListItem().setTitle('القسم / العيادة').setChoiceValues([
    'العلاج الطبيعي','العلاج الوظيفي','علاج النطق','عيادة الدوخة والدهليزي',
    'عيادة القدم والنعل','القسم العام'
  ]).setRequired(true);

  const reportType = form.addMultipleChoiceItem().setTitle('نوع التقرير').setRequired(true);
  const weekly = form.addPageBreakItem().setTitle('التقرير الأسبوعي');
  form.addMultipleChoiceItem().setTitle('الجاهزية العامة للقسم خلال الأسبوع')
    .setChoiceValues(['🟢 جاهز بالكامل','🟡 جاهز جزئيًا — توجد ملاحظة','🔴 غير جاهز — يحتاج تدخل']).setRequired(true);
  form.addParagraphTextItem().setTitle('ملاحظة الجاهزية أو التدخل المطلوب');
  rehabNumber_(form, 'متوسط عدد الموظفين الحاضرين يوميًا');
  form.addMultipleChoiceItem().setTitle('هل وُجد غياب خلال الأسبوع؟')
    .setChoiceValues(['لا يوجد غياب ✅','نعم — يوجد غياب ⚠️']).setRequired(true);
  form.addParagraphTextItem().setTitle('تفاصيل الغياب');
  form.addCheckboxItem().setTitle('حالة الأجهزة والمعدات خلال الأسبوع').setChoiceValues([
    'جميع الأجهزة تعمل','جهاز معطل — تم أو سيتم الإبلاغ','نقص في المستلزمات',
    'مشكلة في النظافة / الترتيب','ملاحظة أخرى'
  ]).setRequired(true);
  form.addParagraphTextItem().setTitle('تفاصيل الجهاز أو المستلزمات أو النظافة');
  rehabNumber_(form, 'إجمالي المرضى المجدولين خلال الأسبوع');
  rehabNumber_(form, 'إجمالي المرضى الذين تمت خدمتهم خلال الأسبوع');
  rehabNumber_(form, 'عدد الإلغاءات / عدم الحضور');
  form.addParagraphTextItem().setTitle('أبرز الإنجازات والمعلومات المهمة هذا الأسبوع')
    .setHelpText('اذكر نمطًا متكررًا أو فرصة تحسين أو خطرًا ناشئًا أو معلومة تحتاج متابعة.');
  form.addParagraphTextItem().setTitle('التعثرات والإجراءات')
    .setHelpText('لكل تعثر: السبب + خيارا حل + توصية المشرف + هل يحتاج قرار رئيس القسم؟');
  form.addParagraphTextItem().setTitle('الأعمال والمتابعة للأسبوع القادم')
    .setHelpText('المهمة + المسؤول + تاريخ المتابعة.');
  form.addMultipleChoiceItem().setTitle('هل يوجد قرار مطلوب من رئيس القسم؟')
    .setChoiceValues(['لا','نعم — عادي','نعم — عاجل']).setRequired(true);
  form.addParagraphTextItem().setTitle('القرار المطلوب والتوصية');
  form.addScaleItem().setTitle('تقييم الأسبوع العام').setBounds(1,5)
    .setLabels('1 — يحتاج تدخل','5 — ممتاز').setRequired(true);

  const emergency = form.addPageBreakItem().setTitle('بلاغ طارئ');
  form.addMultipleChoiceItem().setTitle('درجة الأولوية')
    .setChoiceValues(['عاجل — تأثير فوري','مرتفع — خلال اليوم','متوسط — خلال 48 ساعة']).setRequired(true);
  form.addCheckboxItem().setTitle('نوع البلاغ').setChoiceValues([
    'سلامة مريض أو موظف','تعطل جهاز أساسي','نقص حرج في الكادر',
    'نقص حرج في المستلزمات','مشكلة تشغيلية','أخرى'
  ]).setRequired(true);
  form.addParagraphTextItem().setTitle('وصف البلاغ دون بيانات مرضى شخصية').setRequired(true);
  form.addParagraphTextItem().setTitle('الإجراء الفوري الذي تم اتخاذه').setRequired(true);
  form.addParagraphTextItem().setTitle('الدعم أو القرار المطلوب').setRequired(true);
  reportType.setChoices([
    reportType.createChoice('📅 التقرير الأسبوعي', weekly),
    reportType.createChoice('🚨 بلاغ طارئ', emergency)
  ]);
  weekly.setGoToPage(FormApp.PageNavigationType.SUBMIT);
  emergency.setGoToPage(FormApp.PageNavigationType.SUBMIT);

  props.setProperties({REHAB_FORM_ID:form.getId(),REHAB_RESPONSE_SHEET_ID:responses.getId()});
  ensureRehabDashboard_();
  createRehabFormSubmitTrigger();
  return rehabFormLinks_();
}

function rehabNumber_(form, title) {
  return form.addTextItem().setTitle(title).setValidation(
    FormApp.createTextValidation().requireNumberGreaterThanOrEqualTo(0).build()
  ).setRequired(true);
}

function onRehabSupervisorFormSubmit(e) {
  if (!e || !e.response) throw new Error('تعمل هذه الدالة عند إرسال النموذج فقط.');
  const a = {};
  e.response.getItemResponses().forEach(r => a[r.getItem().getTitle()] = r.getResponse());
  const selected = rehabValue_(a['اسم المشرف']);
  const supervisor = selected === 'مشرف آخر' ? rehabValue_(a['اسم المشرف الآخر']) || selected : selected;
  const reportType = rehabValue_(a['نوع التقرير']);
  const emergency = reportType.indexOf('بلاغ طارئ') >= 0;
  const data = {
    submittedAt:e.response.getTimestamp() || new Date(), reportType:reportType,
    supervisor:supervisor, clinic:rehabValue_(a['القسم / العيادة']),
    weekStart:rehabValue_(a['بداية الأسبوع']), weekEnd:rehabValue_(a['نهاية الأسبوع']),
    readiness:rehabValue_(a['الجاهزية العامة للقسم خلال الأسبوع']),
    scheduled:rehabNumberValue_(a['إجمالي المرضى المجدولين خلال الأسبوع']),
    patients:rehabNumberValue_(a['إجمالي المرضى الذين تمت خدمتهم خلال الأسبوع']),
    noShows:rehabNumberValue_(a['عدد الإلغاءات / عدم الحضور']),
    achievements:rehabValue_(a['أبرز الإنجازات والمعلومات المهمة هذا الأسبوع']),
    blockers:rehabValue_(a['التعثرات والإجراءات']),
    next:rehabValue_(a['الأعمال والمتابعة للأسبوع القادم']),
    decisionLevel:rehabValue_(a['هل يوجد قرار مطلوب من رئيس القسم؟']),
    decision:rehabValue_(a['القرار المطلوب والتوصية']) || rehabValue_(a['الدعم أو القرار المطلوب']),
    priority:rehabValue_(a['درجة الأولوية']), emergency:emergency
  };
  data.brief = rehabBrief_(a, data);
  writeRehabReport_(data);
}

function rehabBrief_(a, d) {
  const lines=[d.emergency?'🚨 بلاغ مشرف طارئ':'📋 تقرير المشرف الأسبوعي',
    '👤 المشرف: '+(d.supervisor||'غير محدد'),'🏥 القسم: '+(d.clinic||'غير محدد'),
    '📅 الإرسال: '+rehabDate_(d.submittedAt)];
  if (d.emergency) lines.push('⚠️ الأولوية: '+d.priority,'🏷️ النوع: '+rehabValue_(a['نوع البلاغ']),
    '📝 الوصف: '+rehabValue_(a['وصف البلاغ دون بيانات مرضى شخصية']),
    '🛠️ الإجراء الفوري: '+rehabValue_(a['الإجراء الفوري الذي تم اتخاذه']),
    '⚖️ الدعم/القرار: '+d.decision);
  else lines.push('🗓️ الفترة: '+d.weekStart+' — '+d.weekEnd,'✅ الجاهزية: '+d.readiness,
    '🩺 المرضى: '+d.patients+' من '+d.scheduled,'↩️ الإلغاء/عدم الحضور: '+d.noShows,
    '✨ معلومات مهمة: '+d.achievements,'⛔ التعثرات: '+d.blockers,
    '🧭 الأسبوع القادم: '+d.next,'⚖️ مستوى القرار: '+(d.decisionLevel||'لا'),'💡 القرار والتوصية: '+d.decision);
  return lines.join('\n');
}

function ensureRehabDashboard_() {
  const book=SpreadsheetApp.openById(REHAB_DASHBOARD_SPREADSHEET_ID);
  rehabEnsureSheet_(book,REHAB_EXECUTIVE_BRIEF_SHEET,['البند','القيمة']);
  rehabEnsureSheet_(book,REHAB_REPORT_LOG_SHEET,['وقت الإرسال','نوع التقرير','المشرف','القسم / العيادة','بداية الأسبوع','نهاية الأسبوع','الجاهزية','المجدولون','تمت خدمتهم','إلغاء / عدم حضور','المعلومات المهمة','التعثرات','مستوى القرار','القرار والتوصية','أولوية البلاغ','الملخص']);
  rehabEnsureSheet_(book,REHAB_AGENT_INPUT_SHEET,['Intake ID','Timestamp','Source','Submitted By','Type','Brief','Language','Classification','Visibility','Status','Project ID','Task ID','Agenda ID','Financial ID','Notes']);
  return book;
}

function rehabEnsureSheet_(book,name,headers) {
  let sheet=book.getSheetByName(name);
  if (!sheet) sheet=book.insertSheet(name);
  if (sheet.getLastRow()===0) {
    sheet.getRange(1,1,1,headers.length).setValues([headers]).setFontWeight('bold').setBackground('#1F4E78').setFontColor('#FFFFFF');
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function writeRehabReport_(d) {
  const book=ensureRehabDashboard_();
  book.getSheetByName(REHAB_REPORT_LOG_SHEET).appendRow([
    d.submittedAt,d.reportType,d.supervisor,d.clinic,d.weekStart,d.weekEnd,d.readiness,
    d.scheduled,d.patients,d.noShows,d.achievements,d.blockers,d.decisionLevel,d.decision,d.priority,d.brief
  ]);
  const brief=book.getSheetByName(REHAB_EXECUTIVE_BRIEF_SHEET);
  rehabMetric_(brief,'آخر تقرير مشرف',rehabDate_(d.submittedAt)+' — '+d.supervisor);
  rehabMetric_(brief,'ملخص تقرير المشرف',d.brief.slice(0,5000));
  rehabMetric_(brief,d.emergency?'آخر بلاغ مشرف طارئ':'مرضى التأهيل هذا الأسبوع',d.emergency?d.priority+' — '+d.supervisor:d.patients);
  if (!d.emergency) {
    rehabMetric_(brief,'الإلغاء / عدم الحضور هذا الأسبوع',d.noShows);
    rehabMetric_(brief,'قرار مطلوب من تقرير المشرف',d.decisionLevel||'لا');
  }
  const classification=d.emergency||String(d.decisionLevel).indexOf('عاجل')>=0?'DECISION_REQUIRED':'WEEKLY_REPORT';
  book.getSheetByName(REHAB_AGENT_INPUT_SHEET).appendRow([
    'FORM-'+Utilities.getUuid().replace(/-/g,'').slice(0,10).toUpperCase(),new Date().toISOString(),
    'GOOGLE_FORM',d.supervisor,d.emergency?'EMERGENCY_SUPERVISOR_REPORT':'WEEKLY_SUPERVISOR_REPORT',
    d.brief,'ar',classification,'INTERNAL','NEW','','','','','مصدر تلقائي: نموذج تقارير مشرفي قسم التأهيل'
  ]);
}

function rehabMetric_(sheet,label,value) {
  const last=Math.max(sheet.getLastRow(),1);
  const labels=sheet.getRange(1,1,last,1).getDisplayValues().flat();
  const found=labels.indexOf(label)+1;
  const row=found||last+1;
  sheet.getRange(row,1,1,2).setValues([[label,value]]);
}

function createRehabFormSubmitTrigger() {
  const id=PropertiesService.getScriptProperties().getProperty('REHAB_FORM_ID');
  if (!id) throw new Error('شغّل createRehabSupervisorForm أولًا.');
  ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()==='onRehabSupervisorFormSubmit').forEach(t=>ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('onRehabSupervisorFormSubmit').forForm(FormApp.openById(id)).onFormSubmit().create();
}

function testRehabIntegration() {
  const book=ensureRehabDashboard_();
  const id=PropertiesService.getScriptProperties().getProperty('REHAB_FORM_ID');
  if (!id) throw new Error('REHAB_FORM_ID غير محفوظ. شغّل createRehabSupervisorForm أولًا.');
  FormApp.openById(id);
  const trigger=ScriptApp.getProjectTriggers().some(t=>t.getHandlerFunction()==='onRehabSupervisorFormSubmit');
  if (!trigger) throw new Error('مشغل النموذج غير موجود.');
  return {ok:true,formId:id,dashboardId:book.getId(),trigger:true};
}

function rehabFormLinks_() {
  const props=PropertiesService.getScriptProperties();
  const form=FormApp.openById(props.getProperty('REHAB_FORM_ID'));
  const responseId=props.getProperty('REHAB_RESPONSE_SHEET_ID');
  return {formUrl:form.getPublishedUrl(),editUrl:form.getEditUrl(),spreadsheetUrl:responseId?SpreadsheetApp.openById(responseId).getUrl():''};
}

function showRehabFormLinks() { const links=rehabFormLinks_(); Logger.log(JSON.stringify(links)); return links; }
function rehabValue_(v) { if(Array.isArray(v)) return v.join('، '); if(v instanceof Date) return rehabDate_(v); return v==null?'':String(v).trim(); }
function rehabNumberValue_(v) { const n=Number(v); return isNaN(n)?0:n; }
function rehabDate_(v) { const d=v instanceof Date?v:new Date(v); return isNaN(d.getTime())?rehabValue_(v):Utilities.formatDate(d,'Asia/Riyadh','yyyy-MM-dd HH:mm'); }
