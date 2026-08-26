/**
 * Abdulrahman AI OS secure Google Sheets gateway.
 * Source contract must match connectors/gateway_contract.py.
 */
const SPREADSHEET_ID = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID')
  || '1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc';
const SUPPORTED_ACTIONS = [
  'append','metadata','snapshot','search','upsert_metrics','update','ping'
];

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function stableRowAlreadyExists_(sheet, row) {
  // Durable de-duplication for the two high-value append streams whose first
  // column is already a stable message/conversation identifier.
  const durableTabs = ['مدخلات الوكيل','محادثات الوكيل'];
  if (!durableTabs.includes(sheet.getName()) || !row.length || !row[0]) return false;
  const last = sheet.getLastRow();
  if (last < 1) return false;
  const start = Math.max(1, last - 999);
  const values = sheet.getRange(start, 1, last - start + 1, 1).getDisplayValues().flat();
  return values.includes(String(row[0]));
}

function appendIdempotent_(sheet, row, idempotencyKey) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    if (stableRowAlreadyExists_(sheet, row)) {
      return {ok:true,deduplicated:true,mode:'stable_row_id'};
    }
    const key = String(idempotencyKey || '').slice(0, 120);
    const cache = CacheService.getScriptCache();
    if (key && cache.get('idem:' + key)) {
      return {ok:true,deduplicated:true,mode:'retry_cache'};
    }
    sheet.appendRow(row);
    if (key) cache.put('idem:' + key, '1', 21600);
    return {ok:true,deduplicated:false};
  } finally {
    lock.releaseLock();
  }
}

function doPost(e) {
  try {
    const body = JSON.parse((e.postData && e.postData.contents) || '{}');
    const expected = PropertiesService.getScriptProperties().getProperty('AGENT_SECRET');
    if (!expected || body.secret !== expected) return json_({ok:false,error:'unauthorized'});
    const action = body.action || 'append';
    if (!SUPPORTED_ACTIONS.includes(action)) throw new Error('unsupported action');

    if (action === 'ping') {
      return json_({ok:true,schema:'gateway/2',actions:SUPPORTED_ACTIONS});
    }

    const book = SpreadsheetApp.openById(SPREADSHEET_ID);

    if (action === 'append') {
      const allowed = ['مدخلات الوكيل','محادثات الوكيل','حالة الوكيل',
        'Decision_Log','Telegram_Log','FollowUp_Log','Approval_Log','Agent_Log',
        'تقارير المشرفين','Brief_History','Decisions','Risks_Blockers',
        'Important_Info','Commitments','Knowledge_Log','Audit_Log'];
      if (!allowed.includes(body.tab) || !Array.isArray(body.row)) throw new Error('invalid append');
      const sheet = book.getSheetByName(body.tab);
      if (!sheet) throw new Error('sheet not found');
      return json_(appendIdempotent_(sheet, body.row, body.idempotency_key));
    }

    if (action === 'metadata') {
      const sheets = book.getSheets().map(s => ({
        title:s.getName(), sheetId:s.getSheetId(), rows:s.getMaxRows(), columns:s.getMaxColumns()
      }));
      return json_({ok:true,sheets:sheets});
    }

    if (action === 'snapshot') {
      const maxRows = Math.max(2,Math.min(Number(body.maxRows)||80,150));
      const maxCols = Math.max(2,Math.min(Number(body.maxCols)||16,20));
      const data = {};
      book.getSheets().slice(0,25).forEach(s => {
        const rows = Math.min(Math.max(s.getLastRow(),1),maxRows);
        const cols = Math.min(Math.max(s.getLastColumn(),1),maxCols);
        const values = s.getRange(1,1,rows,cols).getDisplayValues();
        if (values.some(r => r.some(v => v !== ''))) data[s.getName()] = values;
      });
      return json_({ok:true,data:data});
    }

    if (action === 'search') {
      const q = String(body.query||'').trim().toLowerCase();
      if (!q) throw new Error('empty query');
      const limit = Math.max(1,Math.min(Number(body.maxResults)||25,50));
      const results = [];
      book.getSheets().forEach(s => {
        if (results.length >= limit) return;
        const rows = Math.min(Math.max(s.getLastRow(),1),300);
        const cols = Math.min(Math.max(s.getLastColumn(),1),20);
        const values = s.getRange(1,1,rows,cols).getDisplayValues();
        values.forEach((r,i) => {
          if (results.length < limit && r.join(' | ').toLowerCase().includes(q)) {
            results.push({sheet:s.getName(),row:i+1,values:r});
          }
        });
      });
      return json_({ok:true,results:results});
    }

    if (action === 'upsert_metrics') {
      const sheetName = String(body.sheet||'Executive_Brief');
      if (sheetName !== 'Executive_Brief') throw new Error('invalid metrics sheet');
      const metrics = body.metrics;
      if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) {
        throw new Error('invalid metrics');
      }
      const sheet = book.getSheetByName(sheetName);
      if (!sheet) throw new Error('sheet not found');
      const allowedLabels = [
        'آخر تحديث للملخص التنفيذي','ملخص المدير الشخصي',
        'تغييرات جديدة منذ آخر Brief','عناصر أزيلت أو أغلقت',
        'قرارات تحتاج مراجعة','مخاطر وتعثرات مكتشفة',
        'آخر تقرير مشرف','ملخص تقرير المشرف',
        'مرضى التأهيل هذا الأسبوع','الإلغاء / عدم الحضور هذا الأسبوع',
        'قرار مطلوب من تقرير المشرف','آخر بلاغ مشرف طارئ'
      ];
      const last = Math.max(sheet.getLastRow(),1);
      const labels = sheet.getRange(1,1,last,1).getDisplayValues().flat();
      let next = last + 1, updated = 0;
      Object.keys(metrics).slice(0,20).forEach(label => {
        if (!allowedLabels.includes(label)) throw new Error('metric label not allowed');
        let row = labels.indexOf(label) + 1;
        if (!row) row = next++;
        sheet.getRange(row,1,1,2).setValues([[label,String(metrics[label]).slice(0,5000)]]);
        updated++;
      });
      return json_({ok:true,updated:updated});
    }

    if (action === 'update') {
      if (body.approved !== true) throw new Error('approval required');
      const a1 = String(body.range||'').toUpperCase();
      if (!/^[A-Z]{1,3}[1-9][0-9]{0,5}$/.test(a1)) throw new Error('single cell only');
      const sheet = book.getSheetByName(String(body.sheet||''));
      if (!sheet) throw new Error('sheet not found');
      const cell = sheet.getRange(a1);
      const before = cell.getDisplayValue();
      cell.setValue(body.value);
      return json_({ok:true,sheet:sheet.getName(),range:a1,before:before,after:cell.getDisplayValue()});
    }
  } catch(err) {
    return json_({ok:false,error:String(err)});
  }
}
