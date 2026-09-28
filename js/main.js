/* Entry point. Inline onclick="" handlers in the HTML can only reach global
   (window) functions, not module-scoped exports — so this file's only job is
   to import every feature module and republish the handful of functions the
   markup calls directly onto window, then kick off the initial render. */
import { applyAuthUI, setUiRefs, logout } from './api.js';
import { showToast } from './ui.js';
import { applyLanguage, setLanguage, toggleLangMenu, t } from './i18n.js';
import { nav, openComplaint } from './nav.js';
import { toggleRecording } from './voice.js';
import { sortToggle, selectCat, voteUp, quickVote, setMyStatusFilter } from './feed.js';
import { doVote, doSameIssue, postComment, doTranslate, doDispute, translateComment } from './detail.js';
import {
  submitComplaint, captureLocation,
  handlePhotoSelect, setPhotoCaption, togglePhoto360, removePhoto,
} from './submit.js';
import { loadGovtDashboard, endorseComplaint, markInProgress, setGovtScope } from './govt.js';
import { refreshNearMe, nearMeManual, setNearMeRadius, setNearMeSort } from './nearme.js';
import { submitCorruption } from './corruption.js';
import {
  switchToOfficialMode, switchToCitizenMode, offLogout, offOpenDetail, setOfficialView,
  loadOfficialQueue, expandQueueRow, officialAction, postOfficialResponse,
  loadHotspotMapFull, setOffMapScope, loadInvestmentFlags,
} from './official.js';
import {
  switchAuthTab, switchAuthTabByName, selectRole, selectSignupRole,
  goToStep, doSignIn, completeSignup,
  showForgotPassword, backToSignIn, sendResetCode, submitResetPassword,
  updatePasswordStrength, otpInput, otpKeydown, otpPaste, verifyOtp, resendOtp,
} from './auth.js';

setUiRefs(showToast, nav, {
  official: switchToOfficialMode,
  // On a plain citizen login/logout just make sure the official shell is hidden;
  // don't force a navigation (the caller decides where to go next).
  citizen: () => { document.body.classList.remove('official-mode'); document.getElementById('official-shell').hidden = true; },
});

// Citizen-facing sign out (the official portal has its own via offLogout).
// Sends them back to the marketing landing page, same as the topbar logo.
function doSignOut() {
  logout();
  nav('landing');
  showToast(t('js.signedout'));
}

Object.assign(window, {
  nav, openComplaint, toggleRecording, doSignOut,
  sortToggle, selectCat, voteUp, quickVote, setMyStatusFilter,
  doVote, doSameIssue, postComment, doTranslate, doDispute, translateComment,
  submitComplaint, captureLocation,
  handlePhotoSelect, setPhotoCaption, togglePhoto360, removePhoto,
  loadGovtDashboard, endorseComplaint, markInProgress, setGovtScope,
  refreshNearMe, nearMeManual, setNearMeRadius, setNearMeSort,
  submitCorruption,
  switchToOfficialMode, switchToCitizenMode, offLogout, offOpenDetail, setOfficialView,
  loadOfficialQueue, expandQueueRow, officialAction, postOfficialResponse,
  loadHotspotMapFull, setOffMapScope, loadInvestmentFlags,
  switchAuthTab, switchAuthTabByName, selectRole, selectSignupRole,
  goToStep, doSignIn, completeSignup,
  showForgotPassword, backToSignIn, sendResetCode, submitResetPassword,
  updatePasswordStrength, otpInput, otpKeydown, otpPaste, verifyOtp, resendOtp,
  applyLanguage, setLanguage, toggleLangMenu,
  showToast,
});

// Init
applyLanguage();   // restores the language saved in localStorage ('nv_lang')
applyAuthUI();     // officials are switched straight into the portal here
if (!document.body.classList.contains('official-mode')) nav('landing');
