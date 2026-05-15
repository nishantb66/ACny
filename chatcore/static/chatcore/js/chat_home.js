(() => {
  const bootstrap = window.CHAT_BOOTSTRAP;

  const connectionEl = document.getElementById("dmConnection");
  const conversationListEl = document.getElementById("conversationList");
  const conversationEmptyEl = document.getElementById("conversationEmpty");
  const messagesEl = document.getElementById("messages");
  const composerEl = document.getElementById("composer");
  const messageInputEl = document.getElementById("messageInput");
  const sendBtnEl = document.getElementById("sendBtn");
  const chatTitleEl = document.getElementById("chatTitle");
  const chatMetaEl = document.getElementById("chatMeta");
  const searchInputEl = document.getElementById("searchInput");
  const searchResultsEl = document.getElementById("searchResults");
  const usernameFormEl = document.getElementById("usernameForm");
  const usernameInputEl = document.getElementById("usernameInput");
  const usernameNoticeEl = document.getElementById("usernameNotice");
  const profileUsernameEl = document.getElementById("profileUsername");
  const chatLayoutEl = document.getElementById("ppChatLayout");
  const mobileBackBtnEl = document.getElementById("mobileBackBtn");

  const initialConversationsEl = document.getElementById("initialConversations");
  const initialConversations = initialConversationsEl ? JSON.parse(initialConversationsEl.textContent || "[]") : [];

  const state = {
    socket: null,
    conversations: new Map(),
    messagesByThread: new Map(),
    activePeer: null,
    activeThreadKey: null,
    reconnectTimer: null,
    searchTimer: null,
    bootstrapped: false,
  };

  initialConversations.forEach((item) => {
    state.conversations.set(item.peer.user_id, item);
  });

  const setConnection = (label, offline = false) => {
    connectionEl.textContent = label;
    connectionEl.dataset.state = offline ? "offline" : "online";
  };

  const showNote = (message, isError = false) => {
    usernameNoticeEl.textContent = message;
    usernameNoticeEl.dataset.error = isError ? "1" : "0";
    window.setTimeout(() => {
      if (usernameNoticeEl.textContent === message) {
        usernameNoticeEl.textContent = "";
      }
    }, 4200);
  };

  const autoGrowComposer = () => {
    messageInputEl.style.height = "auto";
    messageInputEl.style.height = `${Math.min(messageInputEl.scrollHeight, 132)}px`;
  };

  const sortedConversations = () => {
    return [...state.conversations.values()].sort((left, right) => {
      const a = new Date(left.last_message?.sent_at || 0).getTime();
      const b = new Date(right.last_message?.sent_at || 0).getTime();
      return b - a;
    });
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
    const items = sortedConversations();
    conversationListEl.innerHTML = "";

    conversationEmptyEl.classList.toggle("hidden", items.length > 0);

    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pp-conversation-item";
      button.dataset.peerId = item.peer.user_id;
      if (state.activePeer?.user_id === item.peer.user_id) {
        button.classList.add("pp-conversation-item-active");
      }

      const name = document.createElement("p");
      name.className = "pp-conversation-name";
      name.textContent = item.peer.username;

      const preview = document.createElement("p");
      preview.className = "pp-conversation-preview";
      preview.textContent = item.last_message?.body || "No messages yet";

      const meta = document.createElement("div");
      meta.className = "pp-conversation-meta";

      const time = document.createElement("span");
      time.className = "pp-conversation-time";
      time.textContent = item.last_message?.sent_at
        ? new Date(item.last_message.sent_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "";
      meta.appendChild(time);

      if (item.unread_count > 0) {
        const unread = document.createElement("span");
        unread.className = "pp-unread-count";
        unread.textContent = String(item.unread_count);
        meta.appendChild(unread);
      }

      button.appendChild(name);
      button.appendChild(preview);
      button.appendChild(meta);
      conversationListEl.appendChild(button);

      button.addEventListener("click", () => openThread(item.peer.user_id, item.peer.username));
    });
  };

  const renderMessages = () => {
    messagesEl.innerHTML = "";
    if (!state.activeThreadKey) {
      const empty = document.createElement("p");
      empty.className = "pp-empty";
      empty.textContent = "Pick a conversation to start messaging.";
      messagesEl.appendChild(empty);
      return;
    }

    const messages = state.messagesByThread.get(state.activeThreadKey) || [];
    if (!messages.length) {
      const empty = document.createElement("p");
      empty.className = "pp-empty";
      empty.textContent = "No messages yet. Send the first message.";
      messagesEl.appendChild(empty);
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
      stamp.textContent = message.sent_at
        ? new Date(message.sent_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "";

      bubble.appendChild(body);
      bubble.appendChild(stamp);
      messagesEl.appendChild(bubble);
    });

    messagesEl.scrollTop = messagesEl.scrollHeight;
  };

  const enableComposer = (enabled) => {
    messageInputEl.disabled = !enabled;
    sendBtnEl.disabled = !enabled;
  };

  const sendSocket = (payload) => {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    state.socket.send(JSON.stringify(payload));
  };

  const openThread = (peerId, peerUsername) => {
    state.activePeer = {
      user_id: peerId,
      username: peerUsername,
    };
    chatTitleEl.textContent = peerUsername;
    chatMetaEl.textContent = "Loading messages...";
    enableComposer(true);
    sendSocket({ action: "open_thread", peer_user_id: peerId });
    chatLayoutEl.classList.add("pp-thread-active");
    renderConversations();
  };

  const handleSocketMessage = (data) => {
    switch (data.type) {
      case "dm_bootstrap":
        state.conversations.clear();
        data.conversations.forEach((item) => {
          state.conversations.set(item.peer.user_id, item);
        });
        renderConversations();
        if (!state.bootstrapped) {
          state.bootstrapped = true;
          const first = sortedConversations()[0];
          if (first && !state.activePeer) {
            openThread(first.peer.user_id, first.peer.username);
          }
        }
        break;
      case "conversations":
        state.conversations.clear();
        data.items.forEach((item) => {
          state.conversations.set(item.peer.user_id, item);
        });
        renderConversations();
        break;
      case "search_results": {
        renderSearchResults(data.results || []);
        break;
      }
      case "thread_opened": {
        state.activeThreadKey = data.thread_key;
        state.activePeer = data.peer;
        state.messagesByThread.set(data.thread_key, data.messages || []);
        chatTitleEl.textContent = data.peer.username;
        chatMetaEl.textContent = "Private messages are end-user persisted.";
        ensureConversation(data.peer, data.thread_key, data.messages || []);
        renderConversations();
        renderMessages();
        sendSocket({ action: "mark_thread_read", peer_user_id: data.peer.user_id });
        break;
      }
      case "dm_message": {
        const payload = data.payload;
        const thread = payload.thread_key;
        const existing = state.messagesByThread.get(thread) || [];
        existing.push(payload);
        state.messagesByThread.set(thread, existing);

        const relatedPeerId = payload.sender_id === bootstrap.userId ? payload.recipient_id : payload.sender_id;
        const relatedPeerUsername = payload.sender_id === bootstrap.userId
          ? payload.recipient_username
          : payload.sender_username;

        const existingConversation = state.conversations.get(relatedPeerId);
        state.conversations.set(relatedPeerId, {
          thread_key: thread,
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

        if (state.activeThreadKey === thread) {
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

  const renderSearchResults = (results) => {
    searchResultsEl.innerHTML = "";
    if (!results.length) {
      searchResultsEl.classList.add("hidden");
      return;
    }

    results.forEach((result) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pp-search-item";
      button.textContent = result.username;
      button.addEventListener("click", () => {
        searchInputEl.value = result.username;
        searchResultsEl.classList.add("hidden");
        openThread(result.user_id, result.username);
      });
      searchResultsEl.appendChild(button);
    });

    searchResultsEl.classList.remove("hidden");
  };

  const connectSocket = () => {
    const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
    state.socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws/dm/`);

    state.socket.onopen = () => {
      setConnection("Live", false);
      if (state.reconnectTimer) {
        clearTimeout(state.reconnectTimer);
        state.reconnectTimer = null;
      }
      if (state.activePeer?.user_id) {
        sendSocket({ action: "open_thread", peer_user_id: state.activePeer.user_id });
      }
    };

    state.socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      handleSocketMessage(payload);
    };

    state.socket.onclose = (event) => {
      if (event.code === 4401 || event.code === 4403) {
        setConnection("Session expired", true);
        showNote("Session expired. Please log in again.", true);
        return;
      }
      setConnection("Offline", true);
      state.reconnectTimer = window.setTimeout(connectSocket, 1200);
    };
  };

  composerEl.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = messageInputEl.value.trim();
    if (!message || !state.activePeer) {
      return;
    }

    sendSocket({
      action: "dm_send",
      peer_user_id: state.activePeer.user_id,
      message,
    });

    messageInputEl.value = "";
    autoGrowComposer();
  });

  messageInputEl.addEventListener("input", autoGrowComposer);

  searchInputEl.addEventListener("input", () => {
    const query = searchInputEl.value.trim();
    if (state.searchTimer) {
      clearTimeout(state.searchTimer);
    }

    if (!query) {
      searchResultsEl.classList.add("hidden");
      searchResultsEl.innerHTML = "";
      return;
    }

    state.searchTimer = window.setTimeout(() => {
      sendSocket({ action: "search_users", query });
    }, 220);
  });

  document.addEventListener("click", (event) => {
    if (!searchResultsEl.contains(event.target) && event.target !== searchInputEl) {
      searchResultsEl.classList.add("hidden");
    }
  });

  usernameFormEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(usernameFormEl);

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
      profileUsernameEl.textContent = updated.username;
      chatMetaEl.textContent = "Username updated successfully.";
      showNote("Username updated.", false);
    } catch {
      showNote("Could not update username.", true);
    }
  });

  mobileBackBtnEl.addEventListener("click", () => {
    chatLayoutEl.classList.remove("pp-thread-active");
  });

  renderConversations();
  renderMessages();
  enableComposer(false);
  setConnection("Connecting", false);
  connectSocket();
})();
