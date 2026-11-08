'use strict';

// Empty string = relative URLs, so the app works on any host/port without changes.
// All fetch calls like fetch(`${BASE_URL}/login`) become fetch('/login').
const BASE_URL = '';

// ============================================================
// STORAGE HELPERS
// ============================================================

function getUserId() {
  return localStorage.getItem('user_id');
}

function setUserId(id) {
  localStorage.setItem('user_id', String(id));
}

// ============================================================
// PAGE ROUTING
// ============================================================

const PAGE_IDS = ['landing-page', 'dashboard-page'];

function showPage(pageId) {
  PAGE_IDS.forEach(id => {
    document.getElementById(id).classList.toggle('hidden', id !== pageId);
  });
}

function requireAuth() {
  if (!getUserId()) {
    showPage('landing-page');
    return false;
  }
  return true;
}

// ============================================================
// UTILITIES
// ============================================================

function showError(el, msg) {
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideError(el) {
  el.textContent = '';
  el.classList.add('hidden');
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ============================================================
// LANDING PAGE
// ============================================================

function initLandingPage() {
  document.getElementById('btn-google-login').addEventListener('click', () => {
    const userId = getUserId();
    if (userId) {
      showPage('dashboard-page');
      loadPlaylists();
    } else {
      window.location.href = `${BASE_URL}/google_auth`;
    }
  });
}

// ============================================================
// DASHBOARD — PLAYLIST LOADING
// ============================================================

async function loadPlaylists() {
  if (!requireAuth()) return;

  const grid = document.getElementById('playlist-grid');
  grid.innerHTML = '<div class="loading-state">Loading your playlists...</div>';

  try {
    const res = await fetch(`${BASE_URL}/playlists/${getUserId()}`);
    const data = await res.json();

    if (!res.ok) {
      grid.innerHTML = `<div class="error-center">${escapeHtml(data.detail || 'Failed to load playlists.')}</div>`;
      return;
    }

    renderPlaylists(data.playlists || []);
  } catch {
    grid.innerHTML = '<div class="error-center">Could not connect to the server. Is the backend running?</div>';
  }
}

function getPlatformIcon(platform) {
  if (platform === 'youtube') {
    return `
      <div class="platform-icon">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 90 63" width="60" height="42" aria-label="YouTube">
          <rect width="90" height="63" rx="14" fill="#FF0000"/>
          <polygon points="35,13 35,50 63,31.5" fill="#FFFFFF"/>
        </svg>
      </div>`;
  }

  if (platform === 'spotify') {
    return `
      <div class="platform-icon">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="50" height="50" aria-label="Spotify">
          <circle cx="50" cy="50" r="50" fill="#1DB954"/>
          <path d="M24,64 Q50,52 76,64" stroke="#FFFFFF" stroke-width="7" stroke-linecap="round" fill="none"/>
          <path d="M20,50 Q50,36 80,50" stroke="#FFFFFF" stroke-width="7" stroke-linecap="round" fill="none"/>
          <path d="M16,36 Q50,20 84,36" stroke="#FFFFFF" stroke-width="7" stroke-linecap="round" fill="none"/>
        </svg>
      </div>`;
  }

  // 'both' or anything else
  return '<div class="platform-icon emoji-icon">🎵</div>';
}

function renderPlaylists(playlists) {
  const grid = document.getElementById('playlist-grid');

  if (!playlists.length) {
    grid.innerHTML = '<div class="empty-state">No playlists yet — create one to get started!</div>';
    return;
  }

  grid.innerHTML = playlists.map(pl => `
    <div class="playlist-card">
      ${getPlatformIcon(pl.platform)}
      <div class="playlist-name">${escapeHtml(pl.name)}</div>
      <div class="playlist-date">${formatDate(pl.created_at)}</div>
    </div>
  `).join('');
}

// ============================================================
// ACTION MENU DROPDOWN
// ============================================================

function initActionMenu() {
  const toggle = document.getElementById('action-menu-btn');
  const list   = document.getElementById('action-menu-list');

  function openMenu() {
    list.classList.add('open');
    toggle.setAttribute('aria-expanded', 'true');
    const first = list.querySelector('.menu-item');
    if (first) first.focus();
  }

  function closeMenu() {
    list.classList.remove('open');
    toggle.setAttribute('aria-expanded', 'false');
  }

  toggle.addEventListener('click', () => {
    list.classList.contains('open') ? closeMenu() : openMenu();
  });

  // Close when any item is activated (the item's own listener fires next).
  list.addEventListener('click', (e) => {
    if (e.target.classList.contains('menu-item')) closeMenu();
  });

  // Keyboard: Escape closes; Arrow keys move focus between items.
  list.addEventListener('keydown', (e) => {
    const items = [...list.querySelectorAll('.menu-item')];
    const idx   = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { closeMenu(); toggle.focus(); }
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(idx + 1) % items.length].focus(); }
    if (e.key === 'ArrowUp')   { e.preventDefault(); items[(idx - 1 + items.length) % items.length].focus(); }
  });

  // Close when clicking outside the menu.
  document.addEventListener('click', (e) => {
    if (!toggle.contains(e.target) && !list.contains(e.target)) closeMenu();
  });
}

// ============================================================
// MODALS — OPEN / CLOSE
// ============================================================

function openModal(modalId) {
  document.getElementById(modalId).classList.remove('hidden');
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  modal.classList.add('hidden');

  // Reset all text inputs and checkboxes inside the modal.
  modal.querySelectorAll('input[type="text"], input[type="password"]').forEach(el => {
    el.value = '';
  });
  modal.querySelectorAll('input[type="checkbox"]').forEach(el => {
    el.checked = false;
  });

  // Hide any visible error messages.
  modal.querySelectorAll('.modal-error').forEach(el => {
    el.textContent = '';
    el.classList.add('hidden');
  });
}

function setModalError(modalId, msg) {
  const errEl = document.querySelector(`#${modalId} .modal-error`);
  if (errEl) {
    errEl.textContent = msg;
    errEl.classList.remove('hidden');
  }
}

function clearModalError(modalId) {
  const errEl = document.querySelector(`#${modalId} .modal-error`);
  if (errEl) {
    errEl.textContent = '';
    errEl.classList.add('hidden');
  }
}

// Runs an async API call for a modal action.
// On success: closes the modal and refreshes playlists.
// On error: shows the detail message inside the modal.
async function executeModalAction(modalId, apiFn) {
  const btn = document.querySelector(`#${modalId} .modal-action-btn`);
  const originalText = btn.textContent;

  clearModalError(modalId);
  btn.disabled = true;
  btn.textContent = 'Processing...';

  try {
    const res = await apiFn();
    if (res.ok) {
      closeModal(modalId);
      loadPlaylists();
    } else {
      try {
        const data = await res.json();
        setModalError(modalId, data.detail || 'An error occurred. Please try again.');
      } catch {
        setModalError(modalId, 'An error occurred. Please try again.');
      }
    }
  } catch (err) {
    setModalError(modalId, err.message || 'Failed to connect to the server.');
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// ============================================================
// MODALS — WIRING
// ============================================================

function initModals() {
  // --- Global: close on overlay click or X button ---
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    // Close when clicking the dark backdrop (not the card itself).
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        overlay.classList.add('hidden');
        // Clear errors and inputs when dismissed.
        closeModal(overlay.id);
      }
    });

    overlay.querySelector('.modal-close').addEventListener('click', () => {
      closeModal(overlay.id);
    });
  });

  // --- CREATE PLAYLIST ---
  document.getElementById('btn-create-playlist').addEventListener('click', () => {
    openModal('modal-create');
  });

  document.querySelector('#modal-create .modal-action-btn').addEventListener('click', () => {
    const name     = document.getElementById('cp-name').value.trim();
    const platform = document.getElementById('cp-platform').value;
    const userId = getUserId();

    if (!name) {
      setModalError('modal-create', 'Please enter a playlist name.');
      return;
    }

    executeModalAction('modal-create', () =>
      fetch(`${BASE_URL}/create_playlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, user_id: userId, platform }),
      })
    );
  });

  // --- ADD PLAYLIST ---
  document.getElementById('btn-add-playlist').addEventListener('click', () => {
    openModal('modal-add');
  });

  document.querySelector('#modal-add .modal-action-btn').addEventListener('click', () => {
    const name     = document.getElementById('ap-name').value.trim();
    const platform = document.getElementById('ap-platform').value;
    const userId = getUserId();

    if (!name) {
      setModalError('modal-add', 'Please enter a playlist name.');
      return;
    }

    executeModalAction('modal-add', () =>
      fetch(`${BASE_URL}/add_playlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, platform, user_id: userId }),
      })
    );
  });

  // --- COPY PLAYLIST ---
  document.getElementById('btn-copy-playlist').addEventListener('click', () => {
    openModal('modal-copy');
  });

  document.querySelector('#modal-copy .modal-action-btn').addEventListener('click', () => {
    const name     = document.getElementById('cop-name').value.trim();
    const platform = document.getElementById('cop-platform').value;
    const sync     = document.getElementById('cop-sync').checked;
    const userId = getUserId();

    if (!name) {
      setModalError('modal-copy', 'Please enter a playlist name.');
      return;
    }

    executeModalAction('modal-copy', () =>
      fetch(`${BASE_URL}/copy_playlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, platform, user_id: userId, sync }),
      })
    );
  });

  // --- SYNC PLAYLIST ---
  document.getElementById('btn-sync-playlist').addEventListener('click', () => {
    openModal('modal-sync');
  });

  document.querySelector('#modal-sync .modal-action-btn').addEventListener('click', () => {
    const name     = document.getElementById('scp-name').value.trim();
    const platform = document.getElementById('scp-platform').value;
    const userId = getUserId();

    if (!name) {
      setModalError('modal-sync', 'Please enter a playlist name.');
      return;
    }

    executeModalAction('modal-sync', () =>
      fetch(`${BASE_URL}/sync_playlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, user_id: userId, override_platform: platform }),
      })
    );
  });

  // --- DELETE PLAYLIST ---
  document.getElementById('btn-delete-playlist').addEventListener('click', () => {
    openModal('modal-delete');
  });

  document.querySelector('#modal-delete .modal-action-btn').addEventListener('click', () => {
    const name     = document.getElementById('dp-name').value.trim();
    const platform = document.getElementById('dp-platform').value;
    const userId   = getUserId();

    if (!name) {
      setModalError('modal-delete', 'Please enter a playlist name.');
      return;
    }

    const queryString = `name=${encodeURIComponent(name)}&platform=${encodeURIComponent(platform)}&user_id=${encodeURIComponent(userId)}`;

    executeModalAction('modal-delete', () =>
      fetch(`${BASE_URL}/delete_playlist?${queryString}`, {
        method: 'DELETE',
      })
    );
  });

  // --- LOGOUT ---
  document.getElementById('btn-logout').addEventListener('click', () => {
    openModal('modal-logout');
  });

  document.getElementById('btn-logout-cancel').addEventListener('click', () => {
    closeModal('modal-logout');
  });

  document.getElementById('btn-logout-confirm').addEventListener('click', async () => {
    const userId = getUserId();
    try {
      const res = await fetch(`${BASE_URL}/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
      });
      if (res.ok) {
        closeModal('modal-logout');
        localStorage.removeItem('user_id');
        showPage('landing-page');
      } else {
        const data = await res.json();
        alert(`Error: ${data.detail || 'Could not log out.'}`);
      }
    } catch {
      alert('Failed to connect to the server. Please try again.');
    }
  });

  // --- DELETE ACCOUNT ---
  document.getElementById('btn-delete-account').addEventListener('click', () => {
    openModal('modal-delete-account');
  });

  document.getElementById('btn-delete-account-cancel').addEventListener('click', () => {
    closeModal('modal-delete-account');
  });

  document.getElementById('btn-delete-account-confirm').addEventListener('click', async () => {
    const userId = getUserId();
    try {
      const res = await fetch(`${BASE_URL}/delete_account?user_id=${encodeURIComponent(userId)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        closeModal('modal-delete-account');
        localStorage.clear();
        showPage('landing-page');
      } else {
        const data = await res.json();
        alert(`Error: ${data.detail || 'Could not delete account.'}`);
      }
    } catch {
      alert('Failed to connect to the server. Please try again.');
    }
  });
}

// ============================================================
// GENERATE WITH AI
// ============================================================

// True while a /generate_playlist request is running, so a double-click
// (or reopening the modal) can't start a second paid generation.
let aiRequestInFlight = false;
let aiElapsedTimer = null;

function setAiBusy(busy) {
  const form    = document.getElementById('ai-form');
  const btn     = document.getElementById('btn-ai-submit');
  const status  = document.getElementById('ai-status');
  const elapsed = document.getElementById('ai-elapsed');

  aiRequestInFlight = busy;
  btn.disabled = busy;
  btn.textContent = busy ? 'Generating...' : 'Generate';
  form.querySelectorAll('input, select').forEach(el => { el.disabled = busy; });
  form.setAttribute('aria-busy', String(busy));
  status.classList.toggle('hidden', !busy);

  clearInterval(aiElapsedTimer);
  elapsed.textContent = '';
  if (busy) {
    const start = Date.now();
    aiElapsedTimer = setInterval(() => {
      elapsed.textContent = `${Math.floor((Date.now() - start) / 1000)}s`;
    }, 1000);
  }
}

function showAiForm() {
  document.getElementById('ai-form').classList.remove('hidden');
  document.getElementById('ai-result').classList.add('hidden');
}

function platformLabel(platform) {
  if (platform === 'spotify') return 'Spotify';
  if (platform === 'youtube') return 'YouTube';
  return 'Spotify and YouTube';
}

function showAiResult(data, name, platform) {
  const added   = data.added || [];
  const skipped = data.skipped || [];
  const total   = Number.isInteger(data.total) ? data.total : added.length + skipped.length;

  const summary = document.getElementById('ai-result-summary');
  const note    = document.getElementById('ai-result-note');

  if (data.playlist_created) {
    summary.textContent = `Added ${added.length} of ${total} songs`;
    note.textContent = data.synced
      ? `"${name}" was created on Spotify and YouTube and is kept synced.`
      : `"${name}" was created on ${platformLabel(platform)}.`;
  } else {
    summary.textContent = 'No playlist was created';
    note.textContent = data.message || 'None of the suggested songs could be found.';
  }

  const wrap = document.getElementById('ai-skipped-wrap');
  const list = document.getElementById('ai-skipped-list');
  document.getElementById('ai-skipped-title').textContent = `Skipped (${skipped.length})`;
  list.innerHTML = skipped.map(s => `
    <li>
      <span class="ai-skipped-song">${escapeHtml(s.title)} — ${escapeHtml(s.artist)}</span>
      <span class="ai-skipped-reason">${escapeHtml(s.reason || 'Not found')}</span>
    </li>
  `).join('');
  wrap.classList.toggle('hidden', skipped.length === 0);

  document.getElementById('ai-form').classList.add('hidden');
  document.getElementById('ai-result').classList.remove('hidden');
  summary.focus();
}

// The backend sends friendly messages as `detail` (limit reached, timeout,
// garbled reply). Anything else gets a generic message, never a raw error.
function friendlyAiError(status, data) {
  if (data && typeof data.detail === 'string') return data.detail;
  if (status === 422) return 'Please check the playlist name and description (the description can be up to 300 characters).';
  if (status >= 500) return 'Something went wrong on the server. Please try again in a moment.';
  return 'Something went wrong. Please try again.';
}

function closeAiModal() {
  closeModal('modal-ai');
  document.getElementById('action-menu-btn').focus();
}

function initAiGenerator() {
  const modal  = document.getElementById('modal-ai');
  const form   = document.getElementById('ai-form');
  const nameEl = document.getElementById('ai-name');

  document.getElementById('btn-generate-ai').addEventListener('click', () => {
    openModal('modal-ai');
    if (aiRequestInFlight) {
      // Still running from before the modal was closed: just show the status.
      document.getElementById('ai-status').focus();
      return;
    }
    showAiForm();
    clearModalError('modal-ai');
    nameEl.focus();
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (aiRequestInFlight) return;

    const name     = nameEl.value.trim();
    const prompt   = document.getElementById('ai-prompt').value.trim();
    const platform = document.getElementById('ai-platform').value;

    clearModalError('modal-ai');
    if (!name) {
      setModalError('modal-ai', 'Please enter a playlist name.');
      nameEl.focus();
      return;
    }
    if (!prompt) {
      setModalError('modal-ai', 'Please describe the music you want.');
      document.getElementById('ai-prompt').focus();
      return;
    }

    setAiBusy(true);
    document.getElementById('ai-status').focus();

    try {
      const res = await fetch(`${BASE_URL}/generate_playlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, prompt, platform, user_id: getUserId() }),
      });

      let data = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }

      if (res.ok && data) {
        showAiResult(data, name, platform);
        if (data.playlist_created) loadPlaylists();
      } else {
        setModalError('modal-ai', friendlyAiError(res.status, data));
      }
    } catch {
      setModalError(
        'modal-ai',
        'Lost connection to the server. Your playlist may still have been created, so check your dashboard before trying again.'
      );
    } finally {
      setAiBusy(false);
      if (document.getElementById('ai-result').classList.contains('hidden')) {
        document.getElementById('btn-ai-submit').focus();
      }
    }
  });

  document.getElementById('btn-ai-done').addEventListener('click', closeAiModal);

  // The X button is wired in initModals(); this just returns focus to the menu.
  modal.querySelector('.modal-close').addEventListener('click', () => {
    document.getElementById('action-menu-btn').focus();
  });

  // Keyboard: Escape closes, Tab stays inside the modal.
  modal.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeAiModal();
      return;
    }
    if (e.key !== 'Tab') return;

    const focusable = [...modal.querySelectorAll('button, input, select')]
      .filter(el => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];

    if (e.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
}

// ============================================================
// DASHBOARD INITIALIZATION
// ============================================================

function initDashboard() {
  // The navbar buttons and modals are wired in initModals().
  // Playlist loading happens in loadPlaylists() called from showPage transitions.
}

// ============================================================
// APP INIT
// ============================================================

function init() {
  initLandingPage();
  initActionMenu();
  initModals();
  initAiGenerator();
  initDashboard();

  // Check if the backend redirected back here after OAuth with a user_id param.
  // This happens after a successful Google + Spotify auth flow.
  const params = new URLSearchParams(window.location.search);
  const oauthUserId = params.get('user_id');
  if (oauthUserId) {
    setUserId(oauthUserId);
    // Remove the query param from the URL so it doesn't persist on refresh.
    window.history.replaceState({}, '', window.location.pathname);
    showPage('dashboard-page');
    loadPlaylists();
    return;
  }

  // Route to dashboard if already logged in, otherwise show landing page.
  const userId = getUserId();
  if (userId) {
    showPage('dashboard-page');
    loadPlaylists();
  } else {
    showPage('landing-page');
  }
}

document.addEventListener('DOMContentLoaded', init);
