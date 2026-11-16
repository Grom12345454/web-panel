(() => {
  const root = document.querySelector('[data-staff-messenger]');
  if (!root) return;
  const conversationId = Number(root.dataset.conversationId || 0);
  const canWrite = root.dataset.canWrite === '1';
  const thread = document.getElementById('messenger-thread-body');

  // The messenger owns its own navigation and conversation filters. These
  // controls affect only the local chat list and never the website sidebar.
  const filterButtons = Array.from(document.querySelectorAll('[data-chat-filter]'));
  const conversationLinks = Array.from(document.querySelectorAll('[data-conversation-kind]'));
  const filterEmpty = document.getElementById('messenger-filter-empty');
  filterButtons.forEach(button => button.addEventListener('click', () => {
    const filter = button.dataset.chatFilter || 'all';
    let visible = 0;
    filterButtons.forEach(item => {
      const active = item === button;
      item.classList.toggle('is-active', active);
      item.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    conversationLinks.forEach(link => {
      const kind = link.dataset.conversationKind;
      const show = filter === 'all' || kind === filter || (filter === 'group' && kind === 'channel');
      link.hidden = !show;
      if (show) visible += 1;
    });
    if (filterEmpty) filterEmpty.hidden = visible !== 0;
  }));
  // Conversation actions are scoped to the current user's list, except the
  // explicit administrator archive action for shared channels/groups.
  document.querySelectorAll('[data-conversation-action]').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.conversationAction;
    const prompts = {
      hide: 'Убрать эту переписку только из вашего списка?',
      archive: 'Удалить этот канал из общего пространства? Он будет архивирован, история сохранится.'
    };
    if (prompts[action] && !window.confirm(prompts[action])) return;
    button.disabled = true;
    try {
      await api(`/staff-messenger/api/conversations/${conversationId}/preferences`, {method:'POST', body:JSON.stringify({action})});
      window.location.href = '/messenger';
    } catch (error) {
      window.alert(error.message || 'Не удалось выполнить действие.');
      button.disabled = false;
    }
  }));
  const permissionDialog = document.getElementById('messenger-channel-permissions-dialog');
  document.querySelector('[data-open-channel-permissions]')?.addEventListener('click', () => permissionDialog?.showModal());
  document.querySelectorAll('[data-close-channel-permissions]').forEach(button => button.addEventListener('click', () => permissionDialog?.close()));
  document.getElementById('messenger-channel-permissions-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const submit = event.currentTarget.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      const writerIds = Array.from(document.querySelectorAll('input[name="channel_permission_writer"]:checked')).map(item => Number(item.value));
      await api(`/staff-messenger/api/conversations/${conversationId}/channel-permissions`, {method:'POST', body:JSON.stringify({writer_ids:writerIds})});
      permissionDialog?.close();
      window.location.reload();
    } catch (error) {
      window.alert(error.message || 'Не удалось сохранить права канала.');
    } finally { submit.disabled = false; }
  });

  const composer = document.getElementById('messenger-composer');
  const input = document.getElementById('messenger-message-input');
  const fileInput = document.getElementById('messenger-attachments');
  const fileTrigger = document.getElementById('messenger-attach-trigger');
  const filePreview = document.getElementById('messenger-draft-attachments');
  const fileLabel = document.getElementById('messenger-file-label');
  const sendButton = composer?.querySelector('[type="submit"]');
  const emojiToggle = document.getElementById('messenger-emoji-toggle');
  const emojiMenu = document.getElementById('messenger-emoji-menu');
  const charCount = document.getElementById('messenger-char-count');
  const csrf = document.querySelector('input[name="csrf_token"]')?.value || '';
  // Auto-grow without forcing a second layout pass for every keystroke.
  const resizeComposerInput = () => {
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  };
  const updateCharCount = () => {
    if (!input || !charCount) return;
    charCount.textContent = `${input.value.length.toLocaleString('ru-RU')} / 5\u00a0000`;
    charCount.classList.toggle('is-near-limit', input.value.length >= 4500);
  };
  const insertEmoji = emoji => {
    if (!input || !emoji) return;
    const start = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
    const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : start;
    input.setRangeText(emoji, start, end, 'end');
    input.dispatchEvent(new Event('input', {bubbles:true}));
    input.focus();
  };
  emojiToggle?.addEventListener('click', () => {
    const open = emojiMenu?.hidden ?? true;
    if (emojiMenu) emojiMenu.hidden = !open;
    emojiToggle.setAttribute('aria-expanded', String(open));
  });
  emojiMenu?.addEventListener('click', event => {
    const choice = event.target.closest('[data-insert-emoji]');
    if (!choice) return;
    insertEmoji(choice.dataset.insertEmoji);
    emojiMenu.hidden = true;
    emojiToggle?.setAttribute('aria-expanded', 'false');
  });
  document.addEventListener('click', event => {
    if (!emojiMenu || emojiMenu.hidden || event.target.closest('.messenger-emoji-control')) return;
    emojiMenu.hidden = true;
    emojiToggle?.setAttribute('aria-expanded', 'false');
  });
  input?.addEventListener('keydown', event => {
    if (event.key === 'Escape' && emojiMenu && !emojiMenu.hidden) {
      emojiMenu.hidden = true;
      emojiToggle?.setAttribute('aria-expanded', 'false');
      emojiToggle?.focus();
    }
  });
  const selectedFiles = () => Array.from(fileInput?.files || []);
  const syncComposerState = () => {
    if (!sendButton) return;
    sendButton.disabled = !(input?.value.trim() || selectedFiles().length) || sendButton.dataset.sending === '1';
  };
  const formatSize = bytes => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
  const renderDraftFiles = () => {
    if (!fileInput || !filePreview) return;
    let files = selectedFiles();
    const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
    if (files.length > 4 || totalBytes > 8 * 1024 * 1024) {
      fileInput.value = ''; files = [];
      if (fileLabel) fileLabel.textContent = 'Лимит: до 4 файлов и до 8 МБ. Выберите файлы заново.';
    }
    filePreview.replaceChildren();
    filePreview.hidden = !files.length;
    files.forEach((file, index) => {
      const chip = document.createElement('span');
      chip.className = 'messenger-draft-file';
      const name = document.createElement('span');
      name.textContent = `${file.name} · ${formatSize(file.size)}`;
      const remove = document.createElement('button');
      remove.type = 'button'; remove.className = 'messenger-draft-file-remove';
      remove.dataset.removeDraftFile = String(index); remove.setAttribute('aria-label', `Убрать файл ${file.name}`); remove.textContent = '×';
      chip.append(name, remove); filePreview.append(chip);
    });
    if (fileLabel && (files.length || !fileLabel.textContent.startsWith('Лимит:'))) fileLabel.textContent = files.length ? `${files.length} из 4 файлов · ${formatSize(totalBytes)} из 8 МБ` : 'До 4 файлов · до 8 МБ суммарно';
    syncComposerState();
  };
  if (input) {
    input.addEventListener('input', () => { resizeComposerInput(); syncComposerState(); updateCharCount(); });
    input.addEventListener('keydown', event => {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
      event.preventDefault();
      if (composer?.requestSubmit && !sendButton?.disabled) composer.requestSubmit();
    });
    resizeComposerInput();
    updateCharCount();
  }
  fileTrigger?.addEventListener('click', () => fileInput?.click());
  fileInput?.addEventListener('change', renderDraftFiles);
  filePreview?.addEventListener('click', event => {
    const remove = event.target.closest('[data-remove-draft-file]');
    if (!remove || !fileInput) return;
    const transfer = new DataTransfer();
    selectedFiles().forEach((file, index) => { if (index !== Number(remove.dataset.removeDraftFile)) transfer.items.add(file); });
    fileInput.files = transfer.files; renderDraftFiles();
  });
  composer?.addEventListener('dragover', event => { if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); composer.classList.add('is-dragging'); } });
  ['dragleave','drop'].forEach(type => composer?.addEventListener(type, event => { composer.classList.remove('is-dragging'); if (type === 'drop' && event.dataTransfer?.files?.length && fileInput) { event.preventDefault(); const transfer = new DataTransfer(); [...selectedFiles(), ...Array.from(event.dataTransfer.files)].slice(0,4).forEach(file => transfer.items.add(file)); fileInput.files = transfer.files; renderDraftFiles(); } }));

  // Apply saved design changes in this open messenger immediately. Only safe CSS
  // colour tokens are accepted; no forced reflow or full-screen animation.
  const applyLiveTheme = message => {
    if (!message || message.type !== 'theme-save' || !/^[a-z0-9_-]{1,48}$/i.test(message.theme || '')) return;
    const body = document.body;
    const validHex = value => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
    const toRgb = value => validHex(value) ? [1,3,5].map(i => parseInt(value.slice(i, i + 2), 16)).join(', ') : null;
    body.dataset.theme = message.theme; body.dataset.season = message.theme;
    const vars = { '--office-accent': message.accent, '--office-secondary': message.secondary, '--office-depth': message.depth, '--office-accent-rgb': toRgb(message.accent), '--office-secondary-rgb': toRgb(message.secondary), '--season-accent': message.accent, '--season-secondary': message.secondary };
    Object.entries(vars).forEach(([name, value]) => { if (value && (name.endsWith('-rgb') ? /^\d{1,3},\s*\d{1,3},\s*\d{1,3}$/.test(value) : validHex(value))) body.style.setProperty(name, value); });
    if (message.themeVars && typeof message.themeVars === 'object' && !Array.isArray(message.themeVars)) Object.entries(message.themeVars).slice(0,32).forEach(([name,value]) => { if (/^season-[a-z0-9-]{1,48}$/.test(name) && typeof value === 'string' && (/^#[0-9a-f]{3,8}$/i.test(value) || /^\d{1,3},\s*\d{1,3},\s*\d{1,3}$/.test(value))) body.style.setProperty(`--${name}`, value); });
    const meta = document.querySelector('meta[name="theme-color"]'); if (meta && validHex(message.depth)) meta.content = message.depth;
  };
  try { const themeChannel = new BroadcastChannel('student-council-theme-v60'); themeChannel.addEventListener('message', event => applyLiveTheme(event.data)); window.addEventListener('pagehide', () => themeChannel.close(), { once: true }); }
  catch (_) { window.addEventListener('storage', event => { if (event.key === 'student-council-theme-v60' && event.newValue) { try { applyLiveTheme(JSON.parse(event.newValue)); } catch (_) {} } }); }

  // Electron runs in its own Chromium storage partition, so it cannot receive
  // BroadcastChannel events from the regular site browser. Poll the authenticated
  // palette endpoint every 15 seconds instead of every 250ms; CSS tokens still
  // apply immediately once a change is observed, without reload or forced reflow.
  if (root.dataset.nativeDesktop === '1') {
    let themePollBusy = false;
    let themePollTimer = 0;
    const pollDesktopTheme = async () => {
      if (themePollBusy || document.visibilityState !== 'visible' || !navigator.onLine) return;
      themePollBusy = true;
      try {
        const response = await fetch('/api/visual-theme', {
          method: 'GET', credentials: 'same-origin', cache: 'no-store',
          headers: { 'Accept': 'application/json' }
        });
        if (response.ok) {
          const palette = await response.json();
          if (palette && palette.theme) applyLiveTheme({ ...palette, type: 'theme-save' });
        }
      } catch (_) { /* Keep the current palette during temporary network loss. */ }
      finally { themePollBusy = false; }
    };
    const DESKTOP_THEME_POLL_INTERVAL = 15000;
    const scheduleDesktopThemePoll = (delay = DESKTOP_THEME_POLL_INTERVAL) => {
      if (themePollTimer) window.clearTimeout(themePollTimer);
      themePollTimer = 0;
      if (document.visibilityState !== 'visible') return;
      themePollTimer = window.setTimeout(async () => {
        themePollTimer = 0;
        await pollDesktopTheme();
        scheduleDesktopThemePoll(DESKTOP_THEME_POLL_INTERVAL);
      }, delay);
    };
    scheduleDesktopThemePoll(0);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        if (themePollTimer) window.clearTimeout(themePollTimer);
        themePollTimer = 0;
      } else scheduleDesktopThemePoll(0);
    });
    window.addEventListener('online', () => scheduleDesktopThemePoll(0));
    window.addEventListener('pagehide', () => { if (themePollTimer) window.clearTimeout(themePollTimer); }, { once: true });
  }

  let lastMessageId = Math.max(0, ...Array.from(document.querySelectorAll('[data-message-id]')).map(x => Number(x.dataset.messageId || 0)));
  let lastTypingSent = 0;
  let pollBusy = false;

  const api = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    headers.set('X-CSRF-Token', csrf);
    if (!(options.body instanceof FormData) && options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(url, {...options, headers, credentials: 'same-origin'});
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok || data.ok === false) throw new Error(data.error || `Ошибка ${response.status}`);
    return data;
  };

  const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function renderReactions(message) {
    return (message.reactions || []).map(item => `<button type="button" class="messenger-reaction ${item.mine ? 'is-active' : ''}" data-reaction="${escape(item.emoji)}" data-message-id="${message.id}" aria-pressed="${item.mine ? 'true' : 'false'}" title="${item.count} реакций">${escape(item.emoji)} <small>${item.count}</small></button>`).join('');
  }
  function renderMessage(message) {
    const own = message.mine ? ' is-own' : '';
    const reply = message.reply ? `<div class="messenger-reply-preview"><b>${escape(message.reply.sender)}</b>${message.reply.sender_position ? `<small>${escape(message.reply.sender_position)}</small>` : ''}<span>${escape(message.reply.body)}</span></div>` : '';
    const body = message.body ? `<div class="messenger-message-body">${escape(message.body)}</div>` : '';
    const attachments = (message.attachments || []).map(file => `<a class="messenger-attachment" href="${escape(file.url)}"><span>▤</span><span><b>${escape(file.name)}</b><small>${(Number(file.size || 0) / 1024).toFixed(1)} КБ</small></span></a>`).join('');
    const reactions = renderReactions(message);
    const picker = canWrite && !message.is_deleted ? ['👍','❤️','✅','👀'].map(emoji => `<button type="button" data-reaction="${emoji}" data-message-id="${message.id}" aria-label="Реакция ${emoji}">${emoji}</button>`).join('') : '';
    const replyButton = canWrite && !message.is_deleted ? `<button type="button" data-reply-id="${message.id}" data-reply-sender="${escape(message.sender)}" data-reply-position="${escape(message.sender_position || '')}" data-reply-body="${escape(message.body || 'Вложение')}">Ответить</button>` : '';
    const deleteButton = message.can_delete ? `<button type="button" class="messenger-delete-message" data-delete-message="${message.id}">Удалить</button>` : '';
    const deletedClass = message.is_deleted ? ' is-deleted' : '';
    const state = message.mine ? `<span class="messenger-read-state">${message.recipient_count && message.read_count === message.recipient_count ? '✓✓ Прочитано' : '✓ Доставлено'}</span>` : '';
    const initials = message.sender_initials || (message.sender || 'С').split(/\s+/).slice(0,2).map(part => part[0] || '').join('').toUpperCase();
    const position = message.sender_position ? `<small class="messenger-message-position">${escape(message.sender_position)}</small>` : '';
    return `<article class="messenger-message${own}${deletedClass}" data-message-id="${message.id}"><div class="messenger-message-avatar">${escape(initials)}</div><div class="messenger-message-content"><div class="messenger-message-meta"><span class="messenger-message-author"><strong>${escape(message.sender)}</strong>${position}</span><time>${escape(message.created_at)}</time></div>${reply}${body}${attachments ? `<div class="messenger-attachments">${attachments}</div>` : ''}<div class="messenger-message-bottom"><div class="messenger-reactions">${reactions}</div><div class="messenger-message-actions">${replyButton}${deleteButton}<span class="messenger-react-picker">${picker}</span>${state}</div></div></div></article>`;
  }
  function appendMessages(messages) {
    if (!thread || !messages?.length) return;
    const empty = document.getElementById('messenger-empty-thread');
    if (empty) empty.remove();
    const wasNearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
    for (const message of messages) {
      if (thread.querySelector(`[data-message-id="${message.id}"]`)) continue;
      thread.insertAdjacentHTML('beforeend', renderMessage(message));
      lastMessageId = Math.max(lastMessageId, Number(message.id));
    }
    if (wasNearBottom) thread.scrollTop = thread.scrollHeight;
  }
  async function refresh() {
    if (!conversationId || pollBusy) return;
    pollBusy = true;
    try {
      const data = await api(`/staff-messenger/api/conversations/${conversationId}/messages?after=${lastMessageId}`, {method:'GET', headers:{'Accept':'application/json'}});
      appendMessages(data.messages);
      for (const status of (data.status_updates || [])) {
        const article = thread?.querySelector(`article[data-message-id="${status.id}"]`);
        if (status.is_deleted && article) { article.outerHTML = renderMessage(status); continue; }
        const node = article?.querySelector('.messenger-read-state');
        if (node) node.textContent = status.recipient_count && status.read_count === status.recipient_count ? '✓✓ Прочитано' : '✓ Доставлено';
      }
      const typing = document.getElementById('messenger-typing');
      if (typing) typing.textContent = data.typing?.length ? `${data.typing.join(', ')} печатает…` : '';
      if (data.messages?.length) await api(`/staff-messenger/api/conversations/${conversationId}/read`, {method:'POST', body:'{}'});
    } catch (_) { /* A transient poll failure must not interrupt composition. */ }
    finally { pollBusy = false; }
  }
  if (thread && conversationId) {
    thread.scrollTop = thread.scrollHeight;
    api(`/staff-messenger/api/conversations/${conversationId}/read`, {method:'POST', body:'{}'}).catch(() => {});
    window.setInterval(refresh, 3500);
  }

  if (composer && conversationId) {
    composer.addEventListener('submit', async event => {
      event.preventDefault();
      const send = composer.querySelector('[type="submit"]');
      send.disabled = true;
      send.dataset.sending = '1';
      try {
        const form = new FormData(composer);
        const data = await api(`/staff-messenger/api/conversations/${conversationId}/messages`, {method:'POST', body:form});
        appendMessages([data.message]);
        input.value = '';
        resizeComposerInput();
        updateCharCount();
        document.getElementById('messenger-reply-to').value = '';
        document.getElementById('messenger-replying').hidden = true;
        fileInput.value = '';
        renderDraftFiles();
        await api(`/staff-messenger/api/conversations/${conversationId}/read`, {method:'POST', body:'{}'});
      } catch (error) { window.alert(error.message || 'Не удалось отправить сообщение.'); }
      finally { send.dataset.sending = '0'; syncComposerState(); input.focus(); }
    });
    input.addEventListener('input', () => {
      const now = Date.now();
      if (now - lastTypingSent > 2500) {
        lastTypingSent = now;
        api(`/staff-messenger/api/conversations/${conversationId}/typing`, {method:'POST', body:'{}'}).catch(() => {});
      }
    });

  }

  document.addEventListener('click', async event => {
    const reply = event.target.closest('[data-reply-id]');
    if (reply && composer) {
      document.getElementById('messenger-reply-to').value = reply.dataset.replyId;
      document.getElementById('messenger-replying-sender').textContent = reply.dataset.replySender || 'Сотрудник';
      document.getElementById('messenger-replying-position').textContent = reply.dataset.replyPosition || '';
      document.getElementById('messenger-replying-body').textContent = reply.dataset.replyBody || '';
      document.getElementById('messenger-replying').hidden = false;
      input.focus();
      return;
    }
    const deleteButton = event.target.closest('[data-delete-message]');
    if (deleteButton) {
      const messageId = Number(deleteButton.dataset.deleteMessage || 0);
      if (!messageId || !window.confirm('Удалить это сообщение?')) return;
      deleteButton.disabled = true;
      try {
        const data = await api(`/staff-messenger/api/messages/${messageId}/delete`, {method:'POST', body:'{}'});
        const node = thread?.querySelector(`article[data-message-id="${messageId}"]`);
        if (node) node.outerHTML = renderMessage(data.message);
      } catch (error) { window.alert(error.message || 'Не удалось удалить сообщение.'); deleteButton.disabled = false; }
      return;
    }
    const reaction = event.target.closest('[data-reaction][data-message-id]');
    if (reaction && canWrite) {
      // Reaction buttons also carry data-message-id. Never use the generic
      // [data-message-id] selector here: it can select the button itself and
      // replacing it with renderMessage() creates recursively nested messages.
      const messageId = Number(reaction.dataset.messageId || 0);
      const messageElement = reaction.closest('article.messenger-message');
      if (!messageId || !messageElement || Number(messageElement.dataset.messageId) !== messageId) return;
      if (reaction.dataset.pending === '1') return;
      const reactionButtons = messageElement.querySelectorAll(`[data-reaction][data-message-id="${messageId}"]`);
      reactionButtons.forEach(button => { button.dataset.pending = '1'; button.disabled = true; });
      try {
        const data = await api(`/staff-messenger/api/messages/${messageId}/reactions`, {method:'POST', body:JSON.stringify({emoji:reaction.dataset.reaction})});
        let updated = data.message;
        // Compatibility fallback for older servers: fetch the exact message,
        // but update only the reaction strip, preserving the message DOM node.
        if (!updated) {
          const response = await api(`/staff-messenger/api/conversations/${conversationId}/messages?after=${Math.max(0, messageId - 1)}`, {method:'GET'});
          updated = response.messages?.find(m => Number(m.id) === messageId);
        }
        if (updated && messageElement.isConnected) {
          const strip = messageElement.querySelector('.messenger-reactions');
          if (strip) strip.innerHTML = renderReactions(updated);
        }
      } catch (error) {
        console.warn(error);
      } finally {
        messageElement.querySelectorAll(`[data-reaction][data-message-id="${messageId}"]`).forEach(button => {
          delete button.dataset.pending;
          button.disabled = false;
        });
      }
    }
  });
  document.getElementById('messenger-cancel-reply')?.addEventListener('click', () => {
    document.getElementById('messenger-reply-to').value = '';
    document.getElementById('messenger-replying').hidden = true;
  });

  const dialog = document.getElementById('messenger-new-dialog');
  document.querySelectorAll('[data-open-new-chat]').forEach(button => button.addEventListener('click', () => dialog?.showModal()));
  document.querySelectorAll('[data-close-new-chat]').forEach(button => button.addEventListener('click', () => dialog?.close()));
  const kindSelect = document.getElementById('messenger-new-kind');
  const titleWrap = document.getElementById('messenger-group-title-wrap');
  const channelWritersWrap = document.getElementById('messenger-channel-writers-wrap');
  const selectionHint = document.getElementById('messenger-selection-hint');
  const updateKind = () => {
    const kind = kindSelect?.value || 'direct';
    const group = kind === 'group';
    const channel = kind === 'channel';
    if (titleWrap) titleWrap.hidden = !(group || channel);
    if (channelWritersWrap) channelWritersWrap.hidden = !channel;
    if (selectionHint) selectionHint.textContent = group
      ? 'Для группы выберите от двух до девятнадцати сотрудников.'
      : channel ? 'Отметьте всех, кто сможет читать этот канал.'
      : 'Для личного диалога выберите одного сотрудника.';
  };
  kindSelect?.addEventListener('change', updateKind);
  updateKind();
  document.querySelectorAll('input[name="channel_writers"]').forEach(writer => writer.addEventListener('change', () => {
    const participant = document.querySelector(`input[name="participants"][value="${writer.value}"]`);
    if (writer.checked && participant) participant.checked = true;
    if (!writer.checked && participant) participant.dispatchEvent(new Event('change', {bubbles:true}));
  }));
  document.querySelectorAll('input[name="participants"]').forEach(participant => participant.addEventListener('change', () => {
    if (!participant.checked) {
      const writer = document.querySelector(`input[name="channel_writers"][value="${participant.value}"]`);
      if (writer) writer.checked = false;
    }
  }));
  document.getElementById('messenger-new-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const participants = Array.from(document.querySelectorAll('input[name="participants"]:checked')).map(item => Number(item.value));
    try {
      const writerIds = Array.from(document.querySelectorAll('input[name="channel_writers"]:checked')).map(item => Number(item.value));
      const data = await api('/staff-messenger/api/conversations', {method:'POST', body:JSON.stringify({kind:kindSelect.value, title:document.getElementById('messenger-new-title')?.value || '', participant_ids:participants, writer_ids:writerIds})});
      window.location.href = data.url;
    } catch (error) { window.alert(error.message || 'Не удалось создать переписку.'); }
  });

  const search = document.getElementById('messenger-search');
  const searchResults = document.getElementById('messenger-search-results');
  let searchTimer = 0;
  search?.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(async () => {
      const query = search.value.trim();
      if (query.length < 2 || !conversationId) { searchResults.hidden = true; searchResults.innerHTML = ''; return; }
      try {
        const data = await api(`/staff-messenger/search?conversation=${conversationId}&q=${encodeURIComponent(query)}`, {method:'GET'});
        searchResults.innerHTML = data.results.length ? data.results.map(item => `<button type="button" class="messenger-search-result" data-search-message="${item.id}"><b>${escape(item.sender)} · ${escape(item.created_at)}</b>${item.sender_position ? `<small class="messenger-search-position">${escape(item.sender_position)}</small>` : ''}<small>${escape(item.body)}</small></button>`).join('') : '<div class="messenger-search-result"><small>Совпадений не найдено.</small></div>';
        searchResults.hidden = false;
      } catch (_) { searchResults.hidden = true; }
    }, 250);
  });
  searchResults?.addEventListener('click', event => {
    const result = event.target.closest('[data-search-message]');
    if (!result) return;
    const focusMessage = async () => {
      let message = thread?.querySelector(`[data-message-id="${result.dataset.searchMessage}"]`);
      if (!message && thread) {
        try {
          const older = await api(`/staff-messenger/api/conversations/${conversationId}/messages?before=${Number(result.dataset.searchMessage) + 1}`, {method:'GET'});
          const current = new Set(Array.from(thread.querySelectorAll('[data-message-id]')).map(node => node.dataset.messageId));
          const first = thread.querySelector('.messenger-message');
          for (const item of older.messages || []) {
            if (current.has(String(item.id))) continue;
            const wrapper = document.createElement('div');
            wrapper.innerHTML = renderMessage(item);
            if (first) thread.insertBefore(wrapper.firstElementChild, first); else thread.appendChild(wrapper.firstElementChild);
          }
          message = thread.querySelector(`[data-message-id="${result.dataset.searchMessage}"]`);
        } catch (_) {}
      }
      if (message) { message.scrollIntoView({behavior:'smooth', block:'center'}); message.classList.add('is-search-hit'); window.setTimeout(() => message.classList.remove('is-search-hit'), 1400); }
    };
    focusMessage();
  });

  // Notifications are delivered only through the installed Electron client.
  const notificationButton = document.querySelector('[data-enable-notifications]');
  const nativeDesktop = root.dataset.nativeDesktop === '1' && Boolean(window.studsovetDesktop);
  const desktopBridge = nativeDesktop ? window.studsovetDesktop : null;
  let notificationCursor = 0;
  let savedNotificationCursor = 0;
  let notificationPollBusy = false;
  let notificationPollStarted = false;
  let nativeNotificationsEnabled = false;

  const setNotificationLabel = text => {
    if (notificationButton) notificationButton.textContent = text;
  };
  function showDesktopNotice(item) {
    if (!desktopBridge || (document.hasFocus() && Number(item.conversation_id) === conversationId)) return;
    if (!nativeNotificationsEnabled) return;
    desktopBridge.showNotification({
      id: Number(item.id || 0),
      title: item.title || 'StudSovet',
      body: `${item.sender || 'Сотрудник'}: ${item.body || 'Новое сообщение'}`,
      url: item.url || `/messenger/desktop?conversation=${Number(item.conversation_id || 0)}&native=1`
    });
  }
  async function pollDesktopNotifications() {
    if (!desktopBridge || !nativeNotificationsEnabled || notificationPollBusy) return;
    notificationPollBusy = true;
    try {
      const bootstrap = notificationCursor === 0;
      const data = await api(`/staff-messenger/api/notifications?after=${notificationCursor}${bootstrap ? '&bootstrap=1' : ''}`, {method:'GET'});
      if (bootstrap) notificationCursor = Number(data.cursor || 0);
      else {
        notificationCursor = Number(data.cursor || notificationCursor);
        (data.notifications || []).forEach(showDesktopNotice);
      }
      if (notificationCursor > savedNotificationCursor) {
        savedNotificationCursor = notificationCursor;
        desktopBridge.saveNotificationCursor(notificationCursor).catch(() => {});
      }
    } catch (_) { /* transient network errors are retried on the next poll */ }
    finally { notificationPollBusy = false; }
  }
  async function enableDesktopNotifications() {
    if (!desktopBridge) { setNotificationLabel('Доступно только в приложении Windows'); return; }
    try {
      nativeNotificationsEnabled = Boolean(await desktopBridge.enableNotifications());
      if (!nativeNotificationsEnabled) { setNotificationLabel('Системные уведомления недоступны'); return; }
      setNotificationLabel('Уведомления Windows включены ✓');
      startForegroundNotificationPolling();
      await pollDesktopNotifications();
    } catch (error) {
      console.warn('Native notification setup failed:', error);
      setNotificationLabel('Не удалось включить уведомления');
    }
  }
  function startForegroundNotificationPolling() {
    if (notificationPollStarted) return;
    notificationPollStarted = true;
    pollDesktopNotifications();
    window.setInterval(pollDesktopNotifications, 4000);
  }
  notificationButton?.addEventListener('click', enableDesktopNotifications);
  if (desktopBridge) {
    Promise.all([desktopBridge.getNotificationState(), desktopBridge.getNotificationCursor()]).then(([enabled, cursor]) => {
      nativeNotificationsEnabled = Boolean(enabled);
      notificationCursor = Number(cursor || 0);
      savedNotificationCursor = notificationCursor;
      if (nativeNotificationsEnabled) {
        setNotificationLabel('Уведомления Windows включены ✓');
        startForegroundNotificationPolling();
      }
    }).catch(() => {});
  } else {
    setNotificationLabel('Откройте StudSovet Messenger Desktop');
  }
})();
