const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(url, body, method, signal) {
  const r = await fetch(url, {method: method || (body ? 'POST' : 'GET'), signal,
    headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
  if (r.status === 401) { location = '/login'; return null; }
  return r.json();
}
function table(cols, rows, render) {
  return '<table class="tbl"><tr>' + cols.map(c => `<th>${esc(c[1])}</th>`).join('') + '</tr>' +
    rows.map(r => '<tr>' + cols.map(c => `<td>${render ? render(c[0], r) : esc(r[c[0]])}</td>`).join('') + '</tr>').join('') + '</table>';
}
const kw = (k, r) => k === 'word' ? `<span class="kw">${esc(r[k])}</span>` : esc(r[k]);

let META, mode = 'dep', cur = 'lexical', depRes = {}, indRes = {}, indSrc = {}, HIST = [];
const STATUS = {ok: 'Passed', error: 'Failed', blocked: 'Blocked', stopped: 'Stopped'};
let run = null;   // the independent phase that is currently running
const badge = (r, k) => run && run.key === k && mode === 'ind' ? '<span class="badge running">Running…</span>'
  : r ? `<span class="badge ${r.status}">${STATUS[r.status]}</span>` : '<span class="badge idle">Not run</span>';

/* ---------- editor ---------- */
function gutter() {
  const n = $('code').value.split('\n').length;
  $('gutter').textContent = Array.from({length: n}, (_, i) => i + 1).join('\n');
}
function setupEditor() {
  const c = $('code');
  c.addEventListener('input', gutter);
  c.addEventListener('scroll', () => { $('gutter').scrollTop = c.scrollTop; });
  c.addEventListener('keydown', e => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const s = c.selectionStart;
      c.setRangeText('    ', s, c.selectionEnd, 'end');
      gutter();
    }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runAll(); }
  });
}

/* ---------- grammar ---------- */
function setupTabs() {
  document.querySelectorAll('#gtabs .tab').forEach(t => t.onclick = () => {
    document.querySelectorAll('#gtabs .tab').forEach(x => x.classList.toggle('on', x === t));
    document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'p-' + t.dataset.p));
  });
}

async function init() {
  META = await api('/api/meta');
  if (!META) return;
  $('kw').innerHTML = table([['purpose', 'Purpose'], ['word', 'Keyword']], META.keywords, kw);
  $('ty').innerHTML = table([['purpose', 'Purpose'], ['word', 'Keyword']], META.types, kw);
  $('op').innerHTML = table([['purpose', 'Purpose'], ['normal', 'Normal operator'], ['word', 'RomanEng']], META.operators, kw);
  $('bnf').textContent = META.bnf;
  $('code').value = META.sample;
  setupEditor(); setupTabs(); gutter();
  $('btnRun').onclick = runAll;
  $('btnSample').onclick = () => { $('code').value = META.sample; gutter(); };
  $('btnClear').onclick = () => { $('code').value = ''; gutter(); $('code').focus(); };
  $('btnClearHist').onclick = clearHist;
  document.querySelectorAll('#seg button').forEach(b => b.onclick = () => { if (run && b.dataset.m !== 'ind') stopRun(); mode = b.dataset.m; renderPhases(); });
  renderPhases();
  loadHistory();
}

/* ---------- run (dependent pipeline) ---------- */
async function runAll() {
  const btn = $('btnRun');
  btn.disabled = true; btn.textContent = 'Running…';
  const d = await api('/api/compile', {source: $('code').value, inputs: $('inp').value});
  btn.disabled = false; btn.textContent = '▶ Run';
  if (!d) return;
  depRes = d.phases; mode = 'dep'; renderPhases(); loadHistory();

  const con = $('console'); con.style.display = 'block';
  const fail = $('fail'), run = d.run;
  fail.style.display = 'none'; $('pyd').style.display = run ? '' : 'none';
  if (run) {
    $('out').textContent = run.output || '(the program printed nothing)';
    $('py').textContent = run.python;
    $('runBadge').innerHTML = run.error ? '<span class="badge error">Runtime error</span>' : '<span class="badge ok">Success</span>';
    if (run.error) { fail.style.display = 'block'; fail.textContent = run.error; }
  } else {
    const bad = META.phases.find(p => depRes[p.key].status === 'error');
    $('out').textContent = '';
    $('runBadge').innerHTML = '<span class="badge error">Compilation failed</span>';
    let msg = `<b>Stopped at ${esc(bad.title)}</b><br>`;
    const r = depRes[bad.key];
    msg += bad.key === 'semantic' && r.data.errors.length ? r.data.errors.map(esc).join('<br>') : esc(r.error);
    fail.innerHTML = msg + '<br><small>Open the Phases section for details.</small>'; fail.style.display = 'block';
  }
  con.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

/* ---------- independent run ---------- */
const STEP_MS = 600;   // each step of a generator is shown for a moment so that it can be stopped
const wait = (ms, sig) => new Promise((res, rej) => {
  const t = setTimeout(res, ms);
  sig.addEventListener('abort', () => { clearTimeout(t); rej(new DOMException('Aborted', 'AbortError')); });
});
async function runOne(k) {
  if (run) return;
  indSrc[k] = $('isrc').value;
  const ctrl = new AbortController();
  const total = META.phases.find(p => p.key === k).funcs.length;
  run = {key: k, ctrl, step: 0, total};
  run.timer = setInterval(() => { if (run && run.step < total) { run.step++; renderPhases(); } }, STEP_MS);
  renderPhases();
  try {
    const [r] = await Promise.all([api('/api/phase', {phase: k, source: indSrc[k]}, null, ctrl.signal), wait(total * STEP_MS, ctrl.signal)]);
    if (r) indRes[k] = r;
  } catch (e) {
    if (e.name === 'AbortError') indRes[k] = {status: 'stopped', data: {}, error: null};
    else indRes[k] = {status: 'error', data: {}, error: 'Request failed: ' + e.message};
  }
  clearInterval(run.timer); run = null;
  renderPhases();
}
function stopRun() { if (run) run.ctrl.abort(); }

/* ---------- phases ---------- */
function result(key, r) {
  if (!r) return `<div class="msg wait">${mode === 'dep' ? 'Press <b>Run</b> in the Compiler section to see the result.' : 'Press <b>Run this phase</b> to see the result.'}</div>`;
  if (r.status === 'stopped') return '<div class="msg wait">This phase was stopped before it finished. Run it again whenever you like.</div>';
  if (r.status === 'blocked') return `<div class="msg wait">${esc(r.error)}</div>`;
  const d = r.data; let h = '';
  if (r.status === 'error' && key !== 'semantic') h += `<div class="msg bad">${esc(r.error)}</div>`;
  if (key === 'lexical' && d.tokens)
    h += `<div class="scroll">` + table([['n', '#'], ['lexeme', 'Lexeme'], ['token', 'Token'], ['category', 'Category'], ['line', 'Line']], d.tokens,
      (c, t) => c === 'category' ? `<span class="cat cat-${t[c]}">${esc(t[c])}</span>` : c === 'lexeme' ? `<code>${esc(t[c])}</code>` : esc(t[c])) +
      `</div><p class="hintline">${d.tokens.length} tokens</p>`;
  if (key === 'syntax' && d.tree !== undefined) h += `<div class="msg ok">Syntax is valid. Parse tree:</div><pre class="tree">${esc(d.tree)}</pre>`;
  if (key === 'semantic') {
    (d.errors || []).forEach(e => h += `<div class="msg bad">${esc(e)}</div>`);
    if (r.status === 'ok') h += '<div class="msg ok">No semantic errors found.</div>';
    if (d.symbols && d.symbols.length) h += '<h3>Symbol table</h3><div class="scroll">' +
      table([['Name', 'Name'], ['Type', 'Type'], ['Kind', 'Kind'], ['Scope', 'Scope'], ['Line', 'Line']], d.symbols) + '</div>';
  }
  if (key === 'icg' && d.tac) h += `<pre class="tree">${esc(d.tac)}</pre>`;
  return h;
}

function renderPhases() {
  const P = META.phases, R = k => (mode === 'dep' ? depRes : indRes)[k];
  document.querySelectorAll('#seg button').forEach(b => b.classList.toggle('on', b.dataset.m === mode));
  $('modeDesc').textContent = mode === 'dep'
    ? 'Dependent mode: the phases run as a pipeline. Each phase uses the output of the previous one, and a failure blocks the phases after it.'
    : 'Independent mode: every phase runs on its own source code and does not depend on the other phases.';
  const flow = ['tokens', 'AST', 'checked AST'];
  $('stepper').className = 'stepper ' + mode;
  $('stepper').innerHTML = P.map((p, i) =>
    (i ? `<div class="conn">${flow[i - 1]}</div>` : '') +
    `<button class="sp ${cur === p.key ? 'on' : ''}" data-k="${p.key}"><span class="num">${p.num}</span><b>${esc(p.title)}</b><small>${esc(p.short)}</small>${badge(R(p.key), p.key)}</button>`).join('');
  const rb = $('runbar');
  if (run && mode === 'ind') {
    const rp = P.find(x => x.key === run.key);
    rb.innerHTML = `<div class="runbar"><span><span class="spin"></span> Running <b>${esc(rp.title)}</b>…</span><button class="btn danger sm" id="btnStop">■ Stop</button></div>`;
    $('btnStop').onclick = stopRun;
  } else rb.innerHTML = '';
  document.querySelectorAll('.sp').forEach(b => b.onclick = () => { cur = b.dataset.k; renderPhases(); });

  const p = P.find(x => x.key === cur);
  let h = `<h3 class="t">${p.num}. ${esc(p.title)}</h3><div>${esc(p.desc)}</div>
    <div class="chips"><span class="chip ${mode}"><b>${mode === 'dep' ? 'Dependent' : 'Independent'}</b></span>
    <span class="chip">Input: <b>${esc(mode === 'dep' ? p.input : 'its own source code')}</b></span><span class="chip">Output: <b>${esc(p.output)}</b></span></div>`;
  if (mode === 'dep') h += `<div class="hintline" style="margin:0 0 6px">${esc(p.dep)}</div>`;
  if (run && mode === 'ind' && run.key === cur)
    h += '<h3>Running</h3><ul class="funcs prog">' + p.funcs.map((f, i) =>
      `<li class="${i < run.step ? 'done' : i === run.step ? 'act' : ''}"><span class="ic">${i < run.step ? '✓' : i === run.step ? '<span class="spin"></span>' : '○'}</span>${esc(f)}</li>`).join('') + '</ul>';
  else h += '<h3>What it does</h3><ul class="funcs">' + p.funcs.map(f => `<li>${esc(f)}</li>`).join('') + '</ul>';
  if (mode === 'ind') {
    if (indSrc[cur] === undefined) indSrc[cur] = $('code').value;
    h += `<h3>Source for this phase</h3><div class="indbox"><textarea id="isrc" class="mono" rows="7" spellcheck="false">${esc(indSrc[cur])}</textarea></div>
      <button class="btn primary sm" id="btnOne" style="margin-top:10px" ${run ? 'disabled' : ''}>${run ? 'Another phase is running…' : '▶ Run this phase'}</button>`;
  }
  h += '<h3>Result</h3>' + (run && mode === 'ind' && run.key === cur ? '<div class="msg wait">Running… the result will appear when it finishes.</div>' : result(cur, R(cur)));
  $('panel').innerHTML = h;
  if (mode === 'ind') {
    $('isrc').oninput = e => { indSrc[cur] = e.target.value; };
    $('btnOne').onclick = () => runOne(cur);
  }
}

/* ---------- history ---------- */
async function loadHistory() {
  const d = await api('/api/history');
  if (!d) return;
  if (d.error) { $('hist').innerHTML = `<div class="msg bad">Database error: ${esc(d.error)}</div>`; return; }
  HIST = d.items;
  $('hist').innerHTML = HIST.length
    ? '<div class="scroll"><table class="tbl"><tr><th>#</th><th>Date</th><th>Status</th><th>Code</th><th></th></tr>' +
      HIST.map((h, i) => `<tr><td>${i + 1}</td><td>${esc(h.time)}</td><td><span class="badge ${h.status}">${h.status === 'success' ? 'Success' : 'Failed'}</span></td>
      <td><code>${esc(h.source.replace(/\s+/g, ' ').slice(0, 70))}</code></td>
      <td><button class="btn outline sm" data-i="${i}">Load</button></td></tr>`).join('') + '</table></div>'
    : '<div class="empty">No history yet. Run a program and it will appear here.</div>';
  document.querySelectorAll('#hist [data-i]').forEach(b => b.onclick = () => {
    $('code').value = HIST[+b.dataset.i].source; gutter(); location.hash = 'compiler';
  });
}
async function clearHist() {
  if (!confirm('Delete all of your saved history?')) return;
  await api('/api/history', null, 'DELETE');
  loadHistory();
}
init();
