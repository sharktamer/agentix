const API = window.location.origin;

function generateId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

const S = {
  agents: [],
  providers: {},
  selected: null,
  wsId: null,
  ws: null,
  processing: false,
  procId: null,
  allTools: {},
  spawnBlocks: {},
  currentSpawnId: null,
  agentFilter: '',
  tagFilter: new Set(),
  showLudique: true,
  mode: 'chat',           // 'chat' | 'debate' | 'battle'
  debateId: null,
  debating: false,
  debateAgents: new Set(),
  debateThinkingEl: null,
  battleId: null,
  battling: false,
  battleAgents: new Set(),
  battleThinkingEl: null,
  battleEliminated: new Set(),
};

// Palette de couleurs pour les agents du débat (cyclique)
const DEBATE_COLORS = [
  { bg: 'var(--accent-dim)',  fg: 'var(--accent)'  },
  { bg: 'var(--green-dim)',   fg: 'var(--green)'   },
  { bg: 'var(--amber-dim)',   fg: 'var(--amber)'   },
  { bg: 'var(--purple-dim)',  fg: 'var(--purple)'  },
  { bg: 'var(--orange-dim)',  fg: 'var(--orange)'  },
  { bg: 'var(--red-dim)',     fg: 'var(--red)'     },
];
const _debateColorMap = {};
function debateColor(name) {
  if (!_debateColorMap[name]) {
    const idx = Object.keys(_debateColorMap).length % DEBATE_COLORS.length;
    _debateColorMap[name] = DEBATE_COLORS[idx];
  }
  return _debateColorMap[name];
}

// ─── Views ─────────────────────────────────────────────────────────────────
let _currentView = null;
const _viewCache = {};

function _saveView(name) {
  const app = document.getElementById('app');
  const frag = document.createDocumentFragment();
  while (app.firstChild) frag.appendChild(app.firstChild);
  _viewCache[name] = frag;
}

function _restoreView(name) {
  if (!_viewCache[name]) return false;
  document.getElementById('app').appendChild(_viewCache[name]);
  delete _viewCache[name];
  return true;
}

const ChatView = {
  mount() {
    const app = document.getElementById('app');
    app.className = 'mode-chat';
    if (_restoreView('chat')) {
      renderAgents();
      renderTagFilters();
      return;
    }
    app.appendChild(document.getElementById('tpl-chat').content.cloneNode(true));
    const mfBtn = document.getElementById('mode-filter-btn');
    if (mfBtn) {
      mfBtn.classList.toggle('ludique', S.showLudique);
      document.getElementById('mode-filter-icon').textContent  = S.showLudique ? '🎭' : '🔧';
      document.getElementById('mode-filter-label').textContent = S.showLudique ? 'Ludiques' : 'Utiles';
    }
    setupInput();
    renderAgents();
    renderTagFilters();
    if (S.selected) {
      document.getElementById('atitle').textContent = S.selected.name;
      document.getElementById('atitle').style.color = 'var(--text)';
      document.getElementById('amodelpill').textContent    = S.selected.model;
      document.getElementById('amodelpill').style.display  = 'block';
      document.getElementById('aspawnpill').style.display  = S.selected.can_spawn ? 'block' : 'none';
      document.getElementById('hdr-clear').style.display   = 'block';
      document.getElementById('msginput').disabled = false;
      _setSendBtn('send');
      renderTools(S.selected.allowed_tools || []);
      loadAgentContextSliders(S.selected.context_limits);
      loadAgentSession(S.selected.name);
      connectWS();
    }
  },
  teardown() { _saveView('chat'); },
};

const SalonView = {
  mount() {
    const app = document.getElementById('app');
    app.className = 'mode-salon';
    if (_restoreView('salon')) { renderDebateAgents(); return; }
    app.appendChild(document.getElementById('tpl-salon').content.cloneNode(true));
    renderDebateAgents();
  },
  teardown() { _saveView('salon'); },
};

const BattleView = {
  mount() {
    const app = document.getElementById('app');
    app.className = 'mode-battle';
    if (_restoreView('battle')) { renderBattleAgents(); return; }
    app.appendChild(document.getElementById('tpl-battle').content.cloneNode(true));
    renderBattleAgents();
  },
  teardown() { _saveView('battle'); },
};

// ─── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  _currentView = ChatView;
  ChatView.mount();
  document.getElementById('hdr-home')?.classList.add('home-active');
  if (isMobile()) mobileTab('sidebar');
  await Promise.all([loadAgents(), loadAllTools(), loadProviders()]);
});

async function loadAgents() {
  try {
    const d = await api('/agents');
    S.agents = d.agents || [];
    renderAgents();
    renderTagFilters();
    renderSharedRag(d.shared_rag);
  } catch {
    document.getElementById('aglist').innerHTML =
      `<div class="empty" style="padding:20px;font-size:12px;color:var(--red);">Backend inaccessible.<br><code>uv run main.py</code></div>`;
  }
}

function renderSharedRag(status) {
  const el = document.getElementById('rag-status');
  if (!el) return;
  if (!status || !status.available) {
    el.textContent = '📚 KB partagée : RAG non disponible';
    el.style.color = 'var(--muted)';
  } else {
    el.textContent = `📚 KB partagée : ${status.count} chunk(s)`;
    el.style.color = status.count > 0 ? 'var(--green)' : 'var(--muted)';
  }
}

async function indexKnowledge() {
  const btn = document.getElementById('btn-index');
  btn.textContent = '⏳ Indexation...';
  btn.disabled = true;
  try {
    const d = await api('/knowledge/index', 'POST');
    if (d.error) {
      log('error', `❌ Indexation KB : ${d.error}`);
    } else {
      log('rag', `✅ KB indexée : ${d.stats?.indexed || 0} fichier(s), ${d.stats?.chunks || 0} chunk(s)`);
      await loadAgents();
    }
  } catch(e) {
    log('error', `❌ Indexation KB : ${e.message}`);
  } finally {
    btn.textContent = '📚 Indexer KB';
    btn.disabled = false;
  }
}

async function loadAllTools() {
  try {
    const d = await api('/tools');
    S.allTools = {};
    for (const t of (d.tools || [])) S.allTools[t.function.name] = t;
  } catch {}
}

// ─── Contexte par agent ────────────────────────────────────────────────────
function loadAgentContextSliders(limits) {
  const d = limits || {total:3000,system:600,history:1000,rag:800,tools:300,user:300};
  document.getElementById('ctx-no-agent').style.display = 'none';
  document.getElementById('ctx-settings').style.display = 'block';
  document.getElementById('ctx-agent-name').textContent = S.selected?.name || '';
  const fields = ['total','system','history','rag','tools','user'];
  for (const f of fields) {
    const slider = document.getElementById(`cr-${f}`);
    const label  = document.getElementById(`cv-${f}`);
    if (slider && d[f] !== undefined) { slider.value = d[f]; if(label) label.textContent = d[f]; }
  }
  updateTokenLimitsDisplay(d);
  updateCtxSum();
}

function updateTokenLimitsDisplay(d) {
  const map = {system:'lims', history:'limh', rag:'limr', tools:'limt', user:'limu'};
  for (const [k,id] of Object.entries(map)) {
    const el = document.getElementById(id);
    if (el && d[k] !== undefined) el.textContent = d[k];
  }
  const tm = document.getElementById('tm');
  if (tm && d.total) tm.textContent = d.total;
}

function updateCtxSum() {
  const fields = ['system','history','rag','tools','user'];
  const total  = parseInt(document.getElementById('cr-total')?.value || 3000);
  const sum    = fields.reduce((acc,f) => acc + parseInt(document.getElementById(`cr-${f}`)?.value || 0), 0);
  const warn   = document.getElementById('ctx-sum-warning');
  if (!warn) return;
  if (sum > total) {
    warn.style.display = 'block';
    warn.style.background = 'var(--red-dim)';
    warn.style.color = 'var(--red)';
    warn.textContent = `⚠ Somme (${sum}) > max (${total}) — config sera refusée`;
  } else {
    warn.style.display = 'block';
    warn.style.background = 'var(--green-dim)';
    warn.style.color = 'var(--green)';
    warn.textContent = `✓ Somme : ${sum} / ${total} tokens`;
  }
}

async function applyContextLimits() {
  if (!S.selected) return;
  const body = {};
  for (const f of ['total','system','history','rag','tools','user'])
    body[f] = parseInt(document.getElementById(`cr-${f}`).value);
  try {
    const d = await api(`/agents/${S.selected.name}/context-limits`, 'PUT', body);
    if (d.error) {
      document.getElementById('ctx-status').textContent = '❌ ' + d.error;
      if (d.current) loadAgentContextSliders(d.current);
    } else {
      updateTokenLimitsDisplay(body);
      const idx = S.agents.findIndex(a => a.name === S.selected.name);
      if (idx >= 0) S.agents[idx].context_limits = d.limits;
      S.selected.context_limits = d.limits;
      document.getElementById('ctx-status').textContent = '✅ Limites sauvegardées';
      setTimeout(() => document.getElementById('ctx-status').textContent = '', 2500);
    }
  } catch(e) {
    document.getElementById('ctx-status').textContent = '❌ ' + e.message;
  }
}

async function resetContextLimits() {
  const defaults = {total:3000,system:600,history:1000,rag:800,tools:300,user:300};
  loadAgentContextSliders(defaults);
  await applyContextLimits();
}

// ─── Sélection d'agent ─────────────────────────────────────────────────────
function toggleSidebarConfig() {
  const actions = document.getElementById('sfooter-actions');
  const arrow   = document.getElementById('sfooter-toggle-arrow');
  if (!actions) return;
  const open = actions.style.display !== 'none';
  actions.style.display = open ? 'none' : 'flex';
  if (arrow) arrow.textContent = open ? '▶' : '▼';
}

function toggleLudiqueFilter() {
  S.showLudique = !S.showLudique;
  const btn = document.getElementById('mode-filter-btn');
  btn.classList.toggle('ludique', S.showLudique);
  document.getElementById('mode-filter-icon').textContent = S.showLudique ? '🎭' : '🔧';
  document.getElementById('mode-filter-label').textContent = S.showLudique ? 'Ludiques' : 'Utiles';
  renderAgents();
}

function renderAgents() {
  const c = document.getElementById('aglist');
  if (!c) return;
  const filter = S.agentFilter.toLowerCase();
  let visible = S.agents.filter(a => {
    const isLudique = !!(a.in_salon || a.in_battle);
    if (S.showLudique !== isLudique) return false;
    return !filter || a.name.toLowerCase().includes(filter) || (a.role||'').toLowerCase().includes(filter);
  });
  if (S.tagFilter.size > 0)
    visible = visible.filter(a => [...S.tagFilter].every(t => (a.tags||[]).includes(t)));

  if (!visible.length) {
    c.innerHTML = (filter || S.tagFilter.size)
      ? `<div class="empty" style="padding:20px;font-size:12px;">Aucun résultat</div>`
      : `<div class="empty" style="padding:20px;font-size:12px;">Aucun agent. Crée-en un !</div>`;
    return;
  }

  c.innerHTML = visible.map(a => `
    <div class="acard ${S.selected?.name===a.name?'active':''}" onclick="selectAgent('${esc(a.name)}')" ontouchstart="">
      <button class="card-edit-btn" onclick="event.stopPropagation();openEditorForAgent('${esc(a.name)}')" ontouchstart="event.stopPropagation()" title="Modifier cet agent">✏</button>
      <div class="aname">${esc(a.name)}</div>
      ${a.message_count > 0 ? `<div class="amsg-count">${a.message_count} msg</div>` : ''}
      <div style="margin-top:4px;display:flex;gap:4px;flex-wrap:wrap;">
        <span class="badge bm">${esc(a.model)}</span>
        ${a.can_spawn  ? `<span class="badge bs">⛓spawn</span>`:''}
        ${a.in_salon   ? `<span class="badge" style="background:var(--purple-dim);color:var(--purple);">🎭 salon</span>`:''}
        ${a.in_battle  ? `<span class="badge" style="background:var(--red-dim);color:var(--red);">⚔️ battle</span>`:''}
        ${(a.tags||[]).map(t=>`<span class="badge btag">#${esc(t)}</span>`).join('')}
      </div>
    </div>`).join('');
}

function getAllTags() {
  const tags = new Set();
  S.agents.forEach(a => (a.tags||[]).forEach(t => tags.add(t)));
  return [...tags].sort();
}

function renderTagFilters() {
  const wrap = document.getElementById('tag-filters');
  if (!wrap) return;
  const tags = getAllTags();
  if (!tags.length) { wrap.innerHTML = ''; wrap.style.display = 'none'; return; }
  wrap.style.display = 'flex';
  wrap.innerHTML = tags.map(t =>
    `<button class="tag-filter-btn ${S.tagFilter.has(t)?'on':''}" onclick="toggleTagFilter('${esc(t)}')">#${esc(t)}</button>`
  ).join('');
}

function toggleTagFilter(tag) {
  if (S.tagFilter.has(tag)) S.tagFilter.delete(tag);
  else S.tagFilter.add(tag);
  renderTagFilters();
  renderAgents();
}

const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

async function selectAgent(name) {
  const agent = S.agents.find(a => a.name === name);
  if (!agent) return;

  S.selected = agent;
  S.wsId     = S.wsId || generateId();

  // Switcher vers le chat immédiatement, avant tout traitement async
  if (isMobile()) mobileTab('chat');

  connectWS();
  renderAgents();

  document.getElementById('atitle').textContent     = agent.name;
  document.getElementById('atitle').style.color     = 'var(--text)';
  document.getElementById('amodelpill').textContent = agent.model;
  document.getElementById('amodelpill').style.display = 'block';
  document.getElementById('aspawnpill').style.display = agent.can_spawn ? 'block' : 'none';
  document.getElementById('hdr-clear').style.display  = 'block';
  document.getElementById('msginput').disabled        = false;
  _setSendBtn('send');
  if (!isMobile()) document.getElementById('msginput').focus();

  renderTools(agent.allowed_tools || []);
  loadAgentContextSliders(agent.context_limits);

  clearMessages();
  await loadAgentSession(name);

  log('info', `✅ Agent sélectionné : ${name}`);
}

async function openEditorForAgent(name) {
  if (!S.selected || S.selected.name !== name) {
    const agent = S.agents.find(a => a.name === name);
    if (!agent) return;
    S.selected = agent;
    renderAgents();
    document.getElementById('atitle').textContent    = agent.name;
    document.getElementById('atitle').style.color    = 'var(--text)';
    document.getElementById('amodelpill').textContent = agent.model;
    document.getElementById('amodelpill').style.display = 'block';
    document.getElementById('aspawnpill').style.display = agent.can_spawn ? 'block' : 'none';
    document.getElementById('hdr-clear').style.display = 'block';
    renderTools(agent.allowed_tools || []);
    loadAgentContextSliders(agent.context_limits);
  }
  openEditor();
}

// ─── Mobile tabs ───────────────────────────────────────────────────────────
function toggleDebateConfig() {
  const el = document.getElementById('debate-config');
  const btn = document.getElementById('debate-config-toggle');
  el.classList.toggle('collapsed');
  if (btn) btn.textContent = el.classList.contains('collapsed') ? '▶' : '▼';
}
function toggleBattleConfig() {
  const el = document.getElementById('battle-config');
  const btn = document.getElementById('battle-config-toggle');
  el.classList.toggle('collapsed');
  if (btn) btn.textContent = el.classList.contains('collapsed') ? '▶' : '▼';
}

function mobileTab(tab) {
  const panelMap = { sidebar:'sidebar', chat:'chat', rpanel:'rpanel', salon:'debate-view', battle:'battle-view' };
  ['sidebar','chat','rpanel','debate-view','battle-view'].forEach(p =>
    document.getElementById(p)?.classList.remove('m-active'));
  const target = panelMap[tab];
  if (target) document.getElementById(target)?.classList.add('m-active');
  document.querySelectorAll('.mnav-btn').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.tab === tab));
}

// ─── Session persistante ───────────────────────────────────────────────────
async function loadAgentSession(agentName) {
  try {
    const d = await api(`/agents/${agentName}/session`);
    const messages = d.messages || [];
    if (messages.length === 0) {
      addSysMsg(`Agent <strong>${esc(agentName)}</strong> — modèle : <code>${esc(S.selected?.model)}</code>`);
      return;
    }
    addSysMsg(`Session restaurée — ${messages.length} message(s) précédents`);
    for (const m of messages) {
      if      (m.role === 'user')          addMsg('user', 'Vous', m.content, false);
      else if (m.role === 'assistant')     addMsg('agent', agentName, m.content, false);
      else if (m.role === 'partial')       addPartialMsg(m.agent || agentName, m.content, false);
      else if (m.role === 'spawn_request') addSpawnRequestMsg(m.from || agentName, m.to || '?', m.task || '', false);
      else if (m.role === 'sub_agent')     addSubAgentMsg(m.agent || '?', m.content, false);
    }
  } catch {}
}

// ─── Chat ──────────────────────────────────────────────────────────────────
function sendOrStop() {
  if (S.processing) stopAgent();
  else send();
}

function _setSendBtn(mode) {
  const btn = document.getElementById('sendbtn');
  if (!btn) return;
  if (mode === 'stop') {
    btn.textContent = '⏹ Stop';
    btn.classList.add('stop-mode');
    btn.disabled = false;
  } else {
    btn.textContent = 'Envoyer';
    btn.classList.remove('stop-mode');
    btn.disabled = !S.selected;
  }
}

async function stopAgent() {
  if (!S.selected) return;
  _setSendBtn('stopping');
  document.getElementById('sendbtn').disabled = true;
  try { await api(`/agents/${S.selected.name}/stop`, 'POST'); } catch(e) {}
}

async function send() {
  const input = document.getElementById('msginput');
  const msg   = input.value.trim();
  if (!msg || S.processing || !S.selected) return;

  S.processing = true;
  input.value  = '';
  input.style.height = '';
  _setSendBtn('stop');

  addMsg('user', 'Vous', msg);
  S.procId = addProc();
  switchTab('logs');
  log('info', `💬 "${msg.substring(0,60)}${msg.length>60?'...':''}"`);

  try {
    await api(`/agents/${S.selected.name}/chat`, 'POST', {
      message: msg, session_id: S.wsId
    });
  } catch(e) {
    removeProc(S.procId);
    addMsg('agent', S.selected.name, `❌ Erreur réseau : ${e.message}`);
    S.processing = false;
    _setSendBtn('send');
  }
}

// ─── WebSocket ─────────────────────────────────────────────────────────────
function connectWS() {
  if (!S.wsId) S.wsId = generateId();
  if (S.ws && S.ws.readyState === WebSocket.OPEN) return;
  if (S.ws) S.ws.close();
  const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  S.ws = new WebSocket(`${wsProto}//${location.host}/ws/${S.wsId}`);
  S.ws.onmessage = e => handleWS(JSON.parse(e.data));
  S.ws.onerror   = () => log('error', '❌ WebSocket error');
  S.ws.onclose   = () => {};
}

async function ensureWS() {
  if (!S.wsId) S.wsId = generateId();
  if (S.ws?.readyState === WebSocket.OPEN) return;
  connectWS();
  // Attendre que la connexion soit établie (max 3s)
  for (let i = 0; i < 60; i++) {
    if (S.ws?.readyState === WebSocket.OPEN) return;
    await new Promise(r => setTimeout(r, 50));
  }
}

function handleWS(ev) {
  const src = ev.source_agent;
  const isChild = src && S.selected && src !== S.selected.name;

  switch(ev.type) {
    case 'log':
      log(ev.data.level, ev.data.message);
      break;

    case 'token_update':
      updateTokens(ev.data);
      switchTab('tok');
      break;

    case 'tool_call':
      highlightTool(ev.data.name);
      if (isChild && S.currentSpawnId) {
        addToSpawnBlock(S.currentSpawnId, 'tool', `🔧 ${ev.data.name}(${JSON.stringify(ev.data.params).substring(0,60)})`);
      }
      break;

    case 'tool_result':
      setTimeout(() => highlightTool(null), 2000);
      break;

    case 'partial_response':
      if (isChild && S.currentSpawnId) {
        addToSpawnBlock(S.currentSpawnId, 'partial', ev.data.content);
      } else {
        removeProc(S.procId);
        addPartialMsg(ev.data.agent_name || S.selected?.name, ev.data.content);
        S.procId = addProc();
      }
      break;

    case 'spawn_event':
      break;

    case 'spawn_end':
      finalizeSpawnBlock(S.currentSpawnId, ev.data);
      S.currentSpawnId = null;
      break;

    case 'response':
      if (isChild) {
        if (S.currentSpawnId) addToSpawnBlock(S.currentSpawnId, 'response', ev.data.content);
      } else {
        removeProc(S.procId);
        addMsg('agent', S.selected?.name || 'Agent', ev.data.content);
      }
      break;

    case 'done':
      if (isChild) break; // ignorer les done des sous-agents
      S.processing = false;
      _setSendBtn('send');
      document.getElementById('msginput')?.focus();
      log('info', '──────────────────────────────────');
      loadAgents();
      if (S.selected) { clearMessages(); loadAgentSession(S.selected.name); }
      break;

    case 'debate_start':
      log('info', `🎭 Débat démarré — ${ev.data.turns} tour(s)`);
      break;

    case 'debate_thinking':
      addDebateThinking(ev.data.agent, ev.data.round);
      switchTab('tok');
      break;

    case 'debate_turn':
      addDebateMsg(ev.data.agent, ev.data.content, ev.data.round, !!ev.data.error);
      break;

    case 'battle_start':
      log('info', `⚔️ Battle Royale démarré — ${ev.data.agents?.length} agents`);
      break;

    case 'battle_phase':
      addBattlePhaseBanner(ev.data);
      break;

    case 'battle_thinking':
      addBattleThinking(ev.data.agent, ev.data.phase, ev.data.round);
      break;

    case 'battle_presentation':
      addBattleMsg(ev.data.agent, ev.data.content, 'presentation', !!ev.data.error);
      break;

    case 'battle_turn':
      addBattleMsg(ev.data.agent, ev.data.content, 'turn', !!ev.data.error);
      break;

    case 'battle_vote':
      addBattleVoteMsg(ev.data.agent, ev.data.target, ev.data.reason);
      break;

    case 'battle_elimination':
      addBattleElimination(ev.data);
      break;

    case 'battle_draw':
      addBattleDraw(ev.data.survivors);
      log('info', `🤝 Match nul — ${ev.data.survivors?.join(' & ')}`);
      break;

    case 'battle_winner':
      addBattleWinner(ev.data.winner);
      log('info', `🏆 ${ev.data.winner} remporte le Battle Royale !`);
      break;

    case 'battle_done':
      addBattleSysMsg(`✅ Battle terminé — ${ev.data.rounds} round(s)`);
      log('info', `⚔️ Battle terminé — ${ev.data.rounds} round(s)`);
      endBattle();
      break;

    case 'debate_vote_start':
      addDebateSysMsg('🗳️ Phase de vote — chaque agent rend son verdict...');
      log('info', '🗳️ Phase de vote démarrée');
      break;

    case 'debate_vote':
      addDebateVoteMsg(ev.data.agent, ev.data.vote, ev.data.reason);
      break;

    case 'debate_done':
      if (ev.data.votes) addDebateVoteTally(ev.data.votes);
      addDebateSysMsg(`✅ Débat terminé — ${ev.data.total_turns} intervention(s)`);
      log('info', `🎭 Débat terminé — ${ev.data.total_turns} intervention(s)`);
      endDebate();
      break;
  }

  if (isChild && ev.type === 'token_update' && !S.currentSpawnId) {
    S.currentSpawnId = openSpawnBlock(src, 1);
  }
}

// ─── Tokens ────────────────────────────────────────────────────────────────
function updateTokens(d) {
  const tt = document.getElementById('tt');
  if (!tt) return;
  tt.textContent = d.total;
  document.getElementById('tm').textContent = d.max;
  const pct   = Math.min(100, d.percent || 0);
  const gauge = document.getElementById('tg');
  gauge.style.width           = `${pct}%`;
  gauge.style.backgroundColor = pct>90?'var(--red)':pct>75?'var(--amber)':'var(--accent)';

  const lims = d.limits || {};
  const pairs = [
    ['ts','tvs','system',  lims.system  || 600],
    ['th','tvh','history', lims.history || 1000],
    ['tr','tvr','rag',     lims.rag     || 800],
    ['tt2','tvt','tools',  lims.tools   || 300],
    ['tu','tvu','user',    lims.user    || 300],
  ];
  for (const [barid, valid, key, lim] of pairs) {
    const val = d[key] || 0;
    document.getElementById(barid).style.width  = `${Math.min(100,(val/lim)*100)}%`;
    document.getElementById(valid).textContent  = val;
    updateTokenLimitsDisplay(lims);
  }
}

// ─── Messages ──────────────────────────────────────────────────────────────
function clearMessages() {
  const c = document.getElementById('msgs');
  if (!c) return;
  c.innerHTML = '';
  S.spawnBlocks    = {};
  S.currentSpawnId = null;
}

function addMsg(role, author, content, animate=true) {
  const c  = document.getElementById('msgs');
  if (!c) return;
  c.querySelector('.empty')?.remove();
  const el = document.createElement('div');
  el.className = 'msg';
  if (!animate) el.style.animation = 'none';
  el.innerHTML = `
    <div class="av av-${role==='user'?'u':'a'}">${role==='user'?'U':esc(author.charAt(0).toUpperCase())}</div>
    <div class="mbody">
      <div class="mauthor">${esc(author)}</div>
      <div class="mtext">${esc(content)}</div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addPartialMsg(author, content, animate=true) {
  const c  = document.getElementById('msgs');
  if (!c) return;
  c.querySelector('.empty')?.remove();
  const el = document.createElement('div');
  el.className = 'msg';
  if (!animate) el.style.animation = 'none';
  el.innerHTML = `
    <div class="av av-p">~</div>
    <div class="mbody">
      <div class="mauthor">${esc(author)} <span class="partial-badge">message intermédiaire</span></div>
      <div class="mtext">${esc(content)}</div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addSpawnRequestMsg(from, to, task, animate=true) {
  const c  = document.getElementById('msgs');
  if (!c) return;
  c.querySelector('.empty')?.remove();
  const el = document.createElement('div');
  el.className = 'msg';
  if (!animate) el.style.animation = 'none';
  el.innerHTML = `
    <div class="av av-s" style="font-size:11px;">⛓</div>
    <div class="mbody">
      <div class="mauthor" style="color:var(--amber);">
        ${esc(from)} → ${esc(to)}
        <span style="font-size:10px;opacity:.6;font-weight:400;">délégation</span>
      </div>
      <div class="mtext" style="font-size:12px;color:var(--muted);border-left:2px solid var(--amber);padding-left:8px;margin-top:4px;">${esc(task)}</div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addSubAgentMsg(agent, content, animate=true) {
  const c  = document.getElementById('msgs');
  if (!c) return;
  c.querySelector('.empty')?.remove();
  const el = document.createElement('div');
  el.className = 'msg';
  if (!animate) el.style.animation = 'none';
  el.innerHTML = `
    <div class="av av-s">${esc(agent.charAt(0).toUpperCase())}</div>
    <div class="mbody">
      <div class="mauthor" style="color:var(--amber);">🌿 ${esc(agent)} <span style="font-size:10px;opacity:.6;font-weight:400;">sous-agent</span></div>
      <div class="mtext" style="font-size:13px;">${esc(content)}</div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addSysMsg(html) {
  const c  = document.getElementById('msgs');
  if (!c) return;
  c.querySelector('.empty')?.remove();
  const el = document.createElement('div');
  el.style.cssText = 'padding:6px 16px;font-size:12px;color:var(--muted);border-left:2px solid var(--border);margin:2px 0;';
  el.innerHTML = html;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addProc() {
  const id = `proc-${Date.now()}`;
  const c  = document.getElementById('msgs');
  if (!c) return null;
  const el = document.createElement('div');
  el.id = id; el.className = 'msg';
  el.innerHTML = `<div class="av av-a">...</div><div class="mbody"><div class="mauthor">${esc(S.selected?.name||'Agent')}</div><div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div></div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
  return id;
}
function removeProc(id) { document.getElementById(id)?.remove(); }

// ─── Spawn blocks ──────────────────────────────────────────────────────────
function openSpawnBlock(childName, depth) {
  const id = `sb-${childName}-${Date.now()}`;
  const c  = document.getElementById('msgs');
  c.querySelector('.empty')?.remove();

  const el = document.createElement('div');
  el.id = id;
  el.className = 'spawn-block';
  el.innerHTML = `
    <div class="spawn-block-hdr">
      <span>🌿</span>
      <strong>${esc(childName)}</strong>
      <span style="font-size:10px;opacity:.6;font-weight:400;">sous-agent</span>
      <span class="spawn-depth">profondeur ${depth || 1}</span>
    </div>
    <div class="spawn-block-body" id="${id}-body">
      <div class="dots"><div class="dot" style="background:var(--amber);"></div><div class="dot" style="background:var(--amber);"></div><div class="dot" style="background:var(--amber);"></div></div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
  S.spawnBlocks[id] = el;
  return id;
}

function addToSpawnBlock(id, type, content) {
  const body = document.getElementById(`${id}-body`);
  if (!body) return;
  body.querySelector('.dots')?.remove();
  const icons = { tool: '🔧', response: '💬', partial: '💭', log: '·' };
  const cls   = { tool: 'tool', response: 'response', partial: 'partial', log: 'log' };
  const el = document.createElement('div');
  el.className = `sub-event ${cls[type]||'log'}`;
  el.innerHTML = `<div class="sub-event-icon">${icons[type]||'·'}</div><div class="sub-event-content">${esc(content)}</div>`;
  body.appendChild(el);
  const msgsEl = document.getElementById('msgs');
  if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;
}

function finalizeSpawnBlock(id, data) {
  if (!id) return;
  const body = document.getElementById(`${id}-body`);
  if (!body) return;
  body.querySelector('.dots')?.remove();
  const el = document.createElement('div');
  el.style.cssText = `margin-top:8px;padding-top:8px;border-top:1px solid rgba(210,153,34,.2);font-size:12px;color:${data.success?'var(--green)':'var(--red)'};`;
  el.textContent = data.success ? `✅ Terminé` : `❌ Erreur : ${data.error || '?'}`;
  body.appendChild(el);
  const msgs = document.getElementById('msgs');
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

// ─── Tools ─────────────────────────────────────────────────────────────────
function renderTools(allowed) {
  const c = document.getElementById('toolslist');
  if (!c) return;
  c.innerHTML = Object.entries(S.allTools).map(([name, t]) => {
    const on = allowed.includes(name);
    return `<div class="tool-item ${on?'':'disabled'}" id="tool-${name}">
      <div class="tname">${esc(name)}() ${on?'':'<span style="font-size:10px;color:var(--muted);">désactivé</span>'}</div>
      <div class="tdesc">${esc(t.function.description)}</div>
    </div>`;
  }).join('');
}

function highlightTool(name) {
  document.querySelectorAll('.tool-item').forEach(e=>e.classList.remove('active'));
  if (name) {
    const el = document.getElementById(`tool-${name}`);
    if (el) { el.classList.add('active'); el.scrollIntoView({behavior:'smooth',block:'nearest'}); }
  }
}

// ─── Tabs ──────────────────────────────────────────────────────────────────
function switchTab(name) {
  const names = ['tok','logs','tools','ctx'];
  document.querySelectorAll('.tab').forEach((el,i)=>el.classList.toggle('active',names[i]===name));
  document.querySelectorAll('.tpane').forEach(el=>el.classList.remove('active'));
  document.getElementById(`tp-${name}`)?.classList.add('active');
}

// ─── Logs ──────────────────────────────────────────────────────────────────
function log(level, message) {
  const c  = document.getElementById('logscont');
  const now = new Date();
  const ts  = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;
  const el  = document.createElement('div');
  el.className = `lentry l-${level}`;
  el.innerHTML = `<span class="lts">${ts}</span>${esc(message)}`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}
function clearLogs() { document.getElementById('logscont').innerHTML=''; }

// ─── Session ───────────────────────────────────────────────────────────────
async function clearAgentSession() {
  if (!S.selected) return;
  await api(`/agents/${S.selected.name}/session`, 'DELETE').catch(()=>{});
  clearMessages();
  clearLogs();
  addSysMsg(`Conversation de <strong>${esc(S.selected.name)}</strong> effacée.`);
  loadAgents();
}

// ─── Input ─────────────────────────────────────────────────────────────────
function setupInput() {
  const input = document.getElementById('msginput');
  input.addEventListener('keydown', e=>{ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();} });
  input.addEventListener('input',   ()=>{ input.style.height=''; input.style.height=Math.min(input.scrollHeight,120)+'px'; });
}

// ─── Éditeur ───────────────────────────────────────────────────────────────
async function openEditor() {
  if (!S.selected) return;
  const d = await api(`/agents/${S.selected.name}`);
  document.getElementById('ed-md').value       = d.raw_markdown || '';
  document.getElementById('ec-temp').value     = d.config?.temperature ?? 0.7;
  document.getElementById('ec-tv').textContent = d.config?.temperature ?? 0.7;
  document.getElementById('ec-tok').value      = d.config?.max_tokens || 512;
  document.getElementById('ec-iter').value     = d.config?.max_iterations || 5;
  document.getElementById('sp-toggle').classList.toggle('on', !!d.config?.can_spawn);
  const isLudique = !!(d.config?.in_salon || d.config?.in_battle);
  document.getElementById('ludique-toggle').classList.toggle('on', isLudique);

  // Populate provider select
  const providerSel = document.getElementById('ec-provider');
  providerSel.innerHTML = '<option value="">— Choisir un provider —</option>' +
    Object.entries(S.providers).map(([id, p]) =>
      `<option value="${esc(id)}">${esc(p.label || id)}</option>`
    ).join('');
  const savedProvider = d.config?.provider_id || '';
  providerSel.value = savedProvider;

  // Populate model datalist from provider
  populateModelDatalist(savedProvider);
  document.getElementById('ec-model').value = d.config?.model || '';

  const allowed = d.config?.allowed_tools || [];
  const descs = {
    read_file:        'Lire des fichiers',
    write_file:       'Écrire des fichiers',
    list_directory:   'Lister des fichiers',
    search_knowledge: 'Recherche sémantique KB partagée',
    write_knowledge:  'Archiver dans la KB partagée (auto-indexé)',
    spawn_agent:      'Déléguer à un sous-agent',
    ssh_exec:         'SSH : exécuter une commande distante',
    ssh_read_file:    'SSH : lire un fichier distant',
    process_status:   'SSH : statut d\'un processus',
    process_wait:     'SSH : attendre la fin d\'un processus',
  };
  document.getElementById('ed-toggles').innerHTML = Object.keys(S.allTools).map(n => `
    <div class="ttoggle ${allowed.includes(n)?'on':''}" id="tg-${n}" onclick="toggleTool('${n}')">
      <div class="tcheck">${allowed.includes(n)?'✓':''}</div>
      <div class="ttn">${esc(n)}()</div>
      <div class="ttd">${esc(descs[n]||'')}</div>
    </div>`).join('');

  // Spawnable agents multi-select
  const savedSpawnable = d.config?.spawnable_agents || [];
  const spawnSection   = document.getElementById('ed-spawnable-section');
  const spawnWrap      = document.getElementById('ed-spawnable-wrap');
  const otherAgents    = S.agents.map(a => a.name).filter(n => n !== S.selected.name);
  if (spawnSection) spawnSection.style.display = (!!d.config?.can_spawn && otherAgents.length) ? 'block' : 'none';
  if (spawnWrap) {
    spawnWrap.innerHTML = otherAgents.length === 0
      ? '<span style="font-size:12px;color:var(--muted);">Aucun autre agent disponible</span>'
      : otherAgents.map(n => `
        <div class="ttoggle ${savedSpawnable.includes(n)?'on':''}" id="spa-${n}" onclick="toggleSpawnable('${n}')" style="padding:5px 10px;">
          <div class="tcheck">${savedSpawnable.includes(n)?'✓':''}</div>
          <div class="ttn" style="font-size:12px;">${esc(n)}</div>
        </div>`).join('');
  }

  renderEditorTags(d.config?.tags || []);

  document.getElementById('ed-title').textContent = `Modifier : ${S.selected.name}`;
  document.getElementById('ed-overlay').classList.add('open');
  switchEtab('prompt');
}
function closeEditor() { document.getElementById('ed-overlay').classList.remove('open'); }

function switchEtab(name) {
  const ns = ['prompt','config','tools'];
  document.querySelectorAll('.etab').forEach((el,i)=>el.classList.toggle('active',ns[i]===name));
  ns.forEach(n=>{ const el=document.getElementById(`etab-${n}`); if(el)el.style.display=n===name?'block':'none'; });
}
function toggleTool(n) {
  const el=document.getElementById(`tg-${n}`);
  const on=el.classList.toggle('on');
  el.querySelector('.tcheck').textContent=on?'✓':'';
}
function toggleSpawn() {
  document.getElementById('sp-toggle').classList.toggle('on');
  const on      = document.getElementById('sp-toggle').classList.contains('on');
  const section = document.getElementById('ed-spawnable-section');
  if (section) section.style.display = on && document.querySelectorAll('#ed-spawnable-wrap .ttoggle').length ? 'block' : 'none';
}
function toggleSpawnable(n) {
  const el = document.getElementById(`spa-${n}`);
  if (!el) return;
  const on = el.classList.toggle('on');
  el.querySelector('.tcheck').textContent = on ? '✓' : '';
}

function renderEditorTags(tags) {
  const wrap = document.getElementById('ed-tags-wrap');
  if (!wrap) return;
  wrap.innerHTML = tags.length
    ? tags.map(t => `<span class="ed-tag">${esc(t)}<button type="button" class="ed-tag-rm" onclick="removeEditorTag('${esc(t)}')">×</button></span>`).join('')
    : `<span style="font-size:12px;color:var(--muted);">Aucun tag</span>`;
}

function getEditorTags() {
  const wrap = document.getElementById('ed-tags-wrap');
  if (!wrap) return [];
  return [...wrap.querySelectorAll('.ed-tag')].map(el => el.firstChild.textContent.trim());
}

function addEditorTag() {
  const input = document.getElementById('ed-tag-input');
  const val = input.value.trim().toLowerCase().replace(/\s+/g, '_');
  if (!val) return;
  const existing = getEditorTags();
  if (!existing.includes(val)) renderEditorTags([...existing, val]);
  input.value = '';
  input.focus();
}

function removeEditorTag(tag) {
  renderEditorTags(getEditorTags().filter(t => t !== tag));
}

async function saveAgent() {
  if (!S.selected) return;
  const name            = S.selected.name;
  const canSpawn        = document.getElementById('sp-toggle').classList.contains('on');
  let tools = [...document.querySelectorAll('#ed-toggles .ttoggle.on')].map(el=>el.id.replace('tg-',''));
  if (canSpawn&&!tools.includes('spawn_agent')) tools.push('spawn_agent');
  if (!canSpawn) tools=tools.filter(t=>t!=='spawn_agent');
  const spawnableAgents = [...document.querySelectorAll('#ed-spawnable-wrap .ttoggle.on')].map(el=>el.id.replace('spa-',''));
  const tags            = getEditorTags();
  const ludique         = document.getElementById('ludique-toggle').classList.contains('on');
  const inSalon         = ludique;
  const inBattle        = ludique;
  try {
    await api(`/agents/${name}/markdown`,'PUT',{content:document.getElementById('ed-md').value});
    await api(`/agents/${name}/config`,'PUT',{
      provider_id:document.getElementById('ec-provider').value,
      model:document.getElementById('ec-model').value,
      temperature:parseFloat(document.getElementById('ec-temp').value),
      max_tokens:parseInt(document.getElementById('ec-tok').value),
      max_iterations:parseInt(document.getElementById('ec-iter').value),
      allowed_tools:tools, can_spawn:canSpawn, spawnable_agents:spawnableAgents, tags,
      in_salon:inSalon, in_battle:inBattle,
    });
    closeEditor();
    await loadAgents();
    const updated = S.agents.find(a=>a.name===name);
    if (updated) {
      S.selected = updated;
      renderTools(updated.allowed_tools||[]);
      document.getElementById('aspawnpill').style.display = updated.can_spawn?'block':'none';
    }
    log('info', `💾 Agent ${name} sauvegardé`);
  } catch(e) { log('error', `❌ ${e.message}`); }
}

async function deleteAgent() {
  if (!S.selected) return;
  if (!confirm(`Supprimer définitivement "${S.selected.name}" ?`)) return;
  await api(`/agents/${S.selected.name}`,'DELETE');
  S.selected = null;
  closeEditor();
  document.getElementById('atitle').textContent = 'Sélectionne un agent →';
  document.getElementById('atitle').style.color = 'var(--muted)';
  ['amodelpill','aspawnpill','hdr-clear'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  document.getElementById('msginput').disabled = true;
  document.getElementById('sendbtn').disabled  = true;
  document.getElementById('ctx-no-agent').style.display  = 'block';
  document.getElementById('ctx-settings').style.display  = 'none';
  document.getElementById('ctx-agent-name').textContent   = 'aucun agent';
  clearMessages();
  await loadAgents();
}

// ─── Create modal ──────────────────────────────────────────────────────────
function openCreate() {
  document.getElementById('new-name').value = '';
  document.getElementById('cr-overlay').classList.add('open');
  setTimeout(() => document.getElementById('new-name').focus(), 100);
}
function closeCreate() { document.getElementById('cr-overlay').classList.remove('open'); }

async function confirmCreate() {
  const name = document.getElementById('new-name').value.trim();
  if (!name) return;
  const btn  = document.querySelector('#cr-overlay .btnp');
  const orig = btn.textContent;
  btn.textContent = '⏳ Création...';
  btn.disabled    = true;
  try {
    const d = await api('/agents','POST',{name});
    if (d.error) { alert(d.error); return; }
    closeCreate();
    await loadAgents();
    await selectAgent(d.name);
    openEditor();
  } finally {
    btn.textContent = orig;
    btn.disabled    = false;
  }
}

// ─── Salon de débat ────────────────────────────────────────────────────────

function switchMode(mode) {
  const newMode = (S.mode === mode) ? 'chat' : mode;
  if (newMode === S.mode) return;
  S.mode = newMode;

  if (_currentView) _currentView.teardown();
  const views = { chat: ChatView, debate: SalonView, battle: BattleView };
  _currentView = views[S.mode] || ChatView;
  _currentView.mount();

  document.getElementById('hdr-home')?.classList.toggle('home-active',    S.mode === 'chat');
  document.getElementById('hdr-salon')?.classList.toggle('salon-active',  S.mode === 'debate');
  document.getElementById('hdr-battle')?.classList.toggle('battle-active', S.mode === 'battle');

  const activeTab = S.mode === 'debate' ? 'salon' : S.mode === 'battle' ? 'battle' : 'chat';
  document.querySelectorAll('.mnav-btn').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.tab === activeTab));
  if (isMobile()) mobileTab(activeTab);
}

function renderDebateAgents() {
  const wrap = document.getElementById('debate-agents-wrap');
  if (!wrap) return;
  const hasSalon   = S.agents.some(a => a.in_salon);
  const candidates = hasSalon ? S.agents.filter(a => a.in_salon) : S.agents;
  if (!candidates.length) {
    wrap.innerHTML = '<span style="font-size:12px;color:var(--muted);">Aucun agent avec le tag "salon".</span>';
    return;
  }
  wrap.innerHTML = candidates.map(a => `
    <div class="debate-agent-tag ${S.debateAgents.has(a.name) ? 'on' : ''}"
      onclick="toggleDebateAgent('${esc(a.name)}')">${esc(a.name)}</div>
  `).join('');
}

function toggleDebateAgent(name) {
  if (S.debating) return;
  if (S.debateAgents.has(name)) S.debateAgents.delete(name);
  else S.debateAgents.add(name);
  renderDebateAgents();
}

async function launchDebate() {
  const topic = document.getElementById('debate-topic').value.trim();
  const turns = parseInt(document.getElementById('debate-turns').value);
  const agents = [...S.debateAgents];

  if (!topic)          return alert('Saisis un sujet de débat.');
  if (agents.length < 2) return alert('Sélectionne au moins 2 agents.');

  S.debating = true;
  S.debateId = null;
  Object.keys(_debateColorMap).forEach(k => delete _debateColorMap[k]); // reset couleurs

  document.getElementById('debate-launch-btn').style.display = 'none';
  document.getElementById('debate-stop-btn').style.display   = 'block';
  document.getElementById('debate-topic').disabled    = true;
  document.getElementById('debate-turns').disabled    = true;
  document.getElementById('debate-vote-toggle').disabled = true;
  document.querySelectorAll('.debate-agent-tag').forEach(el => el.style.opacity = '.5');

  document.getElementById('debate-msgs').innerHTML = '';
  addDebateSysMsg(`Débat démarré — "${esc(topic)}" — ${turns} tour(s) × ${agents.length} agents`);

  switchTab('logs');
  await ensureWS();

  const forceVote = document.getElementById('debate-vote-toggle')?.checked || false;
  try {
    const d = await api('/debate', 'POST', { topic, agents, turns, session_id: S.wsId, force_vote: forceVote });
    if (d.error) { endDebate(); alert(d.error); return; }
    S.debateId = d.debate_id;
  } catch(e) {
    endDebate();
    alert('Erreur réseau : ' + e.message);
  }
}

async function stopDebate() {
  if (!S.debateId) return;
  await api(`/debate/${S.debateId}/stop`, 'POST').catch(() => {});
}

function endDebate() {
  S.debating = false;
  document.getElementById('debate-launch-btn').style.display = 'block';
  document.getElementById('debate-stop-btn').style.display   = 'none';
  document.getElementById('debate-topic').disabled    = false;
  document.getElementById('debate-turns').disabled    = false;
  document.getElementById('debate-vote-toggle').disabled = false;
  document.querySelectorAll('.debate-agent-tag').forEach(el => el.style.opacity = '');
  if (S.debateThinkingEl) { S.debateThinkingEl.remove(); S.debateThinkingEl = null; }
}

function addDebateMsg(agentName, content, round, isError = false) {
  if (S.debateThinkingEl) { S.debateThinkingEl.remove(); S.debateThinkingEl = null; }
  const c  = document.getElementById('debate-msgs');
  const col = debateColor(agentName);
  const el = document.createElement('div');
  el.className = 'debate-msg';
  el.innerHTML = `
    <div class="debate-av" style="background:${col.bg};color:${col.fg};">${esc(agentName.charAt(0).toUpperCase())}</div>
    <div class="debate-body">
      <div class="debate-author" style="color:${col.fg};">
        ${esc(agentName)} <span class="debate-round">tour ${round}</span>
      </div>
      <div class="debate-text" style="${isError ? 'color:var(--red);' : ''}">${esc(content)}</div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addDebateThinking(agentName, round) {
  if (S.debateThinkingEl) { S.debateThinkingEl.remove(); S.debateThinkingEl = null; }
  const c   = document.getElementById('debate-msgs');
  const col = debateColor(agentName);
  const el  = document.createElement('div');
  el.className = 'debate-thinking';
  const roundLabel = round === 'vote' ? '🗳 vote' : `tour ${round}`;
  el.innerHTML = `
    <div class="debate-av" style="background:${col.bg};color:${col.fg};">${esc(agentName.charAt(0).toUpperCase())}</div>
    <div style="font-size:12px;color:var(--muted);">${esc(agentName)} — ${roundLabel}</div>
    <div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
  S.debateThinkingEl = el;
}

function addDebateSysMsg(html) {
  const c  = document.getElementById('debate-msgs');
  const el = document.createElement('div');
  el.style.cssText = 'padding:4px 0;font-size:12px;color:var(--muted);border-left:2px solid var(--border);padding-left:10px;';
  el.innerHTML = html;
  c.appendChild(el);
}

function addDebateVoteMsg(agentName, vote, reason) {
  if (S.debateThinkingEl) { S.debateThinkingEl.remove(); S.debateThinkingEl = null; }
  const c   = document.getElementById('debate-msgs');
  const col = debateColor(agentName);
  const voteColor = vote === 'POUR' ? 'var(--green)' : vote === 'CONTRE' ? 'var(--red)' : 'var(--muted)';
  const voteBg    = vote === 'POUR' ? 'var(--green-dim)' : vote === 'CONTRE' ? 'var(--red-dim)' : 'var(--bg3)';
  const el = document.createElement('div');
  el.className = 'debate-msg';
  el.innerHTML = `
    <div class="debate-av" style="background:${col.bg};color:${col.fg};">${esc(agentName.charAt(0).toUpperCase())}</div>
    <div class="debate-body">
      <div class="debate-author" style="color:${col.fg};">
        ${esc(agentName)}
        <span class="vote-badge" style="background:${voteBg};color:${voteColor};border:1px solid ${voteColor};">🗳 ${esc(vote)}</span>
      </div>
      <div class="debate-text">${esc(reason)}</div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addDebateVoteTally(votes) {
  const entries = Object.entries(votes);
  const pour    = entries.filter(([,v]) => v === 'POUR').map(([n]) => n);
  const contre  = entries.filter(([,v]) => v === 'CONTRE').map(([n]) => n);
  const indet   = entries.filter(([,v]) => v !== 'POUR' && v !== 'CONTRE').map(([n]) => n);
  const c  = document.getElementById('debate-msgs');
  const el = document.createElement('div');
  el.className = 'debate-tally';
  el.innerHTML = `
    <div class="tally-title">📊 Résultat du vote</div>
    <div class="tally-scores">
      <span class="tally-pour">✅ POUR : ${pour.length}</span>
      <span class="tally-contre">❌ CONTRE : ${contre.length}</span>
      ${indet.length ? `<span class="tally-indet">❓ Indéterminé : ${indet.length}</span>` : ''}
    </div>
    <div class="tally-detail">
      ${pour.map(n   => `<span style="color:var(--green);font-size:11px;font-family:var(--mono);">✅ ${esc(n)}</span>`).join('')}
      ${contre.map(n => `<span style="color:var(--red);font-size:11px;font-family:var(--mono);">❌ ${esc(n)}</span>`).join('')}
      ${indet.map(n  => `<span style="color:var(--muted);font-size:11px;font-family:var(--mono);">❓ ${esc(n)}</span>`).join('')}
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

// ─── Battle Royale ─────────────────────────────────────────────────────────

// Palette partagée avec le débat pour la cohérence visuelle
function battleColor(name) { return debateColor(name); }

function renderBattleAgents() {
  const wrap = document.getElementById('battle-agents-wrap');
  if (!wrap) return;
  const hasBattle  = S.agents.some(a => a.in_battle);
  const candidates = hasBattle ? S.agents.filter(a => a.in_battle) : S.agents;
  wrap.innerHTML = candidates.map(a => {
    const elim = S.battleEliminated.has(a.name);
    return `<div class="battle-agent-tag ${S.battleAgents.has(a.name)?'on':''} ${elim?'eliminated':''}"
      onclick="toggleBattleAgent('${esc(a.name)}')">${esc(a.name)}</div>`;
  }).join('');
}

function toggleBattleAgent(name) {
  if (S.battling || S.battleEliminated.has(name)) return;
  if (S.battleAgents.has(name)) S.battleAgents.delete(name);
  else S.battleAgents.add(name);
  renderBattleAgents();
}

async function launchBattle() {
  const agents = [...S.battleAgents];
  if (agents.length < 3) return alert('Sélectionne au moins 3 agents.');

  S.battling = true;
  S.battleId = null;
  S.battleEliminated.clear();
  Object.keys(_debateColorMap).forEach(k => delete _debateColorMap[k]);

  document.getElementById('battle-launch-btn').style.display = 'none';
  document.getElementById('battle-stop-btn').style.display   = 'block';
  document.querySelectorAll('.battle-agent-tag').forEach(el => el.style.pointerEvents = 'none');

  document.getElementById('battle-msgs').innerHTML = '';
  addBattleSysMsg(`⚔️ Battle Royale — ${agents.length} agents`);
  switchTab('logs');
  await ensureWS();

  try {
    const d = await api('/battle', 'POST', { agents, session_id: S.wsId });
    if (d.error) { endBattle(); alert(d.error); return; }
    S.battleId = d.battle_id;
  } catch(e) {
    endBattle();
    alert('Erreur réseau : ' + e.message);
  }
}

async function stopBattle() {
  if (!S.battleId) return;
  await api(`/battle/${S.battleId}/stop`, 'POST').catch(() => {});
}

function endBattle() {
  S.battling = false;
  S.battleEliminated.clear();
  S.battleAgents.clear();
  document.getElementById('battle-launch-btn').style.display = 'block';
  document.getElementById('battle-stop-btn').style.display   = 'none';
  if (S.battleThinkingEl) { S.battleThinkingEl.remove(); S.battleThinkingEl = null; }
  renderBattleAgents();
}

function addBattlePhaseBanner(data) {
  if (S.battleThinkingEl) { S.battleThinkingEl.remove(); S.battleThinkingEl = null; }
  const c  = document.getElementById('battle-msgs');
  const el = document.createElement('div');
  const voteLabel = data.is_final
    ? `🗳️ Duel final — Vote (les agents peuvent voter pour eux-mêmes pour un match nul)`
    : `🗳️ Round ${data.round} — Vote d'élimination`;
  const labels = {
    presentation: '🎤 Présentations',
    turn: `⚔️ Round ${data.round} — Tours de parole`,
    vote: voteLabel,
  };
  el.className = `battle-phase-banner ${data.phase}${data.is_final ? ' final' : ''}`;
  el.textContent = labels[data.phase] || data.phase;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addBattleThinking(agentName, phase, round) {
  if (S.battleThinkingEl) { S.battleThinkingEl.remove(); S.battleThinkingEl = null; }
  const c   = document.getElementById('battle-msgs');
  const col = battleColor(agentName);
  const el  = document.createElement('div');
  el.className = 'battle-thinking';
  const phaseLabel = phase === 'vote' ? '🗳 vote' : phase === 'presentation' ? '🎤 présentation' : `⚔️ round ${round}`;
  el.innerHTML = `
    <div class="battle-av" style="background:${col.bg};color:${col.fg};">${esc(agentName.charAt(0).toUpperCase())}</div>
    <div style="font-size:12px;color:var(--muted);">${esc(agentName)} — ${phaseLabel}</div>
    <div class="dots"><div class="dot" style="background:var(--red);"></div><div class="dot" style="background:var(--red);"></div><div class="dot" style="background:var(--red);"></div></div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
  S.battleThinkingEl = el;
}

function addBattleMsg(agentName, content, phase, isError = false) {
  if (S.battleThinkingEl) { S.battleThinkingEl.remove(); S.battleThinkingEl = null; }
  const c   = document.getElementById('battle-msgs');
  const col = battleColor(agentName);
  const badgeLabel = phase === 'presentation' ? '🎤 présentation' : null;
  const el  = document.createElement('div');
  el.className = 'battle-msg';
  el.innerHTML = `
    <div class="battle-av" style="background:${col.bg};color:${col.fg};">${esc(agentName.charAt(0).toUpperCase())}</div>
    <div class="battle-body">
      <div class="battle-author" style="color:${col.fg};">
        ${esc(agentName)}
        ${badgeLabel ? `<span class="battle-badge" style="background:${col.bg};color:${col.fg};border-color:${col.fg};">${badgeLabel}</span>` : ''}
      </div>
      <div class="battle-text" style="${isError?'color:var(--red);':''}">${esc(content)}</div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addBattleVoteMsg(agentName, target, reason) {
  if (S.battleThinkingEl) { S.battleThinkingEl.remove(); S.battleThinkingEl = null; }
  const c   = document.getElementById('battle-msgs');
  const col = battleColor(agentName);
  const el  = document.createElement('div');
  el.className = 'battle-msg';
  el.innerHTML = `
    <div class="battle-av" style="background:${col.bg};color:${col.fg};">${esc(agentName.charAt(0).toUpperCase())}</div>
    <div class="battle-body">
      <div class="battle-author" style="color:${col.fg};">
        ${esc(agentName)}
        <span class="battle-badge" style="background:var(--red-dim);color:var(--red);border-color:var(--red);">💀 élimine ${esc(target||'?')}</span>
      </div>
      <div class="battle-text" style="font-size:12px;color:var(--muted);">${esc(reason)}</div>
    </div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addBattleElimination(data) {
  if (S.battleThinkingEl) { S.battleThinkingEl.remove(); S.battleThinkingEl = null; }
  S.battleEliminated.add(data.eliminated);
  renderBattleAgents();

  const c  = document.getElementById('battle-msgs');
  const el = document.createElement('div');
  el.className = 'battle-elim';

  const tallyStr = Object.entries(data.tally||{})
    .sort(([,a],[,b]) => b-a)
    .map(([n,v]) => `${esc(n)} ×${v}`)
    .join('  ·  ');

  el.innerHTML = `
    <div class="battle-elim-title">
      💀 ${esc(data.eliminated)} est éliminé${data.random ? ' <span style="font-size:11px;font-weight:400;">(égalité — tirage aléatoire)</span>' : ''}
    </div>
    ${tallyStr ? `<div class="battle-elim-tally">${tallyStr}</div>` : ''}
    <div style="font-size:11px;color:var(--muted);margin-top:6px;">Survivants : ${(data.survivors||[]).map(n=>esc(n)).join(', ')}</div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addBattleDraw(survivors) {
  const c  = document.getElementById('battle-msgs');
  const el = document.createElement('div');
  el.className = 'battle-draw';
  el.innerHTML = `
    <div class="battle-draw-title">🤝</div>
    <div class="battle-draw-names">${(survivors||[]).map(n=>esc(n)).join(' & ')}</div>
    <div style="font-size:12px;color:var(--muted);margin-top:4px;">Ont choisi la collaboration — ils survivent tous les deux.</div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addBattleWinner(name) {
  const c   = document.getElementById('battle-msgs');
  const col = battleColor(name);
  const el  = document.createElement('div');
  el.className = 'battle-winner';
  el.innerHTML = `
    <div class="battle-winner-title">🏆</div>
    <div class="battle-winner-name">${esc(name)}</div>
    <div style="font-size:12px;color:var(--muted);margin-top:4px;">remporte le Battle Royale !</div>`;
  c.appendChild(el);
  c.scrollTop = c.scrollHeight;
}

function addBattleSysMsg(html) {
  const c  = document.getElementById('battle-msgs');
  const el = document.createElement('div');
  el.style.cssText = 'padding:4px 0;font-size:12px;color:var(--muted);border-left:2px solid var(--border);padding-left:10px;';
  el.innerHTML = html;
  c.appendChild(el);
}

// ─── Providers ─────────────────────────────────────────────────────────────

const _pfModels = [];   // modèles en cours d'édition dans le formulaire provider

async function loadProviders() {
  try {
    const d = await api('/providers');
    S.providers = d.providers || {};
  } catch { S.providers = {}; }
}

async function openProvidersModal() {
  document.getElementById('providers-overlay').classList.add('open');
  await loadProviders();
  renderProvidersList();
  _pfModels.length = 0;
  renderPfModels();
}
function closeProvidersModal() { document.getElementById('providers-overlay').classList.remove('open'); }

function renderProvidersList() {
  const list = document.getElementById('providers-list');
  const entries = Object.entries(S.providers);
  if (!entries.length) {
    list.innerHTML = '<div style="font-size:12px;color:var(--muted);">Aucun provider enregistré.</div>';
    return;
  }
  list.innerHTML = entries.map(([id, p]) => {
    const maskedKey = p.key ? p.key : '<span style="color:var(--muted);">pas de clé</span>';
    const models = (p.models || []).map(m => `<span class="ed-tag" style="pointer-events:none;">${esc(m)}</span>`).join('');
    return `
    <div style="display:flex;align-items:flex-start;gap:8px;padding:10px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;margin-bottom:8px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:2px;">${esc(p.label || id)} <span style="font-size:10px;font-family:var(--mono);color:var(--muted);font-weight:400;">${esc(id)}</span></div>
        <div style="font-size:11px;font-family:var(--mono);color:var(--accent);margin-bottom:4px;">${esc(p.endpoint || '')}</div>
        <div style="font-size:11px;color:var(--muted);font-family:var(--mono);margin-bottom:6px;">${maskedKey}</div>
        ${models ? `<div style="display:flex;flex-wrap:wrap;gap:4px;">${models}</div>` : ''}
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;flex-shrink:0;">
        <button class="btn btng" style="padding:4px 10px;font-size:11px;" onclick="editProvider('${esc(id)}')">✏</button>
        <button class="btn btnd" style="padding:4px 10px;font-size:11px;" onclick="deleteProvider('${esc(id)}')">✕</button>
      </div>
    </div>`;
  }).join('');
}

function fillProviderPreset(id, label, endpoint, models) {
  document.getElementById('pf-id').value       = id;
  document.getElementById('pf-label').value    = label;
  document.getElementById('pf-endpoint').value = endpoint;
  document.getElementById('pf-key').value      = '';
  _pfModels.length = 0;
  models.forEach(m => _pfModels.push(m));
  renderPfModels();
  document.getElementById('pf-key').focus();
}

function editProvider(id) {
  const p = S.providers[id];
  if (!p) return;
  document.getElementById('pf-id').value       = id;
  document.getElementById('pf-label').value    = p.label || '';
  document.getElementById('pf-endpoint').value = p.endpoint || '';
  document.getElementById('pf-key').value      = '';
  _pfModels.length = 0;
  (p.models || []).forEach(m => _pfModels.push(m));
  renderPfModels();
  document.getElementById('pf-key').focus();
}

function addProviderModel() {
  const input = document.getElementById('pf-model-input');
  const val = input.value.trim();
  if (!val || _pfModels.includes(val)) { input.value = ''; return; }
  _pfModels.push(val);
  renderPfModels();
  input.value = '';
  input.focus();
}

function removeProviderModel(m) {
  const idx = _pfModels.indexOf(m);
  if (idx >= 0) _pfModels.splice(idx, 1);
  renderPfModels();
}

function renderPfModels() {
  const wrap = document.getElementById('pf-models-wrap');
  if (!wrap) return;
  wrap.innerHTML = _pfModels.length
    ? _pfModels.map(m => `<span class="ed-tag">${esc(m)}<button type="button" class="ed-tag-rm" onclick="removeProviderModel('${esc(m)}')">×</button></span>`).join('')
    : `<span style="font-size:12px;color:var(--muted);">Aucun modèle — l'utilisateur pourra saisir librement.</span>`;
}

async function saveProvider() {
  const id       = document.getElementById('pf-id').value.trim();
  const label    = document.getElementById('pf-label').value.trim();
  const endpoint = document.getElementById('pf-endpoint').value.trim();
  const key      = document.getElementById('pf-key').value.trim();
  if (!id || !endpoint) return alert('ID et endpoint sont requis.');
  await api('/providers', 'POST', { id, label: label || id, endpoint, key, models: [..._pfModels] });
  await loadProviders();
  renderProvidersList();
  document.getElementById('pf-id').value = '';
  document.getElementById('pf-label').value = '';
  document.getElementById('pf-endpoint').value = '';
  document.getElementById('pf-key').value = '';
  _pfModels.length = 0;
  renderPfModels();
  log('info', `🔌 Provider "${id}" enregistré`);
}

async function deleteProvider(id) {
  if (!confirm(`Supprimer le provider "${id}" ?`)) return;
  await api(`/providers/${encodeURIComponent(id)}`, 'DELETE');
  await loadProviders();
  renderProvidersList();
  log('info', `🔌 Provider "${id}" supprimé`);
}

function onEditorProviderChange() {
  const pid = document.getElementById('ec-provider').value;
  populateModelDatalist(pid);
  document.getElementById('ec-model').value = '';
}

function populateModelDatalist(providerId) {
  const dl = document.getElementById('ec-model-list');
  if (!dl) return;
  const models = S.providers[providerId]?.models || [];
  dl.innerHTML = models.map(m => `<option value="${esc(m)}">`).join('');
}

// ─── Overlay click ─────────────────────────────────────────────────────────
function handleOverlayClick(e, id) {
  if (e.target === document.getElementById(id))
    document.getElementById(id).classList.remove('open');
}

// ─── Helpers ───────────────────────────────────────────────────────────────
async function api(path, method='GET', body=null) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API+path, opts);
  return res.json();
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
