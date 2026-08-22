/**
 * Abdulrahman AI OS secure Google Sheets gateway.
 * Supports append, metadata, bounded snapshot/search, and confirmed single-cell updates.
 */
const SPREADSHEET_ID = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID')
  || '1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc';

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    const body = JSON.parse((e.postData && e.postData.contents) || '{}');
    const expected = PropertiesService.getScriptProperties().getProperty('AGENT_SECRET');
    if (!expected || body.secret !== expected) return json_({ok:false,error:'unauthorized'});
    const book = SpreadsheetApp.openById(SPREADSHEET_ID);
    const action = body.action || 'append';

    if (action === 'append') {
      const allowed = ['مدخلات الوكيل','محادثات الوكيل','حالة الوكيل',
        'Decision_Log','Telegram_Log','FollowUp_Log','Approval_Log','Agent_Log'];
      if (!allowed.includes(body.tab) || !Array.isArray(body.row)) throw new Error('invalid append');
      const sheet=book.getSheetByName(body.tab);
      if (!sheet) throw new Error('sheet not found');
      sheet.appendRow(body.row);
      return json_({ok:true});
    }

    if (action === 'metadata') {
      const sheets=book.getSheets().map(s=>({title:s.getName(),sheetId:s.getSheetId(),
        rows:s.getMaxRows(),columns:s.getMaxColumns()}));
      return json_({ok:true,sheets:sheets});
    }

    if (action === 'snapshot') {
      const maxRows=Math.max(2,Math.min(Number(body.maxRows)||80,150));
      const maxCols=Math.max(2,Math.min(Number(body.maxCols)||16,20));
      const data={};
      book.getSheets().slice(0,25).forEach(s=>{
        const rows=Math.min(Math.max(s.getLastRow(),1),maxRows);
        const cols=Math.min(Math.max(s.getLastColumn(),1),maxCols);
        const values=s.getRange(1,1,rows,cols).getDisplayValues();
        if (values.some(r=>r.some(v=>v!==''))) data[s.getName()]=values;
      });
      return json_({ok:true,data:data});
    }

    if (action === 'search') {
      const q=String(body.query||'').trim().toLowerCase();
      if (!q) throw new Error('empty query');
      const limit=Math.max(1,Math.min(Number(body.maxResults)||25,50));
      const results=[];
      book.getSheets().forEach(s=>{
        if (results.length>=limit) return;
        const rows=Math.min(Math.max(s.getLastRow(),1),300);
        const cols=Math.min(Math.max(s.getLastColumn(),1),20);
        const values=s.getRange(1,1,rows,cols).getDisplayValues();
        values.forEach((r,i)=>{
          if(results.length<limit && r.join(' | ').toLowerCase().includes(q))
            results.push({sheet:s.getName(),row:i+1,values:r});
        });
      });
      return json_({ok:true,results:results});
    }

    if (action === 'update') {
      if (body.approved !== true) throw new Error('approval required');
      const a1=String(body.range||'').toUpperCase();
      if (!/^[A-Z]{1,3}[1-9][0-9]{0,5}$/.test(a1)) throw new Error('single cell only');
      const sheet=book.getSheetByName(String(body.sheet||''));
      if (!sheet) throw new Error('sheet not found');
      const cell=sheet.getRange(a1);
      const before=cell.getDisplayValue();
      cell.setValue(body.value);
      return json_({ok:true,sheet:sheet.getName(),range:a1,before:before,after:cell.getDisplayValue()});
    }
    throw new Error('unsupported action');
  } catch(err) {
    return json_({ok:false,error:String(err)});
  }
}
