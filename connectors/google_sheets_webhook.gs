/**
 * Abdulrahman AI OS -> Google Sheets secure append webhook.
 * 1) Set Script Property AGENT_SECRET.
 * 2) Deploy as Web app: Execute as me; access Anyone.
 * 3) Put deployment URL and the same secret in Railway.
 */
const SPREADSHEET_ID = '1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc';

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents || '{}');
    const expected = PropertiesService.getScriptProperties().getProperty('AGENT_SECRET');
    if (!expected || body.secret !== expected) {
      return ContentService.createTextOutput(JSON.stringify({ok:false,error:'unauthorized'}))
        .setMimeType(ContentService.MimeType.JSON);
    }
    const allowed = ['مدخلات الوكيل', 'محادثات الوكيل', 'حالة الوكيل'];
    if (!allowed.includes(body.tab) || !Array.isArray(body.row)) {
      throw new Error('invalid payload');
    }
    const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(body.tab);
    if (!sheet) throw new Error('sheet not found');
    sheet.appendRow(body.row);
    return ContentService.createTextOutput(JSON.stringify({ok:true}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ok:false,error:String(err)}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
