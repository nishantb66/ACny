(() => {
  const bootstrap = window.CHAT_BOOTSTRAP;
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";

  const roomStatusPill = document.getElementById("roomStatusPill");
  const roomStatusPillMobile = document.getElementById("roomStatusPillMobile");
  const inviteWhatsappBtn = document.getElementById("inviteWhatsappBtn");
  const participantsEl = document.getElementById("participants");
  const joinRequestsPanelEl = document.getElementById("joinRequestsPanel");
  const joinRequestsEl = document.getElementById("joinRequests");
  const messagesEl = document.getElementById("messages");
  const composerEl = document.getElementById("composer");
  const messageInputEl = document.getElementById("messageInput");
  const openImageComposerBtn = document.getElementById("openImageComposerBtn");
  const discoverableToggleEl = document.getElementById("discoverableToggle");
  const typingIndicatorEl = document.getElementById("typingIndicator");
  const replyPreviewEl = document.getElementById("replyPreview");
  const replyToNameEl = document.getElementById("replyToName");
  const replyToBodyEl = document.getElementById("replyToBody");
  const cancelReplyBtn = document.getElementById("cancelReplyBtn");

  const imageInputEl = document.getElementById("imageInput");
  const imagePickerBtn = document.getElementById("imagePickerBtn");
  const closeImageComposerBtn = document.getElementById("closeImageComposerBtn");
  const sendImageBtn = document.getElementById("sendImageBtn");
  const imageModeSelectEl = document.getElementById("imageModeSelect");
  const imageSecondsWrapEl = document.getElementById("imageSecondsWrap");
  const imageSecondsInputEl = document.getElementById("imageSecondsInput");
  const selectedImageMetaEl = document.getElementById("selectedImageMeta");
  const imageComposerModalEl = document.getElementById("imageComposerModal");

  const oneTimeImageModalEl = document.getElementById("oneTimeImageModal");
  const oneTimeImageViewEl = document.getElementById("oneTimeImageView");
  const oneTimeImageTimerEl = document.getElementById("oneTimeImageTimer");
  const closeOneTimeImageBtn = document.getElementById("closeOneTimeImageBtn");
  const maxImageUploadBytes = 5 * 1024 * 1024;

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
    selectedImage: null,
    activeImageView: null,
  };

  const setStatus = (text, isOffline = false) => {
    if (roomStatusPill) {
      roomStatusPill.textContent = text;
      roomStatusPill.dataset.state = isOffline ? "offline" : "online";
    }
    if (roomStatusPillMobile) {
      roomStatusPillMobile.textContent = text;
      roomStatusPillMobile.dataset.state = isOffline ? "offline" : "online";
    }
  };

  const getCookieValue = (name) => {
    const raw = document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(`${name}=`));
    if (!raw) {
      return "";
    }
    return decodeURIComponent(raw.slice(name.length + 1));
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

  const previewTextForMessage = (msg) => {
    if (msg.message_type === "one_time_image") {
      return msg.preview_text || "One-time image";
    }
    return msg.body || "";
  };

  const formatViewMode = (msg) => {
    if (msg.view_mode === "timed_one_time_seen") {
      return `${msg.view_seconds || 0}s timed one-time image`;
    }
    return "One-time image";
  };

  const setReplyTarget = (msg) => {
    state.replyTo = {
      id: msg.id,
      sender_name: msg.sender_name,
      body: previewTextForMessage(msg),
    };
    replyToNameEl.textContent = `Replying to ${msg.sender_name}`;
    const preview = previewTextForMessage(msg);
    replyToBodyEl.textContent = preview.length > 120 ? `${preview.slice(0, 120)}...` : preview;
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

  const bindReplyGesture = (wrapper, msg, isSelf) => {
    if (isSelf) {
      return;
    }

    let startX = 0;
    let startY = 0;
    let moved = false;
    let lastTapAt = 0;
    const maxTapTravel = 10;
    const maxTapGapMs = 330;

    wrapper.addEventListener(
      "touchstart",
      (event) => {
        if (!event.touches.length) {
          return;
        }
        startX = event.touches[0].clientX;
        startY = event.touches[0].clientY;
        moved = false;
      },
      { passive: true }
    );

    wrapper.addEventListener(
      "touchmove",
      (event) => {
        if (!event.touches.length) {
          return;
        }
        const dx = event.touches[0].clientX - startX;
        const dy = event.touches[0].clientY - startY;
        if (Math.abs(dx) > maxTapTravel || Math.abs(dy) > maxTapTravel) {
          moved = true;
        }
      },
      { passive: true }
    );

    wrapper.addEventListener("touchend", (event) => {
      if (moved) {
        return;
      }
      if (event.target.closest("button, a, input, textarea, select, label")) {
        return;
      }
      const now = Date.now();
      if (now - lastTapAt <= maxTapGapMs) {
        setReplyTarget(msg);
        lastTapAt = 0;
        return;
      }
      lastTapAt = now;
    });

    wrapper.addEventListener("dblclick", () => setReplyTarget(msg));
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

  const updateImageMessageVisual = (msg) => {
    const wrapper = messagesEl.querySelector(`[data-message-id="${msg.id}"]`);
    if (!wrapper) {
      return;
    }

    const openBtn = wrapper.querySelector(".message-image-btn");
    const statusEl = wrapper.querySelector(".message-image-status");
    const isSelf = msg.sender_id === bootstrap.userId;

    if (statusEl) {
      if (msg.is_opened) {
        const openedAt = msg.opened_at
          ? new Date(msg.opened_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
          : "now";
        statusEl.textContent = isSelf ? `Opened at ${openedAt}` : "Opened";
      } else {
        statusEl.textContent = isSelf ? "Waiting for recipient to open" : "Not opened yet";
      }
    }

    if (openBtn) {
      openBtn.disabled = isSelf || !!msg.is_opened;
      openBtn.textContent = msg.is_opened ? "Opened" : "Open Image";
    }
  };

  const renderMessage = (msg, isSelf) => {
    const wrapper = document.createElement("article");
    wrapper.className = `message-bubble ${isSelf ? "message-self" : "message-other"}`;
    wrapper.dataset.messageId = msg.id;

    if (msg.reply_to) {
      const quote = document.createElement("div");
      quote.className = "reply-quote";

      const quoteName = document.createElement("p");
      quoteName.className = "reply-quote-name";
      quoteName.textContent = msg.reply_to.sender_name;

      const quoteBody = document.createElement("p");
      quoteBody.className = "reply-quote-body";
      quoteBody.textContent = msg.reply_to.body;

      quote.appendChild(quoteName);
      quote.appendChild(quoteBody);
      wrapper.appendChild(quote);
    }

    if (msg.message_type === "one_time_image") {
      const imageCard = document.createElement("div");
      imageCard.className = "message-image-card";

      const caption = document.createElement("p");
      caption.className = "message-image-caption";
      caption.textContent = formatViewMode(msg);
      imageCard.appendChild(caption);

      const openBtn = document.createElement("button");
      openBtn.type = "button";
      openBtn.className = "message-image-btn";
      openBtn.textContent = "Open Image";
      openBtn.disabled = isSelf || !!msg.is_opened;
      openBtn.addEventListener("click", () => {
        state.socket?.send(
          JSON.stringify({
            action: "image_open",
            message_id: msg.id,
          })
        );
      });
      imageCard.appendChild(openBtn);

      const statusText = document.createElement("p");
      statusText.className = "message-image-status";
      statusText.textContent = isSelf ? "Waiting for recipient to open" : "Not opened yet";
      imageCard.appendChild(statusText);

      wrapper.appendChild(imageCard);
    } else {
      const text = document.createElement("p");
      text.className = "message-text";
      text.textContent = msg.body;
      wrapper.appendChild(text);
    }

    const metaRow = document.createElement("div");
    metaRow.className = "message-meta-row";

    const time = document.createElement("span");
    time.className = "message-time";
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
    bindReplyGesture(wrapper, msg, isSelf);

    messagesEl.appendChild(wrapper);
    if (msg.message_type === "one_time_image") {
      updateImageMessageVisual(msg);
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
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

  const resetSelectedImage = () => {
    state.selectedImage = null;
    imageInputEl.value = "";
    selectedImageMetaEl.textContent = "";
  };

  const refreshSelectedImageMeta = () => {
    if (!state.selectedImage) {
      selectedImageMetaEl.textContent = "";
      return;
    }
    const mode = imageModeSelectEl.value;
    if (mode === "timed_one_time_seen") {
      selectedImageMetaEl.textContent = `${state.selectedImage.name} • ${imageSecondsInputEl.value || 0}s timed one-time`;
      return;
    }
    selectedImageMetaEl.textContent = `${state.selectedImage.name} • one-time seen`;
  };

  const updateImageModeUI = () => {
    const timed = imageModeSelectEl.value === "timed_one_time_seen";
    imageSecondsWrapEl.classList.toggle("hidden", !timed);
    refreshSelectedImageMeta();
  };

  const openImageComposerModal = () => {
    imageComposerModalEl.classList.remove("hidden");
    updateImageModeUI();
  };

  const closeImageComposerModal = () => {
    imageComposerModalEl.classList.add("hidden");
  };

  const stopActiveImageTimer = () => {
    if (state.activeImageView?.timerId) {
      clearInterval(state.activeImageView.timerId);
    }
  };

  const closeImageModal = (consume = true) => {
    if (!state.activeImageView) {
      return;
    }

    const messageId = state.activeImageView.messageId;
    stopActiveImageTimer();
    state.activeImageView = null;

    oneTimeImageModalEl.classList.add("hidden");
    oneTimeImageViewEl.removeAttribute("src");
    oneTimeImageTimerEl.textContent = "";

    if (consume && state.socket?.readyState === WebSocket.OPEN) {
      const localMessage = state.messages.get(messageId);
      if (localMessage && !localMessage.is_opened) {
        localMessage.is_opened = true;
        localMessage.opened_at = new Date().toISOString();
        state.messages.set(messageId, localMessage);
        updateImageMessageVisual(localMessage);
      }
      state.socket.send(
        JSON.stringify({
          action: "image_close",
          message_id: messageId,
        })
      );
    }
  };

  const openImageModal = (viewData) => {
    if (state.activeImageView) {
      closeImageModal(true);
    }
    stopActiveImageTimer();
    state.activeImageView = {
      messageId: viewData.message_id,
      timerId: null,
      remainingMs: (viewData.view_seconds || 0) * 1000,
      mode: viewData.view_mode,
    };

    oneTimeImageViewEl.src = viewData.image_data_url;
    oneTimeImageModalEl.classList.remove("hidden");

    if (viewData.view_mode === "timed_one_time_seen") {
      const updateTimerText = () => {
        if (!state.activeImageView) {
          return;
        }
        const seconds = Math.max(0, Math.ceil(state.activeImageView.remainingMs / 1000));
        oneTimeImageTimerEl.textContent = `${seconds}s remaining`;
      };
      updateTimerText();
      state.activeImageView.timerId = window.setInterval(() => {
        if (!state.activeImageView) {
          return;
        }
        state.activeImageView.remainingMs -= 200;
        updateTimerText();
        if (state.activeImageView.remainingMs <= 0) {
          closeImageModal(true);
        }
      }, 200);
      return;
    }

    oneTimeImageTimerEl.textContent = "Close to mark as opened";
  };

  const handlePayload = (data) => {
    switch (data.type) {
      case "room_init":
        state.room = data.room;
        state.ownerId = data.room.owner_id;
        setStatus(data.room.online_count > 1 ? "Live" : "Waiting", false);
        discoverableToggleEl.checked = !!data.room.discoverable_when_single;
        state.messages.clear();
        messagesEl.innerHTML = "";
        (data.messages || []).forEach((message) => {
          state.messages.set(message.id, message);
          renderMessage(message, message.sender_id === bootstrap.userId);
        });
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
        }
        if (!data.is_self && data.payload.message_type !== "one_time_image") {
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
      case "image_open_result":
        if (data.message) {
          state.messages.set(data.message.id, data.message);
          updateImageMessageVisual(data.message);
        }
        if (data.view) {
          openImageModal(data.view);
        }
        break;
      case "image_opened":
        state.messages.set(data.payload.id, data.payload);
        updateImageMessageVisual(data.payload);
        if (state.activeImageView?.messageId === data.payload.id) {
          closeImageModal(false);
        }
        break;
      case "error":
        if (data.code === "image_already_opened") {
          showSystemNote("Image already opened.");
        } else if (data.code === "image_view_in_progress") {
          showSystemNote("Image is currently being viewed.");
        } else if (data.code === "invalid_view_seconds") {
          showSystemNote("Set a time between 1 and 60 seconds.");
        } else if (data.code === "invalid_image_payload") {
          showSystemNote("Could not send image. Use png/jpg/webp/gif up to 5MB.");
        }
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
  openImageComposerBtn.addEventListener("click", openImageComposerModal);
  closeImageComposerBtn.addEventListener("click", closeImageComposerModal);

  inviteWhatsappBtn.addEventListener("click", async () => {
    inviteWhatsappBtn.disabled = true;
    const originalText = inviteWhatsappBtn.textContent;
    inviteWhatsappBtn.textContent = "Creating...";

    try {
      const response = await fetch(`/api/room/${bootstrap.roomId}/invite/`, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCookieValue("csrftoken"),
        },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok || !payload.invite_url) {
        showSystemNote("Could not create invite right now.");
        return;
      }

      const inviteUrl = payload.invite_url;
      const message = `Join my private PulsePair room: ${inviteUrl}`;
      const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(message)}`;

      const shareWindow = window.open(whatsappUrl, "_blank", "noopener,noreferrer");
      if (!shareWindow) {
        await navigator.clipboard.writeText(inviteUrl);
        showSystemNote("Invite link copied. Paste it on WhatsApp.");
        return;
      }
      showSystemNote("Opening WhatsApp with your invite link.");
    } catch {
      showSystemNote("Could not create invite right now.");
    } finally {
      inviteWhatsappBtn.disabled = false;
      inviteWhatsappBtn.textContent = originalText;
    }
  });

  imagePickerBtn.addEventListener("click", () => imageInputEl.click());

  imageInputEl.addEventListener("change", () => {
    const [file] = imageInputEl.files || [];
    if (!file) {
      resetSelectedImage();
      return;
    }
    if (!file.type.startsWith("image/")) {
      showSystemNote("Please choose an image file.");
      resetSelectedImage();
      return;
    }
    if (file.size > maxImageUploadBytes) {
      showSystemNote("Please choose an image up to 5MB.");
      resetSelectedImage();
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        showSystemNote("Could not load image file.");
        resetSelectedImage();
        return;
      }
      state.selectedImage = {
        dataUrl: result,
        name: file.name,
      };
      refreshSelectedImageMeta();
    };
    reader.onerror = () => {
      showSystemNote("Could not load image file.");
      resetSelectedImage();
    };
    reader.readAsDataURL(file);
  });

  imageModeSelectEl.addEventListener("change", updateImageModeUI);
  imageSecondsInputEl.addEventListener("input", refreshSelectedImageMeta);

  sendImageBtn.addEventListener("click", () => {
    if (!state.selectedImage) {
      showSystemNote("Choose an image first.");
      return;
    }

    const mode = imageModeSelectEl.value;
    const payload = {
      action: "image_send",
      image_data_url: state.selectedImage.dataUrl,
      view_mode: mode,
    };

    if (mode === "timed_one_time_seen") {
      const seconds = Number.parseInt(imageSecondsInputEl.value || "0", 10);
      payload.view_seconds = Number.isNaN(seconds) ? 0 : seconds;
    }

    state.socket?.send(JSON.stringify(payload));
    resetSelectedImage();
    clearReplyTarget();
    closeImageComposerModal();
  });

  closeOneTimeImageBtn.addEventListener("click", () => closeImageModal(true));
  oneTimeImageModalEl.addEventListener("click", (event) => {
    if (event.target === oneTimeImageModalEl) {
      closeImageModal(true);
    }
  });
  imageComposerModalEl.addEventListener("click", (event) => {
    if (event.target === imageComposerModalEl) {
      closeImageComposerModal();
    }
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.activeImageView) {
      closeImageModal(true);
      return;
    }
    if (event.key === "Escape" && !imageComposerModalEl.classList.contains("hidden")) {
      closeImageComposerModal();
    }
  });

  setStatus("Connecting", false);
  updateImageModeUI();
  connectSocket();
})();
