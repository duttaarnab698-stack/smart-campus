function renderRooms() {
    const searchInput = document.getElementById("roomSearch");
    const grid = document.getElementById("roomGrid");

    if (!grid) return;

    const q = (searchInput?.value || "").toLowerCase().trim();
    const activeFilter =
        document.querySelector(".filter.active")?.dataset.filter || "all";

    const list = Campus.rooms.filter((r) => {
        const matchesFilter =
            activeFilter === "all" ||
            (activeFilter === "occupied" && r.occupied) ||
            (activeFilter === "empty" && !r.occupied) ||
            (activeFilter === "warning" && r.warning);

        const matchesSearch = String(r.id).toLowerCase().includes(q);

        return matchesFilter && matchesSearch;
    });

    grid.innerHTML = list.length
        ? list
              .map(
                  (r) => `
                    <article class="card room-card" data-id="${r.id}">
                        <div class="room-top">
                            <div>
                                <h3>${r.id}</h3>
                                <p class="muted">${r.floor} · ${r.block}</p>
                            </div>

                            ${badge(
                                r.warning
                                    ? "Warning"
                                    : r.occupied
                                    ? "Occupied"
                                    : "Empty",
                                r.warning
                                    ? "warning"
                                    : r.occupied
                                    ? "occupied"
                                    : "empty"
                            )}
                        </div>

                        <div class="room-details">
                            <div>
                                Temperature
                                <strong>${Number(r.temperature || 0).toFixed(1)}°C</strong>
                            </div>

                            <div>
                                Humidity
                                <strong>${Number(r.humidity || 0).toFixed(0)}%</strong>
                            </div>

                            <div>
                                Appliances
                                <strong>
                                    ${
                                        r.light
                                            ? "Light "
                                            : ""
                                    }${
                                        r.fan
                                            ? "Fan "
                                            : ""
                                    }${
                                        r.ac
                                            ? "AC"
                                            : ""
                                    }${
                                        !r.light && !r.fan && !r.ac
                                            ? "All off"
                                            : ""
                                    }
                                </strong>
                            </div>

                            <div>
                                Current Power
                                <strong>
                                    ${Number(r.power || 0).toFixed(2)} kW
                                </strong>
                            </div>
                        </div>
                    </article>
                `
              )
              .join("")
        : `<div class="card muted">No rooms match this filter.</div>`;

    document.querySelectorAll(".room-card").forEach((card) => {
        card.onclick = () => showDetail(card.dataset.id);
    });
}


function refreshRoomDetail() {
    const detail = document.querySelector(".detail");

    const id =
        detail?.dataset.roomId ||
        new URLSearchParams(location.search).get("room");

    if (!id) return;

    const room = Campus.rooms.find((item) => item.id === id);

    const values = document.querySelectorAll(
        ".detail .room-details strong"
    );

    if (!room || values.length < 7) return;

    values[0].textContent =
        `${Number(room.temperature || 0).toFixed(1)}°C`;

    values[1].textContent =
        `${Number(room.humidity || 0).toFixed(0)}%`;

    values[2].textContent = room.light ? "ON" : "OFF";
    values[3].textContent = room.fan ? "ON" : "OFF";
    values[4].textContent = room.ac ? "ON" : "OFF";

    values[5].textContent =
        `${Number(room.power || 0).toFixed(2)} kW`;

    values[6].textContent =
        `${Number(room.energyToday || 0).toFixed(2)} kWh`;

    document.querySelectorAll("[data-device]").forEach((control) => {
        const device = control.dataset.device;

        control.classList.toggle(
            "on",
            !!room[device]
        );
    });
}


function showDetail(id) {
    const room = Campus.rooms.find((x) => x.id === id);

    if (!room) {
        toast("Room not found");
        return;
    }

    const power = Number(room.power || 0).toFixed(2);
    const energyToday = Number(room.energyToday || 0).toFixed(2);

    shell(
        `Room ${room.id}`,
        `${room.floor} · ${room.block}`,
        `
        <div class="detail" data-room-id="${room.id}">

            <a class="back" href="rooms.html">
                ← Back to rooms
            </a>

            <div class="card">

                <div class="section-title">
                    <div>
                        <h2>ROOM ${room.id}</h2>
                        <p class="muted">
                            ${room.floor} · ${room.block}
                        </p>
                    </div>

                    ${badge(
                        room.warning
                            ? "Warning"
                            : room.occupied
                            ? "Occupied"
                            : "Empty",
                        room.warning
                            ? "warning"
                            : room.occupied
                            ? "occupied"
                            : "empty"
                    )}
                </div>

                <div class="room-details">

                    <div>
                        Temperature
                        <strong>
                            ${Number(room.temperature || 0).toFixed(1)}°C
                        </strong>
                    </div>

                    <div>
                        Humidity
                        <strong>
                            ${Number(room.humidity || 0).toFixed(0)}%
                        </strong>
                    </div>

                    <div>
                        Light
                        <strong>
                            ${room.light ? "ON" : "OFF"}
                        </strong>
                    </div>

                    <div>
                        Fan
                        <strong>
                            ${room.fan ? "ON" : "OFF"}
                        </strong>
                    </div>

                    <div>
                        AC
                        <strong>
                            ${room.ac ? "ON" : "OFF"}
                        </strong>
                    </div>

                    <div>
                        Current Power
                        <strong id="powerRead">
                            ${power} kW
                        </strong>
                    </div>

                    <div>
                        Today's Energy
                        <strong>
                            ${energyToday} kWh
                        </strong>
                    </div>

                </div>
            </div>

            <div class="card" style="margin-top:16px">

                <h2>Simulated Appliance Controls</h2>

                ${["light", "fan", "ac"]
                    .map(
                        (device) => `
                            <div class="toggle-row">

                                <strong>
                                    ${device.toUpperCase()}
                                </strong>

                                <button
                                    class="switch ${room[device] ? "on" : ""}"
                                    data-device="${device}"
                                    type="button"
                                    aria-label="Toggle ${device}"
                                ></button>

                            </div>
                        `
                    )
                    .join("")}

                <p class="muted">
                    Frontend demonstration only — no physical appliances
                    are connected.
                </p>

            </div>

        </div>
        `
    );

    document.querySelectorAll("[data-device]").forEach((button) => {
        button.onclick = async () => {
            const device = button.dataset.device;

            button.disabled = true;

            try {
                const updatedRoom =
                    await SimulationEngine.toggleAppliance(
                        room.id,
                        device
                    );

                if (!updatedRoom) {
                    toast("Device update failed");
                    return;
                }

                document
                    .querySelectorAll("[data-device]")
                    .forEach((control) => {
                        const controlDevice =
                            control.dataset.device;

                        control.classList.toggle(
                            "on",
                            !!updatedRoom[controlDevice]
                        );
                    });

                const powerRead =
                    document.getElementById("powerRead");

                if (powerRead) {
                    powerRead.textContent =
                        `${Number(
                            updatedRoom.power || 0
                        ).toFixed(2)} kW`;
                }

                toast(
                    `${device.toUpperCase()} state updated`
                );

            } catch (error) {
                console.error(
                    "Device update failed:",
                    error
                );

                toast("Device update failed");

            } finally {
                button.disabled = false;
            }
        };
    });
}


window.refreshRoomsLive = () => {
    if (page !== "rooms") return;

    if (document.querySelector(".detail")) {
        refreshRoomDetail();
    } else if (document.querySelector("#roomGrid")) {
        renderRooms();
    }
};


window.addEventListener(
    "campus-state-change",
    window.refreshRoomsLive
);


if (page === "rooms") {

    const selected =
        new URLSearchParams(location.search).get("room");

    if (selected) {

        showDetail(selected);

    } else {

        shell(
            "Rooms",
            "Campus 25 live simulated room monitoring.",
            `
            <div class="room-toolbar">

                <input
                    id="roomSearch"
                    class="select"
                    placeholder="Search Campus 25 room ID"
                    type="search"
                >

                <div class="filters">

                    ${["all", "occupied", "empty", "warning"]
                        .map(
                            (filter, index) => `
                                <button
                                    type="button"
                                    data-filter="${filter}"
                                    class="btn filter ${
                                        index === 0
                                            ? "active"
                                            : ""
                                    }"
                                >
                                    ${
                                        filter.charAt(0).toUpperCase() +
                                        filter.slice(1)
                                    }
                                </button>
                            `
                        )
                        .join("")}

                </div>

            </div>

            <div
                id="roomGrid"
                class="room-grid"
            ></div>
            `
        );

        const roomSearch =
            document.getElementById("roomSearch");

        if (roomSearch) {
            roomSearch.addEventListener(
                "input",
                renderRooms
            );
        }

        document
            .querySelectorAll(".filter")
            .forEach((button) => {

                button.onclick = () => {

                    document
                        .querySelectorAll(".filter")
                        .forEach((item) => {
                            item.classList.remove("active");
                        });

                    button.classList.add("active");

                    renderRooms();
                };
            });

        renderRooms();
    }
}