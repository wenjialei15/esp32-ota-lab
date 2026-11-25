"use strict";

const byId = (id) => document.getElementById(id);
const CAPACITY = 16;
const nodeLabels = {
  active: "运行中", empty: "空闲", standby: "可用版本",
  writing: "下载中", trial: "待确认", rejected: "已拒绝",
};
const slotNames = ["ota_0", "ota_1"];
const networkButton = byId("network");
const healthyButton = byId("healthy");
const faultyButton = byId("faulty");
let state;
let upgradeTimer;

function log(type, message, warning = false) {
  const row = document.createElement("li");
  const time = document.createElement("time");
  const category = document.createElement("code");
  const text = document.createElement("span");
  const now = new Date();
  time.dateTime = now.toISOString();
  time.textContent = now.toTimeString().slice(0, 8);
  category.textContent = type;
  text.textContent = message;
  if (warning) text.className = "warning";
  row.append(time, category, text);
  const list = byId("log");
  list.prepend(row);
  if (list.children.length > 9) list.lastElementChild.remove();
}

function render() {
  const network = byId("network-state");
  const networkText = state.online ? "在线" : "离线";
  if (network.textContent !== networkText) network.textContent = networkText;
  network.classList.toggle("offline", !state.online);
  networkButton.querySelector("strong").textContent = state.online ? "断开网络" : "恢复网络";
  networkButton.querySelector("small").textContent = state.online ? "读数进入离线队列" : "按顺序补传缓存读数";
  byId("version").textContent = state.slots[state.active].version;
  byId("queued").textContent = state.queue.length;
  byId("received").textContent = state.received;
  state.slots.forEach((slot, index) => {
    const id = index === 0 ? "slot-a" : "slot-b";
    byId(id).dataset.state = slot.status;
    byId(id + "-version").textContent = slot.version || "—";
    byId(id + "-status").textContent = nodeLabels[slot.status];
  });
  byId("progress").value = state.progress;
  if (byId("progress-text").textContent !== state.progressText)
    byId("progress-text").textContent = state.progressText;
  const allowed = state.online && !state.pending;
  healthyButton.disabled = !allowed || state.slots[state.active].version !== "1.0.0";
  faultyButton.disabled = !allowed || state.rejected;
}

function sample() {
  if (state.pending?.phase === "trial") return;
  state.sequence += 1;
  if (state.online) {
    state.received += 1;
  } else {
    if (state.queue.length === CAPACITY) {
      state.queue.shift();
      log("QUEUE", "队列已满，覆盖最早读数。", true);
    }
    state.queue.push(state.sequence);
  }
  render();
}

function reset() {
  window.clearTimeout(upgradeTimer);
  state = {
    online: true, active: 0, sequence: 0, received: 0, queue: [], pending: null,
    rejected: false, progress: 0, progressText: "等待升级",
    slots: [{ version: "1.0.0", status: "active" }, { version: null, status: "empty" }],
  };
  byId("log").replaceChildren();
  log("BOOT", "ota_0 启动，固件 1.0.0。");
  sample();
}

function toggleNetwork() {
  state.online = !state.online;
  if (state.online) {
    log("LINK", "网络已恢复。");
    if (state.queue.length) {
      const first = state.queue[0];
      const last = state.queue[state.queue.length - 1];
      state.received += state.queue.length;
      log("REPLAY", `已补传 ${state.queue.length} 条读数，序号 ${first}–${last}。`);
      state.queue = [];
    }
  } else {
    log("LINK", "网络已断开，后续读数暂存到 NVS 队列。", true);
    if (state.pending?.phase === "download") {
      window.clearTimeout(upgradeTimer);
      state.slots[state.pending.target] = { version: null, status: "empty" };
      state.pending = null;
      state.progressText = "下载中断";
      log("OTA", "候选镜像未收全，继续运行原版本。", true);
    }
    sample();
  }
  render();
}

function finishTrial() {
  const update = state.pending;
  if (update.faulty) {
    state.rejected = true;
    state.slots[update.target].status = "rejected";
    state.active = 1 - update.target;
    state.slots[state.active].status = "active";
    state.progressText = "已回滚";
    log("ROLLBACK", `自检失败，恢复 ${slotNames[state.active]} 的 ${state.slots[state.active].version}。`, true);
  } else {
    state.slots[update.target].status = "active";
    state.progressText = "升级成功";
    log("CONFIRM", `自检通过，确认 ${slotNames[state.active]} 的 ${update.version}。`);
  }
  state.pending = null;
  render();
}

function advanceDownload() {
  const update = state.pending;
  state.progress = Math.min(100, state.progress + 25);
  state.progressText = state.progress + "%";
  if (state.progress === 100) {
    update.phase = "trial";
    state.slots[state.active].status = "standby";
    state.active = update.target;
    state.slots[state.active].status = "trial";
    state.progressText = "启动自检";
    log("TRIAL", `${update.version} 首次从 ${slotNames[state.active]} 启动。`);
    upgradeTimer = window.setTimeout(finishTrial, 1250);
  } else {
    upgradeTimer = window.setTimeout(advanceDownload, 375);
  }
  render();
}

function startUpdate(version, faulty) {
  const target = 1 - state.active;
  state.pending = { version, faulty, target, phase: "download" };
  state.slots[target] = { version, status: "writing" };
  state.progress = 0;
  state.progressText = "下载中";
  log("OTA", `正在下载 ${version} 并写入 ${slotNames[target]}。`);
  upgradeTimer = window.setTimeout(advanceDownload, 375);
  render();
}

networkButton.addEventListener("click", toggleNetwork);
healthyButton.addEventListener("click", () => startUpdate("1.1.0", false));
faultyButton.addEventListener("click", () => startUpdate("1.2.0", true));
byId("reset").addEventListener("click", reset);
reset();
window.setInterval(sample, 1000);
