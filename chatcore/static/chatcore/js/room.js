(() => {
  const bootstrap = window.CHAT_BOOTSTRAP;
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";

  const roomStatusPill = document.getElementById("roomStatusPill");
  const participantsEl = document.getElementById("participants");
  const joinRequestsPanelEl = document.getElementById("joinRequestsPanel");
  const joinRequestsEl = document.getElementById("joinRequests");
  const messagesEl = document.getElementById("messages");
  const composerEl = document.getElementById("composer");
  const messageInputEl = document.getElementById("messageInput");
  const discoverableToggleEl = document.getElementById("discoverableToggle");
  const typingIndicatorEl = document.getElementById("typingIndicator");
  const replyPreviewEl = document.getElementById("replyPreview");
  const replyToNameEl = document.getElementById("replyToName");
  const replyToBodyEl = document.getElementById("replyToBody");
  const cancelReplyBtn = document.getElementById("cancelReplyBtn");

  const state = {
    socket: null,
    room: null,
    requests: new Map(),
    messages: new Map(),
    typingUsers: new Map(),
    ownerId: null,
    replyTo: null,
    typingSent: false,
    typingTimer: null,
  };

  const setStatus = (text, isOffline = false) => {
    roomStatusPill.textContent = text;
    roomStatusPill.dataset.state = isOffline ? "offline" : "online";
  };

  const autoGrow = () => {
    messageInputEl.style.height = "auto";
    messageInputEl.style.height = `${Math.min(messageInputEl.scrollHeight, 130)}px`;
  };

  const showSystemNote = (text) => {
    const note = document.createElement("p");
    note.className = "system-note";
    note.textContent = text;
    messagesEl.appendChild(note);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  };

  const setReplyTarget = (msg) => {
    state.replyTo = {
      id: msg.id,
      sender_name: msg.sender_name,
      body: msg.body,
    };
    replyToNameEl.textContent = `Replying to ${msg.sender_name}`;
    replyToBodyEl.textContent = msg.body.length > 120 ? `${msg.body.slice(0, 120)}...` : msg.body;
    replyPreviewEl.classList.remove("hidden");
    messageInputEl.focus();
  };

  const clearReplyTarget = () => {
    state.replyTo = null;
    replyPreviewEl.classList.add("hidden");
    replyToNameEl.textContent = "";
    replyToBodyEl.textContent = "";
  };

  const renderParticipants = () => {
    if (!state.room) {
      participantsEl.innerHTML = "";
      return;
    }

    participantsEl.innerHTML = "";
    state.room.participants.forEach((user) => {
      const isOwner = user.user_id === state.room.owner_id;
      const badge = document.createElement("span");
      badge.className = `participant-chip ${user.is_online ? "participant-chip-online" : "participant-chip-offline"}`;
      badge.textContent = `${user.display_name}${isOwner ? " (host)" : ""}${user.is_online ? " - online" : " - offline"}`;
      participantsEl.appendChild(badge);
    });
  };

  const renderJoinRequests = () => {
    joinRequestsEl.innerHTML = "";
    const isParticipant = state.room?.participants?.some((p) => p.user_id === bootstrap.userId);
    const roomIsOpen = !state.room?.is_full;
    joinRequestsPanelEl.classList.toggle("hidden", !isParticipant || !roomIsOpen || !state.requests.size);

    if (!isParticipant || !roomIsOpen) {
      return;
    }

    state.requests.forEach((request) => {
      const box = document.createElement("div");
      box.className = "request-card";

      const label = document.createElement("p");
      label.className = "request-title";
      label.textContent = `${request.requester_name} wants to join this room.`;

      const actions = document.createElement("div");
      actions.className = "request-actions";

      const approveBtn = document.createElement("button");
      approveBtn.className = "btn-primary approve-btn";
      approveBtn.dataset.requestId = request.request_id;
      approveBtn.innerHTML = '<span class="btn-main">Approve</span>';

      const rejectBtn = document.createElement("button");
      rejectBtn.className = "btn-secondary reject-btn";
      rejectBtn.dataset.requestId = request.request_id;
      rejectBtn.textContent = "Reject";

      actions.appendChild(approveBtn);
      actions.appendChild(rejectBtn);
      box.appendChild(label);
      box.appendChild(actions);
      joinRequestsEl.appendChild(box);
    });

    joinRequestsEl.querySelectorAll(".approve-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.socket?.send(
          JSON.stringify({
            action: "join_decision",
            request_id: btn.dataset.requestId,
            approved: true,
          })
        );
      });
    });

    joinRequestsEl.querySelectorAll(".reject-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.socket?.send(
          JSON.stringify({
            action: "join_decision",
            request_id: btn.dataset.requestId,
            approved: false,
          })
        );
      });
    });
  };

  const bindSwipeReply = (wrapper, msg, isSelf) => {
    if (isSelf) {
      return;
    }

    let startX = 0;
    let startY = 0;
    let dx = 0;
    let active = false;

    wrapper.addEventListener(
      "touchstart",
      (event) => {
        if (!event.touches.length) {
          return;
        }
        startX = event.touches[0].clientX;
        startY = event.touches[0].clientY;
        dx = 0;
        active = true;
      },
      { passive: true }
    );

    wrapper.addEventListener(
      "touchmove",
      (event) => {
        if (!active || !event.touches.length) {
          return;
        }

        dx = event.touches[0].clientX - startX;
        const dy = event.touches[0].clientY - startY;

        if (dx > 0 && Math.abs(dx) > Math.abs(dy)) {
          wrapper.classList.add("message-swipe-active");
          wrapper.style.transform = `translateX(${Math.min(dx, 48)}px)`;
        }
      },
      { passive: true }
    );

    wrapper.addEventListener("touchend", () => {
      if (!active) {
        return;
      }
      active = false;

      if (dx > 36) {
        setReplyTarget(msg);
      }

      wrapper.classList.remove("message-swipe-active");
      wrapper.style.transform = "translateX(0)";
    });

    wrapper.addEventListener("dblclick", () => setReplyTarget(msg));
  };

  const renderMessage = (msg, isSelf) => {
    const wrapper = document.createElement("article");
    wrapper.className = `message-bubble ${isSelf ? "message-self" : "message-other"}`;
    wrapper.dataset.messageId = msg.id;

    if (msg.reply_to) {
      const quote = document.createElement("div");
      quote.className = "reply-quote";

      const quoteName = document.createElement("p");
      quoteName.className = "text-[11px] font-semibold text-[#395308]";
      quoteName.textContent = msg.reply_to.sender_name;

      const quoteBody = document.createElement("p");
      quoteBody.className = "text-xs text-slate-600";
      quoteBody.textContent = msg.reply_to.body;

      quote.appendChild(quoteName);
      quote.appendChild(quoteBody);
      wrapper.appendChild(quote);
    }

    const text = document.createElement("p");
    text.className = "message-text";
    text.textContent = msg.body;
    wrapper.appendChild(text);

    const metaRow = document.createElement("div");
    metaRow.className = "message-meta-row";

    const time = document.createElement("span");
    time.className = "text-[11px] text-slate-500";
    time.textContent = new Date(msg.sent_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    metaRow.appendChild(time);

    if (isSelf) {
      const ticks = document.createElement("span");
      ticks.className = "tick tick-gray";
      ticks.dataset.statusFor = msg.id;
      ticks.dataset.status = "delivered";
      ticks.textContent = "✓✓";
      metaRow.appendChild(ticks);
    }

    wrapper.appendChild(metaRow);
    bindSwipeReply(wrapper, msg, isSelf);

    messagesEl.appendChild(wrapper);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  };

  const updateMessageStatus = (messageId, status) => {
    const el = messagesEl.querySelector(`[data-status-for="${messageId}"]`);
    if (!el) {
      return;
    }

    if (status === "read") {
      el.classList.remove("tick-gray");
      el.classList.add("tick-blue");
      el.dataset.status = "read";
      el.textContent = "✓✓";
      return;
    }

    el.classList.remove("tick-blue");
    el.classList.add("tick-gray");
    el.dataset.status = "delivered";
    el.textContent = "✓✓";
  };

  const sendTyping = (isTyping) => {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    if (state.typingSent === isTyping) {
      return;
    }
    state.typingSent = isTyping;
    state.socket.send(JSON.stringify({ action: "typing", is_typing: isTyping }));
  };

  const scheduleTypingStop = () => {
    if (state.typingTimer) {
      clearTimeout(state.typingTimer);
    }
    state.typingTimer = window.setTimeout(() => {
      sendTyping(false);
    }, 1100);
  };

  const renderTypingIndicator = () => {
    const typingUsers = [...state.typingUsers.values()];
    if (!typingUsers.length) {
      typingIndicatorEl.textContent = "";
      return;
    }

    const name = typingUsers[0].display_name;
    typingIndicatorEl.textContent = `${name} is typing...`;
  };

  const handlePayload = (data) => {
    switch (data.type) {
      case "room_init":
        state.room = data.room;
        state.ownerId = data.room.owner_id;
        setStatus(data.room.online_count > 1 ? "Live" : "Waiting", false);
        discoverableToggleEl.checked = !!data.room.discoverable_when_single;
        renderParticipants();
        renderJoinRequests();
        break;
      case "room_presence":
        state.room = data.room;
        setStatus(data.room.online_count > 1 ? "Live" : "Waiting", false);
        discoverableToggleEl.checked = !!data.room.discoverable_when_single;
        renderParticipants();
        renderJoinRequests();
        break;
      case "participant_joined":
        if (data.payload.user_id !== bootstrap.userId) {
          showSystemNote(`${data.payload.display_name} joined`);
        }
        break;
      case "participant_left":
        if (data.payload.user_id !== bootstrap.userId) {
          state.typingUsers.delete(data.payload.user_id);
          renderTypingIndicator();
          showSystemNote(`${data.payload.display_name} left`);
        }
        break;
      case "typing":
        if (data.payload.user_id === bootstrap.userId) {
          break;
        }
        if (data.payload.is_typing) {
          state.typingUsers.set(data.payload.user_id, data.payload);
        } else {
          state.typingUsers.delete(data.payload.user_id);
        }
        renderTypingIndicator();
        break;
      case "join_requested":
        state.requests.set(data.payload.request_id, data.payload);
        renderJoinRequests();
        break;
      case "join_decision_applied":
        state.requests.delete(data.payload.request_id);
        renderJoinRequests();
        break;
      case "message_new":
        state.messages.set(data.payload.id, data.payload);
        renderMessage(data.payload, data.is_self);
        if (!data.is_self) {
          state.typingUsers.delete(data.payload.sender_id);
          renderTypingIndicator();
          state.socket?.send(
            JSON.stringify({
              action: "message_read",
              message_id: data.payload.id,
            })
          );
        }
        break;
      case "message_status":
        if (data.status === "delivered" || data.status === "read") {
          updateMessageStatus(data.message_id, data.status);
        }
        break;
      case "error":
        setStatus("Error", true);
        break;
      default:
        break;
    }
  };

  const connectSocket = () => {
    state.socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws/room/${bootstrap.roomId}/`);

    state.socket.onopen = () => {
      setStatus("Connected", false);
      sendTyping(false);
    };
    state.socket.onmessage = (event) => handlePayload(JSON.parse(event.data));
    state.socket.onclose = () => {
      setStatus("Offline", true);
      state.typingUsers.clear();
      renderTypingIndicator();
      window.setTimeout(connectSocket, 1200);
    };
  };

  composerEl.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = messageInputEl.value.trim();
    if (!message) {
      return;
    }

    state.socket?.send(
      JSON.stringify({
        action: "message_send",
        message,
        reply_to: state.replyTo,
      })
    );

    messageInputEl.value = "";
    autoGrow();
    clearReplyTarget();
    sendTyping(false);
  });

  messageInputEl.addEventListener("input", () => {
    autoGrow();
    const hasText = messageInputEl.value.trim().length > 0;
    sendTyping(hasText);
    if (hasText) {
      scheduleTypingStop();
    } else {
      sendTyping(false);
    }
  });

  messageInputEl.addEventListener("blur", () => sendTyping(false));

  discoverableToggleEl.addEventListener("change", () => {
    state.socket?.send(
      JSON.stringify({
        action: "set_discoverable_single",
        discoverable_when_single: discoverableToggleEl.checked,
      })
    );
  });

  cancelReplyBtn.addEventListener("click", clearReplyTarget);

  setStatus("Connecting", false);
  connectSocket();
})();
