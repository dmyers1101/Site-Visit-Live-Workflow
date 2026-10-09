/**
 * Site Visit — work-order confirmation forms (ADR 0015).
 *
 * Runs as: the Google account that owns this Apps Script project
 *          (dmyers@shircapital.com for now). Sends as SENDER_FROM when set
 *          (swap to the sitevisits@ alias once the admin creates it).
 * Scheduled: one installable time trigger, `hourly`, created by `installTrigger`.
 * Reads/writes: the master catalog Sheet, tab `WorkOrders` (SHEET_ID). Forms are
 *          created in FORMS_FOLDER_ID (or the owner's My Drive if blank).
 *
 * It never creates anything in AppFolio. It only records the walker's decision;
 * the Cloud Run job `site-visit-workorders` (wo-run) does the AppFolio writes.
 *
 * Script Properties:
 *   SHEET_ID          master catalog spreadsheet ID (required)
 *   CUTOVER_DATE      ISO date; rows created before it never get a form (required)
 *   ESCALATE_TO       comma list, default "dmyers@shircapital.com,jcohen@signaturenexus.com"
 *   FALLBACK_TO       recipient when a row has no uploader_email (default: owner)
 *   SENDER_FROM       verified send-as alias; blank = send as the owner
 *   FORMS_FOLDER_ID   Drive folder for the forms (optional)
 *   DRY_RUN           "1" = log what would be sent; send and write nothing
 *
 * How to update this later: keep HEADERS in step with LEDGER_HEADERS in
 * src/site_visit_workflow/work_order_plan.py; append, never insert.
 */

var TAB = 'WorkOrders';
var HEADERS = ['wo_key', 'visit_drive_id', 'state', 'property', 'visit_name', 'uploader_email',
  'kind', 'group_label', 'clip_asset_ids', 'clip_links', 'location', 'issue_summary',
  'recommended_action', 'severity', 'priority',
  'form_id', 'form_url', 'form_item_id', 'form_sent_at', 'reminder_sent_at', 'escalated_at',
  'decision', 'existing_ref', 'decided_by', 'decided_at',
  'status', 'appfolio_property_id', 'idempotency_keys', 'appfolio_work_order_ids',
  'appfolio_links', 'last_error', 'created_at', 'updated_at', 'walker_description'];
var SEP = '; ';
var CHOICE_ONE = 'Create one AppFolio work order';
var CHOICE_SPLIT = 'Create a separate work order for each clip';
var CHOICE_EXISTS = 'A work order already exists (enter it below)';
var CHOICE_SKIP = 'No work order needed';
var REMIND_HOURS = 24;
var ESCALATE_HOURS = 48;

function hourly() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;
  try {
    collectResponses_();
    sendPendingForms_();
    remindAndEscalate_();
  } finally {
    lock.releaseLock();
  }
}

function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'hourly') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('hourly').timeBased().everyHours(1).create();
}

/** Run by hand: always really sends one email to the owner, even when DRY_RUN=1. */
function testSendAs() {
  var p = PropertiesService.getScriptProperties().getProperties();
  var me = Session.getEffectiveUser().getEmail();
  var opts = { name: 'Site Visit App' };
  if (p.SENDER_FROM) opts.from = p.SENDER_FROM;
  GmailApp.sendEmail(me, 'Site Visit work-order forms — send-as test',
    'Sent as: ' + (p.SENDER_FROM || me) + '. If this arrived from that address, sending works.', opts);
  Logger.log('testSendAs sent to ' + me + ' as ' + (p.SENDER_FROM || me));
}

// ---------------------------------------------------------------------------

function props_() {
  var p = PropertiesService.getScriptProperties().getProperties();
  if (!p.SHEET_ID || !p.CUTOVER_DATE) throw new Error('Set Script Properties SHEET_ID and CUTOVER_DATE.');
  p.ESCALATE_TO = p.ESCALATE_TO || 'dmyers@shircapital.com,jcohen@signaturenexus.com';
  p.FALLBACK_TO = p.FALLBACK_TO || Session.getEffectiveUser().getEmail();
  p.dry = p.DRY_RUN === '1';
  return p;
}

function ledger_(p) {
  var sheet = SpreadsheetApp.openById(p.SHEET_ID).getSheetByName(TAB);
  if (!sheet) throw new Error('Tab ' + TAB + ' not found — run wo-candidates first.');
  var values = sheet.getDataRange().getValues();
  var head = values[0];
  // Append missing trailing headers (never insert or rewrite existing ones).
  var filled = head.filter(String).length;
  if (filled < HEADERS.length && head.slice(0, filled).every(function (h, i) { return h === HEADERS[i]; }) && !p.dry) {
    if (sheet.getMaxColumns() < HEADERS.length) sheet.insertColumnsAfter(sheet.getMaxColumns(), HEADERS.length - sheet.getMaxColumns());
    sheet.getRange(1, filled + 1, 1, HEADERS.length - filled).setValues([HEADERS.slice(filled)]);
    values = sheet.getDataRange().getValues();
    head = values[0];
  }
  HEADERS.forEach(function (h, i) {
    if (head[i] !== h) throw new Error('WorkOrders header mismatch at column ' + (i + 1) + ': ' + head[i] + ' != ' + h);
  });
  var rows = values.slice(1).map(function (v, i) {
    var r = { _row: i + 2 };
    HEADERS.forEach(function (h, j) { r[h] = v[j] === undefined ? '' : String(v[j]); });
    return r;
  });
  return { sheet: sheet, rows: rows };
}

/** Write named cells for one key, re-finding the row first (Python may have appended). */
function write_(p, l, key, changes) {
  if (p.dry) { Logger.log('DRY_RUN write ' + key + ' ' + JSON.stringify(changes)); return; }
  var col = l.sheet.getRange(1, 1, l.sheet.getLastRow(), 1).getValues();
  var hits = [];
  col.forEach(function (c, i) { if (String(c[0]) === key) hits.push(i + 1); });
  if (hits.length !== 1) throw new Error('ledger key ' + key + ' found ' + hits.length + ' times');
  changes.updated_at = iso_(new Date());
  Object.keys(changes).forEach(function (h) {
    var idx = HEADERS.indexOf(h);
    if (idx < 0 || h === 'wo_key') throw new Error('refusing to write column ' + h);
    l.sheet.getRange(hits[0], idx + 1).setValue(changes[h]);
  });
}

function iso_(d) { return Utilities.formatDate(d, 'UTC', "yyyy-MM-dd'T'HH:mm:ss'Z'"); }
function hoursSince_(s) { return s ? (Date.now() - new Date(s).getTime()) / 3600000 : 0; }

function send_(to, subject, body, html) {
  var p = props_();
  if (p.dry) { Logger.log('DRY_RUN email to ' + to + ': ' + subject); return; }
  var opts = { name: 'Site Visit App', htmlBody: html || body };
  if (p.SENDER_FROM) opts.from = p.SENDER_FROM;
  GmailApp.sendEmail(to, subject, body, opts);
}

// ---------------------------------------------------------------------------

function sendPendingForms_() {
  var p = props_();
  var l = ledger_(p);
  var cutover = new Date(p.CUTOVER_DATE).getTime();
  var byVisit = {};
  l.rows.forEach(function (r) {
    if (r.status !== 'PENDING_REVIEW' || r.form_id) return;
    if (!r.created_at || new Date(r.created_at).getTime() < cutover) return;   // cutover filter
    (byVisit[r.visit_drive_id] = byVisit[r.visit_drive_id] || []).push(r);
  });
  Object.keys(byVisit).forEach(function (visitId) {
    var rows = byVisit[visitId];
    var first = rows[0];
    var title = 'Work orders — ' + first.property + ' — ' + first.visit_name;
    if (p.dry) { Logger.log('DRY_RUN form "' + title + '" with ' + rows.length + ' item(s)'); return; }
    var form = FormApp.create(title)
      .setDescription('From your site visit clips. Choose what should happen for each item. ' +
        'Nothing is created in AppFolio until you submit.')
      .setCollectEmail(true)
      .setLimitOneResponsePerUser(false)
      .setAllowResponseEdits(false);
    if (p.FORMS_FOLDER_ID) DriveApp.getFileById(form.getId()).moveTo(DriveApp.getFolderById(p.FORMS_FOLDER_ID));
    var items = [], ids = {};
    rows.forEach(function (r, n) {
      var clips = r.clip_links.split(SEP).filter(String);
      var help = [
        r.kind === 'REQUESTED' ? 'You asked for a work order on camera.' : 'Suggested from severity — not requested on camera.',
        r.location ? 'Location: ' + r.location : '',
        r.issue_summary ? 'Issue: ' + r.issue_summary : '',
        r.priority ? 'Priority if created: ' + r.priority : '',
        'Clips: ' + clips.join('  ')
      ].filter(String).join('\n');
      var choices = clips.length > 1 ? [CHOICE_ONE, CHOICE_SPLIT, CHOICE_EXISTS, CHOICE_SKIP]
                                     : [CHOICE_ONE, CHOICE_EXISTS, CHOICE_SKIP];
      var mc = form.addMultipleChoiceItem()
        .setTitle((n + 1) + '. ' + r.group_label + (clips.length > 1 ? ' (' + clips.length + ' clips)' : ''))
        .setHelpText(help).setChoiceValues(choices).setRequired(true);
      var desc = form.addParagraphTextItem()
        .setTitle((n + 1) + '. Work order description (edit as needed - this text goes into AppFolio)');
      var txt = form.addTextItem()
        .setTitle((n + 1) + '. Existing AppFolio work order # or link (only if it already exists)');
      items.push({ r: r, desc: desc });
      ids[r.wo_key] = mc.getId() + '|' + txt.getId() + '|' + desc.getId();
    });
    // Pre-fill every description box with the generated text, so the walker only edits.
    var pre = form.createResponse();
    items.forEach(function (it) { pre.withItemResponse(it.desc.createResponse(defaultDescription_(it.r))); });
    var url = pre.toPrefilledUrl();
    rows.forEach(function (r) {
      write_(p, l, r.wo_key, { form_id: form.getId(), form_url: url,
        form_item_id: ids[r.wo_key], form_sent_at: iso_(new Date()) });
    });
    var to = first.uploader_email || p.FALLBACK_TO;
    send_(to, 'Action needed: work orders from your ' + first.property + ' site visit',
      'Please confirm which items need an AppFolio work order, and edit the descriptions if needed: ' + url,
      '<p>Please confirm which items from your <b>' + first.property + '</b> site visit (' + first.visit_name +
      ') need an AppFolio work order. Each description is pre-filled - edit it to refine the directions.</p>' +
      '<p><a href="' + url + '">Open the form</a> - ' + rows.length + ' item(s).</p>');
  });
}

function collectResponses_() {
  var p = props_();
  var l = ledger_(p);
  var forms = {};
  l.rows.forEach(function (r) {
    if (r.status !== 'PENDING_REVIEW' || !r.form_id || r.decision) return;
    (forms[r.form_id] = forms[r.form_id] || []).push(r);
  });
  Object.keys(forms).forEach(function (formId) {
    var responses = FormApp.openById(formId).getResponses();
    if (!responses.length) return;
    var resp = responses[responses.length - 1];   // latest submission wins
    var answers = {};
    resp.getItemResponses().forEach(function (ir) { answers[ir.getItem().getId()] = String(ir.getResponse() || ''); });
    forms[formId].forEach(function (r) {
      var ids = r.form_item_id.split('|');
      var choice = answers[ids[0]];
      if (!choice) return;
      var ref = (answers[ids[1]] || '').trim();
      var c = { decided_by: resp.getRespondentEmail(), decided_at: iso_(resp.getTimestamp()), existing_ref: ref };
      if (ids[2]) c.walker_description = (answers[ids[2]] || '').trim().slice(0, 1800);
      if (choice === CHOICE_ONE) { c.decision = 'CREATE_ONE'; c.status = 'APPROVED'; }
      else if (choice === CHOICE_SPLIT) { c.decision = 'SPLIT'; c.status = 'APPROVED'; }
      else if (choice === CHOICE_EXISTS) {
        c.decision = 'EXISTS';
        c.status = ref ? 'EXISTS_PENDING' : 'EXISTS_UNVERIFIED';
        if (!ref) c.last_error = 'walker chose "already exists" but gave no number or link';
      } else if (choice === CHOICE_SKIP) { c.decision = 'SKIP'; c.status = 'DECLINED'; }
      else return;
      write_(p, l, r.wo_key, c);
    });
  });
}

/** The text pre-filled in the description box (mirrors work_order_plan.job_description). */
function defaultDescription_(r) {
  return [r.location ? 'Location: ' + r.location : '',
          r.issue_summary ? 'Issue: ' + r.issue_summary : '',
          r.recommended_action ? 'Recommended: ' + r.recommended_action : ''].filter(String).join('\n');
}

/**
 * Run by hand: forget the form on every row that is still unanswered, so the next
 * `hourly` sends a fresh form (e.g. after a form change). Answered rows are untouched.
 */
function resetUnansweredForms() {
  var p = props_();
  var l = ledger_(p);
  var n = 0;
  l.rows.forEach(function (r) {
    if (r.status === 'PENDING_REVIEW' && r.form_id && !r.decision) {
      write_(p, l, r.wo_key, { form_id: '', form_url: '', form_item_id: '', form_sent_at: '',
        reminder_sent_at: '', escalated_at: '' });
      n++;
    }
  });
  Logger.log('reset ' + n + ' unanswered row(s); run hourly to send fresh forms');
}

function remindAndEscalate_() {
  var p = props_();
  var l = ledger_(p);
  var forms = {};
  l.rows.forEach(function (r) {
    if (r.status === 'PENDING_REVIEW' && r.form_id && !r.decision) (forms[r.form_id] = forms[r.form_id] || []).push(r);
  });
  Object.keys(forms).forEach(function (formId) {
    var rows = forms[formId];
    var r = rows[0];
    var age = hoursSince_(r.form_sent_at);
    var to = r.uploader_email || p.FALLBACK_TO;
    if (age >= ESCALATE_HOURS && !r.escalated_at) {
      send_(p.ESCALATE_TO, 'Escalation: unanswered work-order form — ' + r.property + ' — ' + r.visit_name,
        'No response after 48 hours from ' + to + '. Form: ' + r.form_url +
        '\nLedger: https://docs.google.com/spreadsheets/d/' + p.SHEET_ID + '\nNothing has been created in AppFolio.');
      rows.forEach(function (x) { write_(p, l, x.wo_key, { escalated_at: iso_(new Date()) }); });
    } else if (age >= REMIND_HOURS && !r.reminder_sent_at) {
      send_(to, 'Reminder: work orders from your ' + r.property + ' site visit',
        'Please confirm which items need an AppFolio work order: ' + r.form_url);
      rows.forEach(function (x) { write_(p, l, x.wo_key, { reminder_sent_at: iso_(new Date()) }); });
    }
  });
}
