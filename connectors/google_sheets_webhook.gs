/**
 * Abdulrahman AI OS secure Google Workspace gateway v0.8.
 *
 * Existing operations remain compatible: append, metadata, snapshot, search,
 * upsert_metrics, and approved single-cell update.
 *
 * New read-only knowledge operations:
 *   knowledge_access, knowledge_search, knowledge_read, sheetcheck, ping
 *
 * Security model:
 *   - every request requires AGENT_SECRET
 *   - knowledge is restricted to explicit spreadsheet/folder allowlists
 *   - no Drive delete/write operation exists here
 *   - sheet writes remain restricted to the existing approved paths
 */
const SPREADSHEET_ID = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID')
  || '1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc';
const INDEX_SHEET_ID = '17RlQn1ePixFMSnWipTUALFE_zuGjMWz121IaLOLE2U4';
const KNOWLEDGE_FOLDER_IDS = [
  '1IKEeBHuqRaUEOCXL_xNSPVIs3UInFLDQ',
  '1V3w7lP0nZce6bVkj8c9dxYi4ASdtgIoJ',
  '1OVM6HCRhcOJyd62iFxcUhTlNU8rAOaOR',
  '1HNWIcitrgyKMKl5yc8AstG2fpSmTy1oI',
  '1S57W5ac7hD4ebINKZSLWV-XonwVHN',
  '1VE26NRhR8BaDxarLocNLK9hbwK9Nyt8g'
];
const DOC_MIME = 'application/vnd.google-apps.document';
const SHEET_MIME = 'application/vnd.google-apps.spreadsheet';
const FOLDER_MIME = 'application/vnd.google-apps.folder';
const TEXT_MIMES = ['text/plain','text/markdown','text/csv','application/json'];

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function errorText_(err) {
  return String(err || 'unknown error').slice(0, 300);
}

function allowedSpreadsheetIds_() {
  return [SPREADSHEET_ID, INDEX_SHEET_ID];
}

function isAllowedSpreadsheetId_(id) {
  return allowedSpreadsheetIds_().indexOf(String(id || '')) >= 0;
}

function fileIsInsideAllowedFolder_(file) {
  let parents = file.getParents();
  let depth = 0;
  while (parents.hasNext() && depth < 8) {
    const parent = parents.next();
    if (KNOWLEDGE_FOLDER_IDS.indexOf(parent.getId()) >= 0) return true;
    parents = parent.getParents();
    depth++;
  }
  return false;
}

function fileAllowed_(fileId) {
  const id = String(fileId || '');
  if (isAllowedSpreadsheetId_(id)) return true;
  const file = DriveApp.getFileById(id);
  return fileIsInsideAllowedFolder_(file);
}

function spreadsheetStatus_(id) {
  const row = {id:id, ok:false, title:''};
  try {
    const book = SpreadsheetApp.openById(id);
    row.ok = true;
    row.title = book.getName();
  } catch (err) {
    row.error = errorText_(err);
  }
  return row;
}

function folderStatus_(id) {
  const row = {id:id, ok:false, title:''};
  try {
    const folder = DriveApp.getFolderById(id);
    row.ok = true;
    row.title = folder.getName();
  } catch (err) {
    row.error = errorText_(err);
  }
  return row;
}

function knowledgeAccess_() {
  return {
    ok:true,
    gateway:'apps_script',
    spreadsheets:allowedSpreadsheetIds_().map(spreadsheetStatus_),
    folders:KNOWLEDGE_FOLDER_IDS.map(folderStatus_)
  };
}

function addIndexMatches_(query, limit, results) {
  try {
    const book = SpreadsheetApp.openById(INDEX_SHEET_ID);
    const tabs = book.getSheets().slice(0, 12);
    tabs.forEach(function(sheet) {
      if (results.length >= limit) return;
      const rows = Math.min(Math.max(sheet.getLastRow(), 1), 250);
      const cols = Math.min(Math.max(sheet.getLastColumn(), 1), 8);
      const values = sheet.getRange(1, 1, rows, cols).getDisplayValues();
      values.slice(1).forEach(function(row) {
        if (results.length >= limit) return;
        const joined = row.join(' | ').toLowerCase();
        if (joined.indexOf(query) >= 0) {
          results.push({
            source:'index',
            tab:sheet.getName(),
            name:row.length > 1 ? row[1] : '',
            url:row.length > 4 ? row[4] : ''
          });
        }
      });
    });
  } catch (err) {
    // Folder search below remains available even if the index sheet is unavailable.
  }
}

function scanFolderNames_(folder, query, limit, results, state, depth) {
  if (results.length >= limit || state.scanned >= 500 || depth > 3) return;

  const files = folder.getFiles();
  while (files.hasNext() && results.length < limit && state.scanned < 500) {
    const file = files.next();
    state.scanned++;
    if (file.getName().toLowerCase().indexOf(query) >= 0) {
      results.push({
        source:'folder',
        folder_id:folder.getId(),
        name:file.getName(),
        url:file.getUrl(),
        mimeType:file.getMimeType()
      });
    }
  }

  const folders = folder.getFolders();
  while (folders.hasNext() && results.length < limit && state.scanned < 500) {
    const child = folders.next();
    state.scanned++;
    if (child.getName().toLowerCase().indexOf(query) >= 0) {
      results.push({
        source:'folder',
        folder_id:folder.getId(),
        name:child.getName(),
        url:child.getUrl(),
        mimeType:FOLDER_MIME
      });
    }
    scanFolderNames_(child, query, limit, results, state, depth + 1);
  }
}

function knowledgeSearch_(body) {
  const query = String(body.query || '').trim().toLowerCase();
  if (!query) throw new Error('empty query');
  const limit = Math.max(1, Math.min(Number(body.maxResults) || 20, 30));
  const results = [];
  addIndexMatches_(query, limit, results);
  const state = {scanned:0};
  KNOWLEDGE_FOLDER_IDS.forEach(function(folderId) {
    if (results.length >= limit || state.scanned >= 500) return;
    try {
      scanFolderNames_(DriveApp.getFolderById(folderId), query, limit, results, state, 0);
    } catch (err) {
      // One inaccessible folder must not block the other approved sources.
    }
  });
  return {ok:true, results:results, scanned:state.scanned};
}

function sheetText_(book, maxChars) {
  const chunks = [];
  let used = 0;
  book.getSheets().slice(0, 12).forEach(function(sheet) {
    if (used >= maxChars) return;
    const rows = Math.min(Math.max(sheet.getLastRow(), 1), 80);
    const cols = Math.min(Math.max(sheet.getLastColumn(), 1), 20);
    const values = sheet.getRange(1, 1, rows, cols).getDisplayValues();
    const text = '[' + sheet.getName() + ']\n' + values.map(function(row) {
      return row.join(' | ');
    }).join('\n');
    const remaining = Math.max(maxChars - used, 0);
    chunks.push(text.slice(0, remaining));
    used += Math.min(text.length, remaining);
  });
  return chunks.join('\n\n').slice(0, maxChars);
}

function knowledgeRead_(body) {
  const fileId = String(body.fileId || '').trim();
  if (!fileId) throw new Error('missing fileId');
  if (!fileAllowed_(fileId)) throw new Error('file outside approved knowledge sources');
  const maxChars = Math.max(1000, Math.min(Number(body.maxChars) || 12000, 16000));
  const file = DriveApp.getFileById(fileId);
  const mime = file.getMimeType();
  let text = '';
  let note = '';

  if (mime === DOC_MIME) {
    text = DocumentApp.openById(fileId).getBody().getText().slice(0, maxChars);
  } else if (mime === SHEET_MIME) {
    text = sheetText_(SpreadsheetApp.openById(fileId), maxChars);
  } else if (TEXT_MIMES.indexOf(mime) >= 0) {
    text = file.getBlob().getDataAsString().slice(0, maxChars);
  } else {
    note = 'يمكن للوكيل رؤية الملف ومعلوماته، لكن القراءة النصية لهذا النوع غير مفعلة بعد.';
  }

  return {
    ok:true,
    name:file.getName(),
    url:file.getUrl(),
    mimeType:mime,
    text:text,
    note:note
  };
}

function sheetcheck_(body) {
  const id = String(body.spreadsheetId || '').trim();
  if (!isAllowedSpreadsheetId_(id)) throw new Error('spreadsheet outside allowlist');
  const book = SpreadsheetApp.openById(id);
  return {
    ok:true,
    id:id,
    title:book.getName(),
    tabs:book.getSheets().map(function(sheet) { return sheet.getName(); })
  };
}

function ping_() {
  return {
    ok:true,
    version:'google-gateway-v0.8',
    actions:[
      'append','metadata','snapshot','search','upsert_metrics','update',
      'knowledge_access','knowledge_search','knowledge_read','sheetcheck','ping'
    ]
  };
}

function doPost(e) {
  try {
    const body = JSON.parse((e.postData && e.postData.contents) || '{}');
    const expected = PropertiesService.getScriptProperties().getProperty('AGENT_SECRET');
    if (!expected || body.secret !== expected) return json_({ok:false,error:'unauthorized'});
    const action = body.action || 'append';

    if (action === 'ping') return json_(ping_());
    if (action === 'knowledge_access') return json_(knowledgeAccess_());
    if (action === 'knowledge_search') return json_(knowledgeSearch_(body));
    if (action === 'knowledge_read') return json_(knowledgeRead_(body));
    if (action === 'sheetcheck') return json_(sheetcheck_(body));

    const book = SpreadsheetApp.openById(SPREADSHEET_ID);

    if (action === 'append') {
      const allowed = ['مدخلات الوكيل','محادثات الوكيل','حالة الوكيل',
        'Decision_Log','Telegram_Log','FollowUp_Log','Approval_Log','Agent_Log',
        'تقارير المشرفين','Brief_History','Decisions','Risks_Blockers',
        'Important_Info','Commitments','Knowledge_Log','Audit_Log'];
      if (!allowed.includes(body.tab) || !Array.isArray(body.row)) throw new Error('invalid append');
      const sheet = book.getSheetByName(body.tab);
      if (!sheet) throw new Error('sheet not found');
      sheet.appendRow(body.row);
      return json_({ok:true});
    }

    if (action === 'metadata') {
      const sheets = book.getSheets().map(function(sheet) {
        return {title:sheet.getName(),sheetId:sheet.getSheetId(),
          rows:sheet.getMaxRows(),columns:sheet.getMaxColumns()};
      });
      return json_({ok:true,sheets:sheets});
    }

    if (action === 'snapshot') {
      const maxRows = Math.max(2, Math.min(Number(body.maxRows) || 80, 150));
      const maxCols = Math.max(2, Math.min(Number(body.maxCols) || 16, 20));
      const data = {};
      book.getSheets().slice(0,25).forEach(function(sheet) {
        const rows = Math.min(Math.max(sheet.getLastRow(),1),maxRows);
        const cols = Math.min(Math.max(sheet.getLastColumn(),1),maxCols);
        const values = sheet.getRange(1,1,rows,cols).getDisplayValues();
        if (values.some(function(row) { return row.some(function(v) { return v !== ''; }); })) {
          data[sheet.getName()] = values;
        }
      });
      return json_({ok:true,data:data});
    }

    if (action === 'search') {
      const q = String(body.query || '').trim().toLowerCase();
      if (!q) throw new Error('empty query');
      const limit = Math.max(1, Math.min(Number(body.maxResults) || 25, 50));
      const results = [];
      book.getSheets().forEach(function(sheet) {
        if (results.length >= limit) return;
        const rows = Math.min(Math.max(sheet.getLastRow(),1),300);
        const cols = Math.min(Math.max(sheet.getLastColumn(),1),20);
        const values = sheet.getRange(1,1,rows,cols).getDisplayValues();
        values.forEach(function(row, index) {
          if (results.length < limit && row.join(' | ').toLowerCase().indexOf(q) >= 0) {
            results.push({sheet:sheet.getName(),row:index+1,values:row});
          }
        });
      });
      return json_({ok:true,results:results});
    }

    if (action === 'upsert_metrics') {
      const sheetName = String(body.sheet || 'Executive_Brief');
      if (sheetName !== 'Executive_Brief') throw new Error('invalid metrics sheet');
      const metrics = body.metrics;
      if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) throw new Error('invalid metrics');
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
      let next = last + 1;
      let updated = 0;
      Object.keys(metrics).slice(0,20).forEach(function(label) {
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
      const a1 = String(body.range || '').toUpperCase();
      if (!/^[A-Z]{1,3}[1-9][0-9]{0,5}$/.test(a1)) throw new Error('single cell only');
      const sheet = book.getSheetByName(String(body.sheet || ''));
      if (!sheet) throw new Error('sheet not found');
      const cell = sheet.getRange(a1);
      const before = cell.getDisplayValue();
      cell.setValue(body.value);
      return json_({ok:true,sheet:sheet.getName(),range:a1,before:before,after:cell.getDisplayValue()});
    }

    throw new Error('unsupported action');
  } catch (err) {
    return json_({ok:false,error:errorText_(err)});
  }
}
