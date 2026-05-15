(() => {
  const bootstrap = window.CHAT_BOOTSTRAP || {};

  const initialConversationsEl = document.getElementById("initialConversations");
  const activePeerEl = document.getElementById("activePeerData");
  const initialConversations = initialConversationsEl ? JSON.parse(initialConversationsEl.textContent || "[]") : [];
  const activePeer = activePeerEl ? JSON.parse(activePeerEl.textContent || "null") : null;

  const els = {
    connection: document.getElementById("dmConnection"),
    mobileConnection: document.getElementById("dmConnectionMobile"),
    conversationList: document.getElementById("conversationList"),
    conversationEmpty: document.getElementById("conversationEmpty"),
    inboxUnreadCount: document.getElementById("inboxUnreadCount"),
    messages: document.getElementById("messages"),
    composer: document.getElementById("composer"),
    messageInput: document.getElementById("messageInput"),
    sendBtn: document.getElementById("sendBtn"),
    chatTitle: document.getElementById("chatTitle"),
    chatMeta: document.getElementById("chatMeta"),
    peopleSearchInput: document.getElementById("peopleSearchInput"),
    peopleSearchResults: document.getElementById("peopleSearchResults"),
    peopleSearchEmpty: document.getElementById("peopleSearchEmpty"),
    usernameForm: document.getElementById("usernameForm"),
    usernameNotice: document.getElementById("usernameNotice"),
    profileUsername: document.getElementById("profileUsername"),
  };

  const state = {
    socket: null,
    conversations: new Map(),
    messagesByThread: new Map(),
    activePeer,
    activeThreadKey: null,
    reconnectTimer: null,
    searchTimer: null,
    activeOpenSent: false,
  };

  initialConversations.forEach((item) => {
    state.conversations.set(item.peer.user_id, item);
  });

  const threadUrl = (peerId) => `${bootstrap.threadBaseUrl || "/chat/u/"}${encodeURIComponent(peerId)}/`;

  const setConnection = (label, offline = false) => {
    [els.connection, els.mobileConnection].forEach((node) => {
      if (!node) {
        return;
      }
      node.textContent = label;
      node.dataset.state = offline ? "offline" : "online";
    });
  };

  const showNote = (message, isError = false) => {
    if (!els.usernameNotice) {
      return;
    }
    els.usernameNotice.textContent = message;
    els.usernameNotice.dataset.error = isError ? "1" : "0";
    window.setTimeout(() => {
      if (els.usernameNotice?.textContent === message) {
        els.usernameNotice.textContent = "";
      }
    }, 4200);
  };

  const sortedConversations = () => {
    return [...state.conversations.values()].sort((left, right) => {
      const a = new Date(left.last_message?.sent_at || 0).getTime();
      const b = new Date(right.last_message?.sent_at || 0).getTime();
      return b - a;
    });
  };

  const formatTime = (value) => {
    if (!value) {
      return "";
    }
    return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const ensureConversation = (peer, threadKey, messages = []) => {
    const existing = state.conversations.get(peer.user_id);
    const latestMessage = messages.length ? messages[messages.length - 1] : existing?.last_message || null;
    state.conversations.set(peer.user_id, {
      thread_key: threadKey,
      peer: {
        user_id: peer.user_id,
        username: peer.username,
      },
      last_message: latestMessage
        ? {
            body: latestMessage.body || "",
            sender_id: latestMessage.sender_id || "",
            sent_at: latestMessage.sent_at || "",
          }
        : null,
      unread_count: 0,
    });
  };

  const renderConversations = () => {
    if (!els.conversationList) {
      return;
    }

    const items = sortedConversations();
    const unreadTotal = items.reduce((sum, item) => sum + (item.unread_count || 0), 0);
    els.conversationList.innerHTML = "";
    els.conversationEmpty?.classList.toggle("hidden", items.length > 0);
    if (els.inboxUnreadCount) {
      els.inboxUnreadCount.textContent = String(unreadTotal);
    }

    items.forEach((item) => {
      const link = document.createElement("a");
      link.href = threadUrl(item.peer.user_id);
      link.className = "pp-conversation-item";
      if (state.activePeer?.user_id === item.peer.user_id) {
        link.classList.add("pp-conversation-item-active");
      }

      const avatar = document.createElement("span");
      avatar.className = "pp-avatar";
      avatar.textContent = (item.peer.username || "?").slice(0, 1).toUpperCase();

      const text = document.createElement("span");
      text.className = "pp-conversation-text";

      const name = document.createElement("span");
      name.className = "pp-conversation-name";
      name.textContent = item.peer.username;

      const preview = document.createElement("span");
      preview.className = "pp-conversation-preview";
      preview.textContent = item.last_message?.body || "No messages yet";

      text.appendChild(name);
      text.appendChild(preview);

      const meta = document.createElement("span");
      meta.className = "pp-conversation-meta";

      const time = document.createElement("span");
      time.className = "pp-conversation-time";
      time.textContent = formatTime(item.last_message?.sent_at);
      meta.appendChild(time);

      if (item.unread_count > 0) {
        const unread = document.createElement("span");
        unread.className = "pp-unread-count";
        unread.textContent = String(item.unread_count);
        meta.appendChild(unread);
      }

      link.appendChild(avatar);
      link.appendChild(text);
      link.appendChild(meta);
      els.conversationList.appendChild(link);
    });
  };

  const renderMessages = () => {
    if (!els.messages) {
      return;
    }

    els.messages.innerHTML = "";
    if (!state.activeThreadKey) {
      const empty = document.createElement("p");
      empty.className = "pp-empty pp-message-empty";
      empty.textContent = "Opening conversation...";
      els.messages.appendChild(empty);
      return;
    }

    const messages = state.messagesByThread.get(state.activeThreadKey) || [];
    if (!messages.length) {
      const empty = document.createElement("p");
      empty.className = "pp-empty pp-message-empty";
      empty.textContent = "No messages yet. Send the first message.";
      els.messages.appendChild(empty);
      return;
    }

    messages.forEach((message) => {
      const isSelf = message.sender_id === bootstrap.userId;
      const bubble = document.createElement("article");
      bubble.className = `pp-message ${isSelf ? "pp-message-self" : "pp-message-other"}`;

      const body = document.createElement("p");
      body.className = "pp-message-body";
      body.textContent = message.body;

      const stamp = document.createElement("p");
      stamp.className = "pp-message-time";
      stamp.textContent = formatTime(message.sent_at);

      bubble.appendChild(body);
      bubble.appendChild(stamp);
      els.messages.appendChild(bubble);
    });

    els.messages.scrollTop = els.messages.scrollHeight;
  };

  const enableComposer = (enabled) => {
    if (els.messageInput) {
      els.messageInput.disabled = !enabled;
    }
    if (els.sendBtn) {
      els.sendBtn.disabled = !enabled;
    }
  };

  const autoGrowComposer = () => {
    if (!els.messageInput) {
      return;
    }
    els.messageInput.style.height = "auto";
    els.messageInput.style.height = `${Math.min(els.messageInput.scrollHeight, 132)}px`;
  };

  const sendSocket = (payload) => {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    state.socket.send(JSON.stringify(payload));
    return true;
  };

  const requestActiveThread = () => {
    if (!state.activePeer?.user_id) {
      return;
    }
    if (state.activeOpenSent) {
      return;
    }
    els.chatTitle && (els.chatTitle.textContent = state.activePeer.username);
    els.chatMeta && (els.chatMeta.textContent = "Loading messages...");
    enableComposer(true);
    state.activeOpenSent = sendSocket({ action: "open_thread", peer_user_id: state.activePeer.user_id });
  };

  const renderSearchResults = (results) => {
    if (!els.peopleSearchResults) {
      return;
    }

    els.peopleSearchResults.innerHTML = "";
    els.peopleSearchEmpty?.classList.toggle("hidden", results.length > 0);

    results.forEach((result) => {
      const link = document.createElement("a");
      link.href = threadUrl(result.user_id);
      link.className = "pp-person-result";

      const avatar = document.createElement("span");
      avatar.className = "pp-avatar";
      avatar.textContent = (result.username || "?").slice(0, 1).toUpperCase();

      const name = document.createElement("span");
      name.className = "pp-person-name";
      name.textContent = result.username;

      const action = document.createElement("span");
      action.className = "pp-person-action";
      action.textContent = "Chat";

      link.appendChild(avatar);
      link.appendChild(name);
      link.appendChild(action);
      els.peopleSearchResults.appendChild(link);
    });
  };

  const handleSocketMessage = (data) => {
    switch (data.type) {
      case "dm_bootstrap":
        state.conversations.clear();
        data.conversations.forEach((item) => {
          state.conversations.set(item.peer.user_id, item);
        });
        renderConversations();
        requestActiveThread();
        break;
      case "conversations":
        state.conversations.clear();
        data.items.forEach((item) => {
          state.conversations.set(item.peer.user_id, item);
        });
        renderConversations();
        break;
      case "search_results":
        renderSearchResults(data.results || []);
        break;
      case "thread_opened":
        state.activeThreadKey = data.thread_key;
        state.activePeer = data.peer;
        state.messagesByThread.set(data.thread_key, data.messages || []);
        els.chatTitle && (els.chatTitle.textContent = data.peer.username);
        els.chatMeta && (els.chatMeta.textContent = "Private conversation");
        ensureConversation(data.peer, data.thread_key, data.messages || []);
        renderConversations();
        renderMessages();
        sendSocket({ action: "mark_thread_read", peer_user_id: data.peer.user_id });
        break;
      case "dm_message": {
        const payload = data.payload;
        const existing = state.messagesByThread.get(payload.thread_key) || [];
        existing.push(payload);
        state.messagesByThread.set(payload.thread_key, existing);

        const relatedPeerId = payload.sender_id === bootstrap.userId ? payload.recipient_id : payload.sender_id;
        const relatedPeerUsername = payload.sender_id === bootstrap.userId
          ? payload.recipient_username
          : payload.sender_username;

        const existingConversation = state.conversations.get(relatedPeerId);
        state.conversations.set(relatedPeerId, {
          thread_key: payload.thread_key,
          peer: {
            user_id: relatedPeerId,
            username: relatedPeerUsername,
          },
          last_message: {
            body: payload.body,
            sender_id: payload.sender_id,
            sent_at: payload.sent_at,
          },
          unread_count: existingConversation?.unread_count || 0,
        });

        if (state.activeThreadKey === payload.thread_key) {
          renderMessages();
          if (payload.sender_id !== bootstrap.userId) {
            sendSocket({ action: "mark_thread_read", peer_user_id: payload.sender_id });
          }
        }
        renderConversations();
        break;
      }
      case "error":
        if (data.code === "username_taken") {
          showNote("Username already exists.", true);
        } else if (data.code === "user_not_found") {
          showNote("User not found.", true);
        } else {
          showNote(data.message || data.code || "Something went wrong.", true);
        }
        break;
      default:
        break;
    }
  };

  const searchPeople = async (query) => {
    if (!query) {
      renderSearchResults([]);
      return;
    }

    if (sendSocket({ action: "search_users", query })) {
      return;
    }

    const response = await fetch(`/api/users/search/?q=${encodeURIComponent(query)}`);
    const payload = await response.json();
    renderSearchResults(payload.items || []);
  };

  const connectSocket = () => {
    const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
    state.socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws/dm/`);

    state.socket.onopen = () => {
      setConnection("Live", false);
      state.activeOpenSent = false;
      if (state.reconnectTimer) {
        clearTimeout(state.reconnectTimer);
        state.reconnectTimer = null;
      }
      requestActiveThread();
    };

    state.socket.onmessage = (event) => {
      handleSocketMessage(JSON.parse(event.data));
    };

    state.socket.onclose = (event) => {
      if (event.code === 4401 || event.code === 4403) {
        setConnection("Session expired", true);
        showNote("Session expired. Please log in again.", true);
        return;
      }
      setConnection("Offline", true);
      state.reconnectTimer = window.setTimeout(connectSocket, 1500);
    };
  };

  els.composer?.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = els.messageInput?.value.trim();
    if (!message || !state.activePeer) {
      return;
    }

    sendSocket({
      action: "dm_send",
      peer_user_id: state.activePeer.user_id,
      message,
    });

    els.messageInput.value = "";
    autoGrowComposer();
  });

  els.messageInput?.addEventListener("input", autoGrowComposer);

  els.peopleSearchInput?.addEventListener("input", () => {
    const query = els.peopleSearchInput.value.trim();
    if (state.searchTimer) {
      clearTimeout(state.searchTimer);
    }
    state.searchTimer = window.setTimeout(() => {
      searchPeople(query).catch(() => renderSearchResults([]));
    }, 180);
  });

  els.usernameForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(els.usernameForm);

    try {
      const response = await fetch("/api/profile/update/", {
        method: "POST",
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        showNote(payload.message || "Could not update username.", true);
        return;
      }

      const updated = payload.user;
      if (els.profileUsername) {
        els.profileUsername.textContent = updated.username;
      }
      showNote("Username updated.", false);
    } catch {
      showNote("Could not update username.", true);
    }
  });

  renderConversations();
  renderMessages();
  enableComposer(false);
  setConnection("Connecting", false);
  connectSocket();
})();
