(() => {
  const roomListEl = document.getElementById("roomList");
  const emptyStateEl = document.getElementById("emptyState");
  const roomCountEl = document.getElementById("roomCount");
  const createRoomBtn = document.getElementById("createRoomBtn");
  const bannerEl = document.getElementById("notificationBanner");

  const state = {
    rooms: new Map(),
    socket: null,
  };

  const bootstrap = window.CHAT_BOOTSTRAP;

  const showBanner = (text, isError = false) => {
    bannerEl.classList.remove("hidden");
    bannerEl.textContent = text;
    bannerEl.classList.toggle("border-rose-400", isError);
    bannerEl.classList.toggle("bg-rose-50", isError);
    bannerEl.classList.toggle("text-rose-800", isError);
    if (!isError) {
      bannerEl.classList.remove("text-rose-800", "bg-rose-50", "border-rose-400");
    }
    window.setTimeout(() => {
      bannerEl.classList.add("hidden");
    }, 4500);
  };

  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";

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
      const canRequestJoin = room.owner_id !== bootstrap.userId && !room.is_full;
      const participantNames = room.participants.map((p) => p.display_name).join(", ");

      const container = document.createElement("article");
      container.className = "room-item";
      container.innerHTML = `
        <div class="flex items-start justify-between gap-2">
          <div>
            <p class="font-mono text-xs text-slate-500">${room.id}</p>
            <h3 class="mt-1 text-sm font-semibold text-slate-800">${room.owner_name}'s room</h3>
          </div>
          <span class="status-pill">${room.is_full ? "Full" : "Open"}</span>
        </div>
        <p class="mt-2 text-xs text-slate-500">Online: ${room.online_count} / 2</p>
        <p class="mt-1 text-xs text-slate-500">Participants: ${participantNames || "Waiting"}</p>
        <div class="mt-3 flex items-center gap-2">
          ${canRequestJoin ? `<button data-room-id="${room.id}" class="btn-secondary join-btn">Request Join</button>` : `<a class="btn-secondary text-center" href="/room/${room.id}/">Open</a>`}
        </div>
      `;
      roomListEl.appendChild(container);
    });

    roomListEl.querySelectorAll(".join-btn").forEach((button) => {
      button.addEventListener("click", () => {
        state.socket?.send(JSON.stringify({
          action: "join_room_request",
          room_id: button.dataset.roomId,
        }));
      });
    });
  };

  const connectSocket = () => {
    state.socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws/lobby/`);

    state.socket.onopen = () => {
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
          showBanner("Join request sent. Waiting for owner approval.");
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
      createRoomBtn.disabled = true;
      showBanner("Connection dropped. Reconnecting...", true);
      setTimeout(connectSocket, 1200);
    };
  };

  createRoomBtn.disabled = true;
  createRoomBtn.addEventListener("click", () => {
    state.socket?.send(JSON.stringify({ action: "create_room" }));
  });

  connectSocket();
})();
