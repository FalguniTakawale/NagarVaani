/* Entry point. Inline onclick="" handlers in the HTML can only reach global
   (window) functions, not module-scoped exports — so this file's only job is
   to import every feature module and republish the handful of functions the
   markup calls directly onto window, then kick off the initial render. */
import { applyAuthUI, setUiRefs, logout, startTelegramLink } from './api.js';
import { showToast, showHelp, closeHelp } from './ui.js';
import { applyLanguage, setLanguage, toggleLangMenu, t } from './i18n.js';
import { nav, openComplaint, topbarSearch, trackComplaintById } from './nav.js';
import { toggleRecording } from './voice.js';
import { sortToggle, selectCat, voteUp, quickVote, setMyStatusFilter, filterTrendingByArea, clearTrendingAreaFilter, toggleSchemesPanel, toggleNotifMenu, refreshNotifDot, translateCardTitle } from './feed.js';
import { doVote, doSameIssue, postComment, doTranslate, doDispute, translateComment, shareComplaint, flagComplaint } from './detail.js';
import {
  submitComplaint, captureLocation, overrideSubmitCityState,
  handlePhotoSelect, setPhotoCaption, togglePhoto360, removePhoto,
  copySubmitId, dismissSubmitSuccess,
} from './submit.js';
import { loadGovtDashboard, endorseComplaint, markInProgress, setGovtScope } from './govt.js';
import {
  refreshNearMe, nearMeManual, setNearMeRadius, setNearMeSort, toggleHeatmap, subscribeNeighborhood,
  showNearMeTutorial, closeNearMeTutorial, nearMeTutorialNext, nearMeTutorialStep, showNearMeManual, hideNearMeManual,
} from './nearme.js';
import { submitCorruption } from './corruption.js';
import { sendVolunteerInterest, sendOrgPartnerInterest } from './getinvolved.js';
import { toggleChatbotPanel, sendChatbotMessage, askChatbotSuggestion } from './chatbot.js';
import {
  switchToOfficialMode, switchToCitizenMode, offLogout, offOpenDetail, setOfficialView,
  loadOfficialQueue, expandQueueRow, officialAction, postOfficialResponse,
  loadHotspotMapFull, setOffMapScope, loadInvestmentFlags, downloadPrioritiesCsv,
  loadVerificationQueue, approveOfficialApplication, rejectOfficialApplication,
} from './official.js';
import {
  switchAuthTab, switchAuthTabByName, selectRole, selectSignupRole,
  goToStep, doSignIn, completeSignup, startOfficialSignup,
  showForgotPassword, backToSignIn, sendResetCode, submitResetPassword,
  updatePasswordStrength, otpInput, otpKeydown, otpPaste, verifyOtp, resendOtp,
} from './auth.js';

setUiRefs(showToast, nav, {
  official: switchToOfficialMode,
  // On a plain citizen login/logout just make sure the official shell is hidden;
  // don't force a navigation (the caller decides where to go next).
  citizen: () => { document.body.classList.remove('official-mode'); document.getElementById('official-shell').hidden = true; },
}, showHelp, refreshNotifDot);

// Citizen-facing sign out (the official portal has its own via offLogout).
// Sends them back to the marketing landing page, same as the topbar logo.
function doSignOut() {
  if (!confirm(t('js.confirmsignout'))) return;
  logout();
  nav('landing');
  showToast(t('js.signedout'));
}

Object.assign(window, {
  nav, openComplaint, toggleRecording, doSignOut, startTelegramLink, topbarSearch, trackComplaintById,
  sortToggle, selectCat, voteUp, quickVote, setMyStatusFilter, filterTrendingByArea, clearTrendingAreaFilter, toggleSchemesPanel,
  toggleNotifMenu, translateCardTitle,
  toggleChatbotPanel, sendChatbotMessage, askChatbotSuggestion,
  sendVolunteerInterest, sendOrgPartnerInterest,
  doVote, doSameIssue, postComment, doTranslate, doDispute, translateComment, shareComplaint, flagComplaint,
  submitComplaint, captureLocation, overrideSubmitCityState,
  handlePhotoSelect, setPhotoCaption, togglePhoto360, removePhoto,
  copySubmitId, dismissSubmitSuccess,
  loadGovtDashboard, endorseComplaint, markInProgress, setGovtScope,
  refreshNearMe, nearMeManual, setNearMeRadius, setNearMeSort, toggleHeatmap, subscribeNeighborhood,
  showNearMeTutorial, closeNearMeTutorial, nearMeTutorialNext, nearMeTutorialStep, showNearMeManual, hideNearMeManual,
  submitCorruption,
  switchToOfficialMode, switchToCitizenMode, offLogout, offOpenDetail, setOfficialView,
  loadOfficialQueue, expandQueueRow, officialAction, postOfficialResponse,
  loadHotspotMapFull, setOffMapScope, loadInvestmentFlags, downloadPrioritiesCsv,
  loadVerificationQueue, approveOfficialApplication, rejectOfficialApplication,
  switchAuthTab, switchAuthTabByName, selectRole, selectSignupRole,
  goToStep, doSignIn, completeSignup, startOfficialSignup,
  showForgotPassword, backToSignIn, sendResetCode, submitResetPassword,
  updatePasswordStrength, otpInput, otpKeydown, otpPaste, verifyOtp, resendOtp,
  applyLanguage, setLanguage, toggleLangMenu,
  showToast,
  showHelp, closeHelp,
});

// Init
// autocomplete="off" is only a hint — Chrome still re-offers a value it has
// already collected for a field on this origin (e.g. an email typed
// elsewhere on the page), regardless of that attribute. Explicitly clearing
// it after the browser's own autofill pass is the only reliable way to stop
// the topbar search box from showing up pre-filled with someone's email.
const topbarSearchInput = document.getElementById('topbar-search-input');
if (topbarSearchInput) {
  // The input is read-only until focused (see the HTML) so Chrome won't autofill
  // a saved login into it; these late clears are the belt-and-braces backup for
  // an autofill that lands after this script ran, or from the back/forward cache.
  const clearIfAutofilled = () => { if (document.activeElement !== topbarSearchInput) topbarSearchInput.value = ''; };
  clearIfAutofilled();
  [300, 1200, 3000].forEach(ms => setTimeout(clearIfAutofilled, ms));
  window.addEventListener('pageshow', clearIfAutofilled);
}

applyLanguage();   // restores the language saved in localStorage ('nv_lang')
applyAuthUI();     // officials are switched straight into the portal here
if (!document.body.classList.contains('official-mode')) {
  // A reload keeps the browser's session-history state for the current
  // entry (it's part of that history entry, not wiped by the reload) — so
  // restore whichever page was open, the same way reloading google.com's
  // results page keeps you on that page instead of bouncing to google.com/.
  // Falls back to the landing page only for a genuinely first-ever visit
  // (or the state predates this history.state field entirely).
  const restoreState = history.state;
  const hashMatch = /^#detail\/(.+)$/.exec(location.hash || '');
  if (hashMatch) {
    // Shared deep link (#detail/<id>) — open that complaint directly.
    openComplaint(decodeURIComponent(hashMatch[1]));
  } else if (restoreState && restoreState.page === 'detail' && restoreState.id) {
    openComplaint(restoreState.id);
  } else if (restoreState && restoreState.page) {
    nav(restoreState.page);
  } else if (/^#(levels|about|track|trending|forofficials|impact|orgsupport|govtschemes)$/.test(location.hash || '')) {
    nav(location.hash.slice(1));
  } else {
    nav('landing');
  }
}
