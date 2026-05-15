(() => {
  const roomListEl = document.getElementById("roomList");
  const emptyStateEl = document.getElementById("emptyState");
  const roomCountEl = document.getElementById("roomCount");
  const createRoomBtn = document.getElementById("createRoomBtn");
  const bannerEl = document.getElementById("notificationBanner");
  const connectionEl = document.getElementById("lobbyConnection");
  const mobileConnectionEl = document.getElementById("lobbyConnectionMobile");
  const selfNamePillEl = document.getElementById("selfNamePill");
  const selfNamePillMobileEl = document.getElementById("selfNamePillMobile");

  const state = {
    rooms: new Map(),
    socket: null,
  };
  const inviteErrorMessages = {
    invite_not_found: "Invite link is invalid or already used.",
    invite_expired: "Invite link expired. Ask for a fresh link.",
    room_not_found: "That room is no longer available.",
    room_full: "Room is already full.",
    username_taken: "Username already exists.",
    invalid_username: "Username must use letters, numbers, or underscore (3-24 chars).",
  };

  const bootstrap = window.CHAT_BOOTSTRAP;
  if (selfNamePillEl) {
    selfNamePillEl.textContent = bootstrap.userName;
  }
  if (selfNamePillMobileEl) {
    selfNamePillMobileEl.textContent = bootstrap.userName;
  }

  const setConnection = (label, isOffline = false) => {
    if (connectionEl) {
      connectionEl.textContent = label;
      connectionEl.dataset.state = isOffline ? "offline" : "online";
    }
    if (mobileConnectionEl) {
      mobileConnectionEl.textContent = label;
      mobileConnectionEl.dataset.state = isOffline ? "offline" : "online";
    }
  };

  const showBanner = (text, isError = false) => {
    bannerEl.classList.remove("hidden", "notice-error");
    bannerEl.textContent = text;
    if (isError) {
      bannerEl.classList.add("notice-error");
    }

    window.setTimeout(() => {
      bannerEl.classList.add("hidden");
    }, 4500);
  };

  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";

  const createRoomCard = (room) => {
    const canRequestJoin = room.owner_id !== bootstrap.userId && !room.is_full;
    const participantNames = room.participants.map((p) => p.display_name).join(", ") || "Waiting";

    const card = document.createElement("article");
    card.className = "room-card";

    const topRow = document.createElement("div");
    topRow.className = "room-top-row";

    const left = document.createElement("div");
    const roomIdEl = document.createElement("p");
    roomIdEl.className = "room-id";
    roomIdEl.textContent = room.id;
    const titleEl = document.createElement("h3");
    titleEl.className = "room-title";
    titleEl.textContent = `${room.owner_name}'s room`;
    left.appendChild(roomIdEl);
    left.appendChild(titleEl);

    const status = document.createElement("span");
    status.className = "status-dot";
    status.textContent = room.is_full ? "Full" : "Open";

    topRow.appendChild(left);
    topRow.appendChild(status);

    const metaGrid = document.createElement("div");
    metaGrid.className = "room-meta-grid";

    const online = document.createElement("div");
    online.className = "room-meta";
    online.innerHTML = `Online <strong>${room.online_count}/2</strong>`;

    const access = document.createElement("div");
    access.className = "room-meta";
    access.innerHTML = `Access <strong>${room.is_full ? "Locked" : "Invite"}</strong>`;

    metaGrid.appendChild(online);
    metaGrid.appendChild(access);

    const participants = document.createElement("p");
    participants.className = "room-participants";
    participants.textContent = `Participants: ${participantNames}`;

    const actions = document.createElement("div");
    actions.className = "room-actions";

    if (canRequestJoin) {
      const joinBtn = document.createElement("button");
      joinBtn.type = "button";
      joinBtn.dataset.roomId = room.id;
      joinBtn.className = "btn-secondary join-btn";
      joinBtn.textContent = "Request Join";
      actions.appendChild(joinBtn);
    } else {
      const openLink = document.createElement("a");
      openLink.href = `/room/${room.id}/`;
      openLink.className = "btn-secondary btn-link-like";
      openLink.textContent = "Open Room";
      actions.appendChild(openLink);
    }

    card.appendChild(topRow);
    card.appendChild(metaGrid);
    card.appendChild(participants);
    card.appendChild(actions);

    return card;
  };

  const renderRooms = () => {
    const rooms = [...state.rooms.values()].sort((a, b) => (a.created_at > b.created_at ? -1 : 1));
    roomListEl.innerHTML = "";
    roomCountEl.textContent = `${rooms.length} room${rooms.length === 1 ? "" : "s"}`;

    if (!rooms.length) {
      emptyStateEl.classList.remove("hidden");
      return;
    }

    emptyStateEl.classList.add("hidden");

    rooms.forEach((room) => {
      roomListEl.appendChild(createRoomCard(room));
    });

    roomListEl.querySelectorAll(".join-btn").forEach((button) => {
      button.addEventListener("click", () => {
        state.socket?.send(
          JSON.stringify({
            action: "join_room_request",
            room_id: button.dataset.roomId,
          })
        );
      });
    });
  };

  const connectSocket = () => {
    state.socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws/lobby/`);

    state.socket.onopen = () => {
      setConnection("Live", false);
      createRoomBtn.disabled = false;
    };

    state.socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      switch (data.type) {
        case "lobby_init":
          data.rooms.forEach((room) => state.rooms.set(room.id, room));
          renderRooms();
          break;
        case "room_created":
          window.location.href = data.redirect_url;
          break;
        case "lobby_room_update":
          state.rooms.set(data.room.id, data.room);
          renderRooms();
          break;
        case "lobby_room_remove":
          state.rooms.delete(data.room_id);
          renderRooms();
          break;
        case "join_request_sent":
          showBanner("Join request sent. Waiting for approval.");
          break;
        case "notification":
          if (data.payload.kind === "join_decision") {
            if (data.payload.status === "approved") {
              showBanner("Join approved. Redirecting...");
              window.setTimeout(() => {
                window.location.href = data.payload.room_url;
              }, 700);
            } else {
              showBanner("Join request was rejected.", true);
            }
          }
          break;
        case "error":
          showBanner(data.message || data.code, true);
          break;
        default:
          break;
      }
    };

    state.socket.onclose = () => {
      setConnection("Offline", true);
      createRoomBtn.disabled = true;
      showBanner("Connection dropped. Reconnecting...", true);
      window.setTimeout(connectSocket, 1200);
    };
  };

  createRoomBtn.disabled = true;
  createRoomBtn.addEventListener("click", () => {
    state.socket?.send(JSON.stringify({ action: "create_room" }));
  });

  const params = new URLSearchParams(window.location.search);
  const inviteError = params.get("invite_error");
  if (inviteError && inviteErrorMessages[inviteError]) {
    showBanner(inviteErrorMessages[inviteError], true);
  }
  const profileError = params.get("profile_error");
  if (profileError && inviteErrorMessages[profileError]) {
    showBanner(inviteErrorMessages[profileError], true);
  }

  setConnection("Connecting", false);
  connectSocket();
})();
