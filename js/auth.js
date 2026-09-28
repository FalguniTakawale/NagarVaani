import { api, storeSession } from './api.js';
import { showToast } from './ui.js';
import { nav } from './nav.js';
import { t } from './i18n.js';

const SIGNUP_FORMS = ['form-signup-1', 'form-signup-2', 'form-signup-3', 'form-signup-4'];

export function switchAuthTab(btn, tab) {
  document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('form-signin').style.display = tab === 'signin' ? 'block' : 'none';
  document.getElementById('form-forgot').style.display = 'none';
  SIGNUP_FORMS.forEach(id => document.getElementById(id).style.display = 'none');
  if (tab === 'signup') document.getElementById('form-signup-1').style.display = 'block';
}

export function switchAuthTabByName(tab) {
  const tabs = document.querySelectorAll('.auth-tab');
  switchAuthTab(tab === 'signup' ? tabs[1] : tabs[0], tab);
}

export function selectRole(el) {
  el.closest('.role-cards').querySelectorAll('.role-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  const isOfficial = el.querySelector('.role-card-title').textContent === 'Official';
  const notice = document.getElementById('official-notice');
  if (notice) notice.style.display = isOfficial ? 'flex' : 'none';
}

export function selectSignupRole(el) {
  el.closest('.role-cards').querySelectorAll('.role-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  const isOfficial = el.querySelector('.role-card-title').textContent === 'Official';
  document.getElementById('official-level-group').style.display = isOfficial ? 'block' : 'none';
}

export function goToStep(step) {
  if (step === 2 && !passwordGate()) return; // don't advance past step 1 with a weak password
  document.getElementById('form-signin').style.display = 'none';
  SIGNUP_FORMS.forEach((id, i) => document.getElementById(id).style.display = step === i + 1 ? 'block' : 'none');
  if (step === 4) setTimeout(() => document.querySelector('#otp-row .otp-box').focus(), 50);
}

/* ── PASSWORD RULES — mirrors validate_password() in services/auth.py ──
   This is UX only; the backend re-checks and returns 400 on its own. */
const PASSWORD_RULES = [
  [/.{8,}/, 'at least 8 characters'],
  [/[A-Z]/, 'an uppercase letter'],
  [/[a-z]/, 'a lowercase letter'],
  [/\d/, 'a digit'],
  [/[^A-Za-z0-9]/, 'a special character (e.g. @ # ! $)'],
];

export function validatePassword(pw) {
  const missing = PASSWORD_RULES.filter(([re]) => !re.test(pw || '')).map(([, label]) => label);
  const passed = PASSWORD_RULES.length - missing.length;
  // Strong = every rule met and 12+ chars; Medium = all rules met (or one short); else Weak.
  const strength = missing.length === 0 && (pw || '').length >= 12 ? 'strong'
    : passed >= 4 ? 'medium' : 'weak';
  return { ok: missing.length === 0, missing, strength };
}

export function updatePasswordStrength(pw) {
  const meter = document.getElementById('pw-meter');
  const label = document.getElementById('pw-strength-label');
  const hint = document.getElementById('pw-strength-hint');
  const err = document.getElementById('signup-pass-error');
  err.classList.remove('show');
  if (!pw) { meter.hidden = true; return; }
  const { ok, missing, strength } = validatePassword(pw);
  meter.hidden = false;
  meter.className = 'pw-meter ' + strength;
  label.textContent = { weak: 'Weak', medium: 'Medium', strong: 'Strong' }[strength];
  hint.textContent = ok ? (strength === 'strong' ? 'Good password' : 'Meets all rules — 12+ characters makes it strong')
    : 'Needs ' + missing.join(', ');
}

function passwordGate() {
  const pw = document.getElementById('signup-pass').value;
  const { ok, missing } = validatePassword(pw);
  const err = document.getElementById('signup-pass-error');
  if (ok) { err.classList.remove('show'); return true; }
  updatePasswordStrength(pw);
  err.textContent = 'Password needs ' + missing.join(', ') + '.';
  err.classList.add('show');
  document.getElementById('signup-pass').focus();
  return false;
}

export async function doSignIn() {
  const email = document.getElementById('signin-email').value;
  const pass = document.getElementById('signin-pass').value;
  let valid = true;
  if (!email || !email.includes('@')) {
    document.getElementById('email-error').classList.add('show');
    document.getElementById('signin-email').classList.add('error');
    valid = false;
  } else {
    document.getElementById('email-error').classList.remove('show');
    document.getElementById('signin-email').classList.remove('error');
  }
  if (!pass) {
    document.getElementById('pass-error').classList.add('show');
    document.getElementById('signin-pass').classList.add('error');
    valid = false;
  } else {
    document.getElementById('pass-error').classList.remove('show');
    document.getElementById('signin-pass').classList.remove('error');
  }
  if (!valid) return;

  try {
    const result = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email, password: pass }) });
    finishLogin(result, email);
  } catch (err) {
    const d = err.data && err.data.detail;
    if (err.status === 403 && d && d.requires_verification) {
      // Account exists but the email was never verified — take them straight to the OTP step.
      showToast(d.msg);
      startOtpStep(d.user_id, d.email || email, { alreadySent: false });
      return;
    }
    showToast(err.message);
  }
}

function finishLogin(result, email) {
  storeSession(result.access_token, Object.assign({ email }, result)); // applyAuthUI() → official portal if role=official
  showToast(t('js.signedin', { name: result.name }));
  if (result.role !== 'official') setTimeout(() => nav('home'), 800);
}

/* ── FORGOT PASSWORD — real OTP flow, same pattern as signup verification ── */
let _forgotEmail = '';

export function showForgotPassword() {
  document.getElementById('form-signin').style.display = 'none';
  SIGNUP_FORMS.forEach(id => document.getElementById(id).style.display = 'none');
  document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('form-forgot').style.display = 'block';
  document.getElementById('forgot-step-email').style.display = 'block';
  document.getElementById('forgot-step-reset').style.display = 'none';
  document.getElementById('forgot-email').value = '';
  document.getElementById('forgot-otp').value = '';
  document.getElementById('forgot-newpass').value = '';
  document.getElementById('forgot-pass-error').classList.remove('show');
}

export function backToSignIn() {
  document.getElementById('form-forgot').style.display = 'none';
  switchAuthTabByName('signin');
}

export async function sendResetCode() {
  const email = document.getElementById('forgot-email').value.trim();
  if (!email || !email.includes('@')) { showToast(t('auth.invalidemail')); return; }
  const btn = document.getElementById('forgot-send-btn');
  btn.disabled = true;
  try {
    await api('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) });
    _forgotEmail = email;
    document.getElementById('forgot-step-email').style.display = 'none';
    document.getElementById('forgot-step-reset').style.display = 'block';
    showToast(t('auth.resetsent'));
  } catch (err) {
    showToast(err.message);
  } finally {
    btn.disabled = false;
  }
}

export async function submitResetPassword() {
  const otp = document.getElementById('forgot-otp').value.trim();
  const newPass = document.getElementById('forgot-newpass').value;
  const err = document.getElementById('forgot-pass-error');
  const { ok, missing } = validatePassword(newPass);
  if (!ok) {
    err.textContent = 'Password needs ' + missing.join(', ') + '.';
    err.classList.add('show');
    return;
  }
  err.classList.remove('show');
  if (!otp) { showToast(t('auth.entercode')); return; }

  const btn = document.getElementById('forgot-reset-btn');
  btn.disabled = true;
  try {
    const result = await api('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email: _forgotEmail, otp, new_password: newPass }),
    });
    document.getElementById('form-forgot').style.display = 'none';
    finishLogin(result, _forgotEmail);
  } catch (err2) {
    showToast(err2.message);
  } finally {
    btn.disabled = false;
  }
}

export async function completeSignup() {
  const isOfficial = document.querySelectorAll('#form-signup-1 .role-card')[1].classList.contains('selected');
  const payload = {
    name: document.getElementById('signup-name').value,
    email: document.getElementById('signup-email').value,
    password: document.getElementById('signup-pass').value,
    role: isOfficial ? 'official' : 'citizen',
    official_level: isOfficial ? document.getElementById('signup-official-level').value : null,
    state: document.getElementById('signup-state').value,
    city: document.getElementById('signup-city').value,
    area: document.getElementById('signup-area').value,
    ward: document.getElementById('signup-ward').value,
  };
  if (!payload.name || !payload.email || !payload.password) {
    showToast('Fill in name, email, and password first');
    goToStep(1);
    return;
  }
  if (!passwordGate()) { goToStep(1); return; }

  const btn = document.getElementById('create-account-btn');
  btn.disabled = true; btn.textContent = 'Creating account…';
  try {
    const result = await api('/auth/register', { method: 'POST', body: JSON.stringify(payload) });
    if (result.requires_verification) {
      startOtpStep(result.user_id, result.email, { alreadySent: true });
    } else if (result.access_token) {
      finishLogin(result, payload.email);
    }
  } catch (err) {
    if (err.status === 400) { // server-side password rule failure — show it on the field
      const e = document.getElementById('signup-pass-error');
      e.textContent = err.message; e.classList.add('show');
      goToStep(1);
    }
    showToast(err.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Create account';
  }
}

/* ── EMAIL OTP STEP ── */
let pendingUserId = null;
let pendingEmail = null;
let resendTimer = null;

function startOtpStep(userId, email, { alreadySent }) {
  pendingUserId = userId;
  pendingEmail = email;
  document.getElementById('otp-email-label').textContent = email;
  document.getElementById('otp-error').classList.remove('show');
  otpBoxes().forEach(b => { b.value = ''; b.classList.remove('error'); });
  document.querySelectorAll('.auth-tab').forEach((t, i) => t.classList.toggle('active', i === 1));
  goToStep(4);
  if (alreadySent) startResendCooldown(); else enableResend();
}

function otpBoxes() { return Array.from(document.querySelectorAll('#otp-row .otp-box')); }
function otpValue() { return otpBoxes().map(b => b.value).join(''); }

export function otpInput(event, i) {
  const boxes = otpBoxes();
  const box = boxes[i];
  box.value = box.value.replace(/\D/g, '').slice(-1);
  box.classList.remove('error');
  if (box.value && i < boxes.length - 1) boxes[i + 1].focus();
  if (otpValue().length === 6) verifyOtp();
}

export function otpKeydown(event, i) {
  const boxes = otpBoxes();
  if (event.key === 'Backspace' && !boxes[i].value && i > 0) { boxes[i - 1].focus(); boxes[i - 1].value = ''; event.preventDefault(); }
  else if (event.key === 'ArrowLeft' && i > 0) boxes[i - 1].focus();
  else if (event.key === 'ArrowRight' && i < boxes.length - 1) boxes[i + 1].focus();
}

export function otpPaste(event) {
  const digits = (event.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 6);
  if (!digits) return;
  event.preventDefault();
  const boxes = otpBoxes();
  digits.split('').forEach((d, i) => { boxes[i].value = d; });
  boxes[Math.min(digits.length, 5)].focus();
  if (digits.length === 6) verifyOtp();
}

export async function verifyOtp() {
  const otp = otpValue();
  const errEl = document.getElementById('otp-error');
  if (otp.length !== 6) { errEl.textContent = 'Enter all 6 digits'; errEl.classList.add('show'); return; }
  const btn = document.getElementById('otp-verify-btn');
  if (btn.disabled) return;
  btn.disabled = true; btn.textContent = 'Verifying…';
  try {
    const result = await api('/auth/verify-email', { method: 'POST', body: JSON.stringify({ user_id: pendingUserId, otp }) });
    errEl.classList.remove('show');
    clearInterval(resendTimer);
    showToast('✓ Email verified — welcome to NagarVaani');
    finishLogin(result, pendingEmail);
  } catch (err) {
    errEl.textContent = err.message; errEl.classList.add('show');
    otpBoxes().forEach(b => b.classList.add('error'));
    otpBoxes()[0].focus();
  } finally {
    btn.disabled = false; btn.textContent = 'Verify & sign in';
  }
}

export async function resendOtp() {
  const link = document.getElementById('otp-resend-link');
  if (link.dataset.disabled === '1' || !pendingEmail) return;
  link.dataset.disabled = '1';
  try {
    const result = await api('/auth/resend-otp', { method: 'POST', body: JSON.stringify({ email: pendingEmail }) });
    if (result.user_id) pendingUserId = result.user_id;
    showToast('New code sent');
    startResendCooldown();
  } catch (err) {
    showToast(err.message);
    enableResend();
  }
}

function startResendCooldown(seconds = 60) {
  const link = document.getElementById('otp-resend-link');
  const timer = document.getElementById('otp-resend-timer');
  link.dataset.disabled = '1'; link.style.opacity = '0.4'; link.style.pointerEvents = 'none';
  let left = seconds;
  timer.textContent = ` (${left}s)`;
  clearInterval(resendTimer);
  resendTimer = setInterval(() => {
    left -= 1;
    timer.textContent = left > 0 ? ` (${left}s)` : '';
    if (left <= 0) { clearInterval(resendTimer); enableResend(); }
  }, 1000);
}

function enableResend() {
  const link = document.getElementById('otp-resend-link');
  link.dataset.disabled = '0'; link.style.opacity = ''; link.style.pointerEvents = '';
  document.getElementById('otp-resend-timer').textContent = '';
}
