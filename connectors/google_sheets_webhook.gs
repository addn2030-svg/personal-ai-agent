/**
 * Abdulrahman AI OS — Secure Google Sheets Gateway
 * Version 1.0.0 — 2026-09-11
 *
 * Contract (unchanged): append, metadata, addtab, snapshot, search, upsert_metrics, update
 * Added:                health, record_approval
 * BREAKING:             update requires an approval_id issued by record_approval.
 *                       Self-declared { approved: true } is rejected.
 *
 * Script Properties
 *   Required : SPREADSHEET_ID, AGENT_SECRET,
 *              APPROVAL_SECRET (must differ from AGENT_SECRET; used only by the human-approval path)
 *   Optional : GATEWAY_ENV = DEV | LIVE   (default DEV)
 *              LIVE_SPREADSHEET_ID        (a DEV gateway refuses every write to this ID)
 *
 * Optional on every mutating request: request_id (idempotency window: 6 hours)
 */

const GATEWAY_VERSION = '1.0.0';

const APPEND_TABS = [
  'مدخلات الوكيل', 'محادثات الوكيل', 'حالة الوكيل',
  'Decision_Log', 'Telegram_Log', 'FollowUp_Log', 'Approval_Log', 'Agent_Log',
  'تقارير المشرفين', 'Brief_History', 'Decisions', 'Risks_Blockers',
  'Important_Info', 'Commitments', 'Knowledge_Log', 'Audit_Log'
];

// Append-only: never editable through update / record_approval.
const APPEND_ONLY_TABS = [
  'Decision_Log', 'Telegram_Log', 'FollowUp_Log', 'Approval_Log',
  'Agent_Log', 'Brief_History', 'Knowledge_Log', 'Audit_Log'
];

const METRIC_SHEET = 'Executive_Brief';
const METRIC_LABELS = [
  'آخر تحديث للملخص التنفيذي', 'ملخص المدير الشخصي',
  'تغييرات جديدة منذ آخر Brief', 'عناصر أزيلت أو أغلقت',
  'قرارات تحتاج مراجعة', 'مخاطر وتعثرات مكتشفة',
  'آخر تقرير مشرف', 'ملخص تقرير المشرف',
  'مرضى التأهيل هذا الأسبوع', 'الإلغاء / عدم الحضور هذا الأسبوع',
  'قرار مطلوب من تقرير المشرف', 'آخر بلاغ مشرف طارئ'
];

const AUDIT_TAB = 'Gateway_Audit';
const APPROVALS_TAB = 'Gateway_Approvals';
const GATEWAY_TABS = [AUDIT_TAB, APPROVALS_TAB];
const AUDIT_HEADERS = ['timestamp', 'request_id', 'env', 'action', 'target', 'before', 'after', 'result'];
const APPROVAL_HEADERS = ['approval_id', 'sheet', 'range', 'value_sha256', 'approved_by',
  'approved_at', 'expires_at_ms', 'used_at', 'used_request_id'];

const MUTATING_ACTIONS = ['append', 'addtab', 'upsert_metrics', 'update', 'record_approval'];
const MAX_CELL_CHARS = 50000;
const MAX_METRIC_CHARS = 5000;
const MAX_ROW_CELLS = 60;
const CACHE_TTL_SECONDS = 21600;
const LOCK_WAIT_MS = 15000;


function doPost(e) {
  let body;
  try {
    body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return json_({ ok: false, error: 'invalid json' });
  }
  if (!body || typeof body !== 'object' || !safeEquals_(body.secret, prop_('AGENT_SECRET'))) {
    return json_({ ok: false, error: 'unauthorized' });
  }

  const action = String(body.action || 'append');
  const mutating = MUTATING_ACTIONS.indexOf(action) !== -1;
  const requestId = body.request_id ? String(body.request_id).slice(0, 100) : '';
  const cacheKey = mutating && requestId ? 'req:' + sha256_(action + '|' + requestId) : '';
  let lock = null;
  let lockHeld = false;

  try {
    const config = config_();
    if (mutating) {
      guardEnv_(config);
      lock = LockService.getScriptLock();
      if (!lock.tryLock(LOCK_WAIT_MS)) throw new Error('gateway busy, retry');
      lockHeld = true;
      if (cacheKey) {
        const hit = CacheService.getScriptCache().get(cacheKey);
        if (hit) {
          const previous = JSON.parse(hit);
          previous.duplicate = true;
          return json_(previous);
        }
      }
    }

    const ctx = {
      book: SpreadsheetApp.openById(config.spreadsheetId),
      body: body,
      config: config,
      requestId: requestId
    };
    const result = route_(action, ctx);

    if (cacheKey && result.ok) {
      try { CacheService.getScriptCache().put(cacheKey, JSON.stringify(result), CACHE_TTL_SECONDS); } catch (ignored) {}
    }
    return json_(result);
  } catch (err) {
    return json_({ ok: false, error: String((err && err.message) || err) });
  } finally {
    if (lock && lockHeld) { try { lock.releaseLock(); } catch (ignored) {} }
  }
}


function route_(action, ctx) {
  switch (action) {
    case 'health':          return actionHealth_(ctx);
    case 'append':          return actionAppend_(ctx);
    case 'metadata':        return actionMetadata_(ctx);
    case 'addtab':          return actionAddTab_(ctx);
    case 'snapshot':        return actionSnapshot_(ctx);
    case 'search':          return actionSearch_(ctx);
    case 'upsert_metrics':  return actionUpsertMetrics_(ctx);
    case 'record_approval': return actionRecordApproval_(ctx);
    case 'update':          return actionUpdate_(ctx);
    default: throw new Error('unsupported action');
  }
}


function actionHealth_(ctx) {
  return {
    ok: true,
    version: GATEWAY_VERSION,
    env: ctx.config.env,
    spreadsheet: ctx.book.getName(),
    // A spreadsheet ID is an identifier, not a secret. It lets the DEV verifier
    // prove that it did not point its writes at the configured LIVE workbook.
    spreadsheet_id: ctx.config.spreadsheetId,
    time: new Date().toISOString()
  };
}


function actionMetadata_(ctx) {
  const sheets = ctx.book.getSheets().map(s => ({
    title: s.getName(),
    sheetId: s.getSheetId(),
    rows: s.getMaxRows(),
    columns: s.getMaxColumns()
  }));
  return { ok: true, sheets: sheets };
}


function actionSnapshot_(ctx) {
  const maxRows = clamp_(ctx.body.maxRows, 80, 2, 150);
  const maxCols = clamp_(ctx.body.maxCols, 16, 2, 20);
  const data = {};
  readableSheets_(ctx.book).slice(0, 25).forEach(s => {
    const rows = Math.min(Math.max(s.getLastRow(), 1), maxRows);
    const cols = Math.min(Math.max(s.getLastColumn(), 1), maxCols);
    const values = s.getRange(1, 1, rows, cols).getDisplayValues();
    if (values.some(r => r.some(v => v !== ''))) data[s.getName()] = values;
  });
  return { ok: true, data: data };
}


function actionSearch_(ctx) {
  const q = String(ctx.body.query || '').trim().toLowerCase().slice(0, 200);
  if (!q) throw new Error('empty query');
  const limit = clamp_(ctx.body.maxResults, 25, 1, 50);
  const results = [];
  readableSheets_(ctx.book).forEach(s => {
    if (results.length >= limit) return;
    const rows = Math.min(Math.max(s.getLastRow(), 1), 300);
    const cols = Math.min(Math.max(s.getLastColumn(), 1), 20);
    const values = s.getRange(1, 1, rows, cols).getDisplayValues();
    values.forEach((r, i) => {
      if (results.length < limit && r.join(' | ').toLowerCase().indexOf(q) !== -1) {
        results.push({ sheet: s.getName(), row: i + 1, values: r });
      }
    });
  });
  return { ok: true, results: results };
}


function actionAppend_(ctx) {
  const b = ctx.body;
  if (APPEND_TABS.indexOf(b.tab) === -1) throw new Error('invalid append tab');
  if (!Array.isArray(b.row) || !b.row.length || b.row.length > MAX_ROW_CELLS) throw new Error('invalid row');
  const sheet = ctx.book.getSheetByName(b.tab);
  if (!sheet) throw new Error('sheet not found');
  sheet.appendRow(b.row.map(cell_));
  const rowNumber = sheet.getLastRow();
  const audited = audit_(ctx, 'append', b.tab + '!row=' + rowNumber, '', 'appended', 'ok');
  return { ok: true, row: rowNumber, audited: audited };
}


function actionAddTab_(ctx) {
  const b = ctx.body;
  const title = String(b.title || '').trim();
  if (!title || title.length > 100) throw new Error('invalid title');
  if (/[\[\]\*\?:\\/'"]/.test(title)) throw new Error('invalid tab name characters');

  if (GATEWAY_TABS.indexOf(title) !== -1) throw new Error('reserved tab name');

  const existing = ctx.book.getSheetByName(title);
  if (existing) return { ok: true, tab: title, existed: true };

  const rows = clamp_(b.rows, 1000, 2, 20000);
  const cols = clamp_(b.cols, 26, 1, 100);
  const sheet = ctx.book.insertSheet(title, ctx.book.getNumSheets(), { rowCount: rows, columnCount: cols });
  const audited = audit_(ctx, 'addtab', title, '', rows + 'x' + cols, 'created');
  return { ok: true, tab: title, existed: false, sheetId: sheet.getSheetId(), audited: audited };
}


function actionUpsertMetrics_(ctx) {
  const b = ctx.body;
  if (String(b.sheet || METRIC_SHEET) !== METRIC_SHEET) throw new Error('invalid metrics sheet');
  const metrics = b.metrics;
  if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) throw new Error('invalid metrics');

  const keys = Object.keys(metrics);
  if (!keys.length || keys.length > 20) throw new Error('metrics must contain 1-20 labels');
  const rejected = keys.filter(k => METRIC_LABELS.indexOf(k) === -1);
  if (rejected.length) throw new Error('metric label not allowed: ' + rejected.join(', '));

  const sheet = ctx.book.getSheetByName(METRIC_SHEET);
  if (!sheet) throw new Error('sheet not found');

  const lastRow = sheet.getLastRow();
  const labels = lastRow ? sheet.getRange(1, 1, lastRow, 1).getDisplayValues().map(r => r[0]) : [];
  let next = lastRow + 1;

  keys.forEach(label => {
    let row = labels.indexOf(label) + 1;
    if (!row) row = next++;
    const value = cell_(String(metrics[label]).slice(0, MAX_METRIC_CHARS));
    sheet.getRange(row, 1, 1, 2).setValues([[label, value]]);
  });

  const audited = audit_(ctx, 'upsert_metrics', METRIC_SHEET, '', keys.join(' | '), 'ok');
  return { ok: true, updated: keys.length, audited: audited };
}


function actionRecordApproval_(ctx) {
  const b = ctx.body;
  if (!safeEquals_(b.approval_secret, prop_('APPROVAL_SECRET'))) throw new Error('approval unauthorized');

  const approvalId = String(b.approval_id || '').trim();
  if (!/^[A-Za-z][A-Za-z0-9_\-:.]{5,79}$/.test(approvalId)) throw new Error('invalid approval_id');
  assertScalar_(b.value);
  const target = validateTarget_(ctx.book, b);

  const approvedBy = String(b.approved_by || '').trim().slice(0, 100);
  if (!approvedBy) throw new Error('approved_by required');
  const ttlMinutes = clamp_(b.ttl_minutes, 60, 1, 1440);

  const sheet = ensureTab_(ctx.book, APPROVALS_TAB, APPROVAL_HEADERS);
  if (findApprovalRow_(sheet, approvalId)) return { ok: true, approval_id: approvalId, existed: true };

  const now = Date.now();
  const expiresMs = now + ttlMinutes * 60000;
  sheet.appendRow([
    approvalId,
    target.sheet.getName(),
    target.a1,
    approvalHash_(b.value),
    cell_(approvedBy),
    new Date(now).toISOString(),
    expiresMs,
    '',
    ''
  ]);
  const approvalRow = sheet.getLastRow();
  // Keep identifiers/timestamps textual and the expiry epoch explicitly numeric;
  // this prevents an existing sheet number format from displaying an epoch as a date.
  sheet.getRange(approvalRow, 1, 1, 6).setNumberFormat('@');
  sheet.getRange(approvalRow, 7).setNumberFormat('0');
  sheet.getRange(approvalRow, 8, 1, 2).setNumberFormat('@');

  const audited = audit_(ctx, 'record_approval', target.sheet.getName() + '!' + target.a1, '',
    'approval_id=' + approvalId + ' by=' + approvedBy, 'recorded');
  return { ok: true, approval_id: approvalId, expires_at: new Date(expiresMs).toISOString(), audited: audited };
}


function actionUpdate_(ctx) {
  const b = ctx.body;
  const approvalId = String(b.approval_id || '').trim();
  if (!approvalId) {
    throw new Error(b.approved === true
      ? 'approval_id required: self-declared approved:true is no longer accepted'
      : 'approval required');
  }
  assertScalar_(b.value);
  const target = validateTarget_(ctx.book, b);

  const approvals = ctx.book.getSheetByName(APPROVALS_TAB);
  const found = approvals ? findApprovalRow_(approvals, approvalId) : null;
  if (!found) throw new Error('approval not found');

  const v = found.values;
  if (String(v[7])) throw new Error('approval already used');
  if (Number(v[6]) < Date.now()) throw new Error('approval expired');
  if (String(v[1]) !== target.sheet.getName() || String(v[2]) !== target.a1) {
    throw new Error('approval does not match target');
  }
  if (String(v[3]) !== approvalHash_(b.value)) throw new Error('approval does not match value');

  const cell = target.sheet.getRange(target.a1);
  const before = cell.getDisplayValue();
  cell.setValue(cell_(b.value));
  const after = cell.getDisplayValue();

  approvals.getRange(found.row, 8, 1, 2).setValues([[new Date().toISOString(), ctx.requestId || '']]);

  const audited = audit_(ctx, 'update', target.sheet.getName() + '!' + target.a1, before, after,
    'approval_id=' + approvalId);
  return {
    ok: true, sheet: target.sheet.getName(), range: target.a1,
    before: before, after: after, approval_id: approvalId, audited: audited
  };
}


function setupGateway() {
  const config = config_();
  ['AGENT_SECRET', 'APPROVAL_SECRET'].forEach(k => {
    if (!prop_(k)) throw new Error(k + ' is not set');
  });
  if (prop_('AGENT_SECRET') === prop_('APPROVAL_SECRET')) {
    throw new Error('APPROVAL_SECRET must differ from AGENT_SECRET');
  }
  guardEnv_(config);
  const book = SpreadsheetApp.openById(config.spreadsheetId);
  ensureTab_(book, AUDIT_TAB, AUDIT_HEADERS);
  ensureTab_(book, APPROVALS_TAB, APPROVAL_HEADERS);
  Logger.log('Gateway %s ready — env=%s — spreadsheet=%s', GATEWAY_VERSION, config.env, book.getName());
}


function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}


function prop_(key) {
  return PropertiesService.getScriptProperties().getProperty(key);
}


function config_() {
  const spreadsheetId = String(prop_('SPREADSHEET_ID') || '').trim();
  if (!spreadsheetId) throw new Error('SPREADSHEET_ID script property is not set');
  const env = String(prop_('GATEWAY_ENV') || 'DEV').toUpperCase();
  if (['DEV', 'LIVE'].indexOf(env) === -1) throw new Error('GATEWAY_ENV must be DEV or LIVE');
  return {
    spreadsheetId: spreadsheetId,
    env: env,
    liveId: String(prop_('LIVE_SPREADSHEET_ID') || '').trim()
  };
}


function guardEnv_(config) {
  if (config.env !== 'LIVE' && config.liveId && config.spreadsheetId === config.liveId) {
    throw new Error('DEV gateway is not allowed to write to the LIVE spreadsheet');
  }
}


function sha256_(text) {
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(text), Utilities.Charset.UTF_8);
  return bytes.map(b => ('0' + (b & 0xff).toString(16)).slice(-2)).join('');
}


function approvalHash_(value) {
  return 'sha256:' + sha256_(valueKey_(value));
}


function safeEquals_(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || !b) return false;
  const ha = sha256_(a);
  const hb = sha256_(b);
  let diff = 0;
  for (let i = 0; i < ha.length; i++) diff |= ha.charCodeAt(i) ^ hb.charCodeAt(i);
  return diff === 0;
}


function clamp_(value, fallback, min, max) {
  return Math.max(min, Math.min(Number(value) || fallback, max));
}


function readableSheets_(book) {
  return book.getSheets().filter(s => GATEWAY_TABS.indexOf(s.getName()) === -1);
}


function assertScalar_(v) {
  const t = typeof v;
  if (!(v === null || t === 'string' || t === 'number' || t === 'boolean')) {
    throw new Error('value must be string, number, boolean or null');
  }
}


function valueKey_(v) {
  return v === null || v === undefined ? '' : String(v);
}


function cell_(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return isFinite(v) ? v : String(v);
  if (typeof v === 'boolean') return v;
  let s = typeof v === 'string' ? v : JSON.stringify(v);
  if (s.length > MAX_CELL_CHARS - 1) s = s.slice(0, MAX_CELL_CHARS - 1);
  if (/^[=+\-@\t\r]/.test(s) && !/^[+-]?\d+(\.\d+)?$/.test(s)) s = "'" + s;
  return s;
}


function validateTarget_(book, body) {
  const a1 = String(body.range || '').toUpperCase();
  if (!/^[A-Z]{1,3}[1-9][0-9]{0,5}$/.test(a1)) throw new Error('single cell only');
  const name = String(body.sheet || '');
  if (APPEND_ONLY_TABS.indexOf(name) !== -1 || GATEWAY_TABS.indexOf(name) !== -1) {
    throw new Error('tab is append-only or protected');
  }
  const sheet = book.getSheetByName(name);
  if (!sheet) throw new Error('sheet not found');
  return { sheet: sheet, a1: a1 };
}


function protectManaged_(sheet) {
  const protections = sheet.getProtections(SpreadsheetApp.ProtectionType.SHEET);
  const protection = protections.length ? protections[0] : sheet.protect();
  protection.setDescription('Managed by AI OS gateway — do not edit manually').setWarningOnly(false);
}


function ensureTab_(book, name, headers) {
  let sheet = book.getSheetByName(name);
  if (!sheet) {
    sheet = book.insertSheet(name, book.getNumSheets());
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
  }
  protectManaged_(sheet);
  return sheet;
}


function findApprovalRow_(sheet, approvalId) {
  const last = sheet.getLastRow();
  if (last < 2) return null;
  const values = sheet.getRange(2, 1, last - 1, APPROVAL_HEADERS.length).getValues();
  for (let i = values.length - 1; i >= 0; i--) {
    if (String(values[i][0]) === approvalId) return { row: i + 2, values: values[i] };
  }
  return null;
}


function audit_(ctx, action, target, before, after, result) {
  try {
    const sheet = ensureTab_(ctx.book, AUDIT_TAB, AUDIT_HEADERS);
    sheet.appendRow([
      new Date().toISOString(), ctx.requestId || '', ctx.config.env,
      action, target, before, after, result
    ].map(cell_));
    return true;
  } catch (err) {
    return false;
  }
}
