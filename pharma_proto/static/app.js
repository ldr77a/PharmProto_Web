const provider = document.querySelector("#provider");
const tier = document.querySelector("#tier");
const apiKey = document.querySelector("#api-key");
const question = document.querySelector("#question");
const message = document.querySelector("#message");
const setupMessage = document.querySelector("#setup-message");
const results = document.querySelector("#results");
const apiSetup = document.querySelector("#api-setup");
const researchApp = document.querySelector("#research-app");
const reviewNotice = document.querySelector("#review-notice");
const selectedModel = document.querySelector("#selected-model");
const modelCatalog = JSON.parse(document.querySelector("#model-catalog").textContent);
const followupPanel = document.querySelector("#followup-panel");
const followupQuestion = document.querySelector("#followup-question");
const followupLog = document.querySelector("#followup-log");
const followupButton = document.querySelector("#followup");
const logoutButton = document.querySelector("#logout");
const themeToggle = document.querySelector("#theme-toggle");
const printButton = document.querySelector("#print");
const resultActions = document.querySelector("#result-actions");
const saveButton = document.querySelector("#save-result");
const saveStatus = document.querySelector("#save-status");
const refreshResultsButton = document.querySelector("#refresh-results");
const resultsList = document.querySelector("#results-list");
const helpText = JSON.parse(document.querySelector("#help-text").textContent || "{}");
const helpPopover = document.querySelector("#help-popover");
const helpTitle = document.querySelector("#help-title");
const helpBody = document.querySelector("#help-body");
const helpClose = document.querySelector("#help-close");
const sidePanel = document.querySelector("#side-panel");
const panelBackdrop = document.querySelector("#panel-backdrop");
const panelTitle = document.querySelector("#panel-title");
const gateGuide = document.querySelector("#gate-guide");
const panelSaved = document.querySelector("#panel-saved");
const openGatesButton = document.querySelector("#open-gates");
const openSavedButton = document.querySelector("#open-saved");
const closePanelButton = document.querySelector("#close-panel");
const examples = document.querySelector("#examples");
const resultsSkeleton = document.querySelector("#results-skeleton");
const resultsEmpty = document.querySelector("#results-empty");
// 서버 메모리에 있는 현재 대화의 id. 새로고침·로그아웃이면 사라진다(브라우저에 저장하지 않음).
let conversationId = null;

// 옆 패널: 게이트 안내 / 저장된 작업. 한 번에 하나만.
function openPanel(kind) {
  const saved = kind === "saved";
  panelTitle.textContent = saved ? "저장된 작업" : "게이트 안내";
  gateGuide.hidden = saved;
  panelSaved.hidden = !saved;
  sidePanel.hidden = false;
  panelBackdrop.hidden = false;
  openGatesButton.ariaExpanded = String(!saved);
  openSavedButton.ariaExpanded = String(saved);
  closePanelButton.focus();
  return saved ? refreshResults() : Promise.resolve();
}

function closePanel() {
  sidePanel.hidden = true;
  panelBackdrop.hidden = true;
  openGatesButton.ariaExpanded = "false";
  openSavedButton.ariaExpanded = "false";
}

function updateEmptyState() {
  resultsEmpty.hidden = results.querySelector(".card") !== null;
}

// 화면 색: 기본은 밝은 화면. 오른쪽 아래 해·달 버튼이 밝게↔어둡게를 바꾸고, 선택값은 서버의
// preferences.json 에 저장한다(브라우저 저장소를 쓰지 않는 규칙). 예전 값 'system' 은 OS 설정을 따른다.
const THEMES = ["light", "dark", "system"];

function isDarkNow() {
  const theme = document.documentElement.dataset.theme;
  if (theme === "dark") return true;
  if (theme === "light") return false;
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme(theme) {
  const value = THEMES.includes(theme) ? theme : "light";
  document.documentElement.dataset.theme = value;
  const label = isDarkNow() ? "밝은 화면으로 전환" : "어두운 화면으로 전환";
  themeToggle.ariaLabel = label;
  themeToggle.title = label;
  return value;
}

function populateModels() {
  const preferredTier = tier.value || "normal";
  tier.replaceChildren();
  for (const [tierName, modelName] of Object.entries(modelCatalog[provider.value])) {
    const option = document.createElement("option");
    option.value = tierName;
    option.textContent = modelName;
    option.selected = tierName === preferredTier;
    tier.append(option);
  }
  if (!tier.value) tier.value = "normal";
  selectedModel.textContent = modelCatalog[provider.value][tier.value];
}

function setFollowupEnabled(enabled) {
  followupQuestion.disabled = !enabled;
  followupButton.disabled = !enabled;
}

function resetConversation() {
  conversationId = null;
  followupPanel.hidden = true;
  followupLog.replaceChildren();
  followupQuestion.value = "";
  setFollowupEnabled(true);
  resultActions.hidden = true;
  saveStatus.textContent = "";
}

// 결과 표시는 생성·후속 수정·저장본 열기·이어서 질문이 모두 같은 길을 탄다.
function showResult(data) {
  results.innerHTML = data.html;
  enableDownloads(data.downloads || []);
  reviewNotice.hidden = results.querySelector(".card") === null;
  updateEmptyState();
}

function showTurns(turns) {
  followupLog.replaceChildren();
  for (const turn of turns || []) {
    if (turn && turn.html) appendFollowupLog(turn.html);
  }
}

function showApiSetup() {
  researchApp.hidden = true;
  apiSetup.hidden = false;
  results.replaceChildren();
  reviewNotice.hidden = true;
  resetConversation();
  closePanel();
  resultsEmpty.hidden = false;
  setupMessage.textContent = "";
  apiKey.focus();
}

function appendFollowupLog(htmlText) {
  if (!htmlText) return;
  const entry = document.createElement("div");
  entry.innerHTML = htmlText;
  followupLog.append(entry);
}

function showResearchApp() {
  selectedModel.textContent = modelCatalog[provider.value][tier.value];
  apiSetup.hidden = true;
  researchApp.hidden = false;
  message.textContent = "API 설정이 적용되었습니다.";
  question.focus();
  refreshResults();
}

function downloadWorkbook(item) {
  const binary = atob(item.content_base64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  }));
  const link = document.createElement("a");
  link.href = url;
  link.download = item.filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function enableDownloads(downloads) {
  const byCandidate = new Map(
    downloads.map((item) => [String(item.candidate_idx), item]),
  );
  for (const button of results.querySelectorAll(".download-xlsx")) {
    const item = byCandidate.get(button.dataset.candidateIndex);
    if (!item) continue;
    button.disabled = false;
    button.addEventListener("click", () => downloadWorkbook(item));
  }
}

// 서버는 오류 코드만 돌려준다(본문·경로·키 없음). 화면에서는 코드 옆에 한 줄 설명을 붙인다.
const ERROR_MESSAGES = {
  "REQUEST-001": "요청 형식이 올바르지 않습니다.",
  "REQUEST-FORM-001": "현재는 경구 고형제(정제·캡슐·과립·산제)만 지원합니다.",
  "LLM-KEY-001": "API 키가 설정되지 않았습니다.",
  "LLM-AUTH-001": "API 키가 거부되었습니다. 키를 확인해 주세요.",
  "LLM-RATE-001": "API 호출 한도에 걸렸습니다. 잠시 뒤 다시 시도해 주세요.",
  "LLM-TIMEOUT-001": "AI 응답이 시간 안에 오지 않았습니다. 다시 시도해 주세요.",
  "LLM-UPSTREAM-001": "AI 서비스에 연결하지 못했습니다.",
  "LLM-RESPONSE-001": "AI 응답을 해석하지 못했습니다. 질문을 바꿔 다시 시도해 주세요.",
  "CONVERSATION-001": "대화가 만료되었습니다. 조성표를 새로 생성해 주세요.",
  "RESULTS-001": "저장된 작업을 찾을 수 없습니다.",
  "RESULTS-IO-001": "저장 폴더에 쓰거나 지울 수 없습니다.",
  "RESULTS-SNAPSHOT-001": "다른 데이터베이스 버전으로 만든 결과라 이어서 질문할 수 없습니다. 열람과 다운로드만 가능합니다.",
  "PREFERENCES-IO-001": "화면 설정을 파일에 저장하지 못했습니다. 이번 실행에서는 적용됩니다.",
  "APP-START-001": "앱 내부 오류가 발생했습니다.",
};

function describeError(error) {
  const code = error && error.message ? error.message : "APP-START-001";
  const text = ERROR_MESSAGES[code];
  return text ? `${text} (${code})` : code;
}

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "APP-START-001");
  return data;
}

async function refreshHealth() {
  try {
    const data = await jsonRequest("/health");
    document.querySelector("#health").textContent =
      `${data.status} · 앱 ${data.app_version} · DB ${data.snapshot_id} / schema ${data.schema_version}`;
  } catch (error) {
    document.querySelector("#health").textContent = describeError(error);
  }
}

document.querySelector("#save-key").addEventListener("click", async () => {
  setupMessage.textContent = "";
  populateModels();   // 브라우저가 새로고침 때 '모델 종류'만 복원했어도 모델 이름을 그 공급자 것으로 맞춘다
  try {
    await jsonRequest("/api/key", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({provider: provider.value, api_key: apiKey.value}),
    });
    apiKey.value = "";
    showResearchApp();
  } catch (error) {
    apiKey.value = "";
    setupMessage.textContent = describeError(error);
    apiKey.focus();
  }
});

themeToggle.addEventListener("click", async () => {
  const next = isDarkNow() ? "light" : "dark";
  applyTheme(next);
  try {
    await jsonRequest("/api/preferences", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({theme: next}),
    });
  } catch (error) {
    message.textContent = describeError(error);   // 화면은 이미 바뀌었고 저장만 실패했다
  }
});

printButton.addEventListener("click", () => window.print());
// 접힌 근거·해설도 인쇄물에는 펼쳐서 넣고, 인쇄가 끝나면 원래대로 접는다.
window.addEventListener("beforeprint", () => {
  for (const details of document.querySelectorAll("details:not([open])")) {
    details.dataset.printOpened = "1";
    details.open = true;
  }
});
window.addEventListener("afterprint", () => {
  for (const details of document.querySelectorAll("details[data-print-opened]")) {
    details.open = false;
    delete details.dataset.printOpened;
  }
});

logoutButton.addEventListener("click", async () => {
  try {
    await jsonRequest("/api/logout", {method: "POST"});
  } catch (error) {
    // 서버가 응답하지 못해도 화면은 초기화한다. 키는 프로세스 종료 때 어차피 사라진다.
  }
  showApiSetup();
});
provider.addEventListener("change", populateModels);
tier.addEventListener("change", () => {
  selectedModel.textContent = modelCatalog[provider.value][tier.value];
});

const generateButton = document.querySelector("#generate");
generateButton.addEventListener("click", async () => {
  message.textContent = "생성 중… 조성표를 만든 뒤 LLM 해설을 작성합니다. 1~2분 걸릴 수 있습니다.";
  results.replaceChildren();
  reviewNotice.hidden = true;
  resetConversation();
  resultsEmpty.hidden = true;
  resultsSkeleton.hidden = false;      // 결과 자리에 표 모양 자리 표시
  generateButton.disabled = true;
  generateButton.ariaBusy = "true";
  try {
    const data = await jsonRequest("/api/generate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({provider: provider.value, tier: tier.value, question: question.value}),
    });
    showResult(data);
    conversationId = data.conversation_id || null;
    followupPanel.hidden = conversationId === null || reviewNotice.hidden;
    resultActions.hidden = followupPanel.hidden;
    message.textContent = "완료";
  } catch (error) {
    message.textContent = describeError(error);
    updateEmptyState();
  } finally {
    resultsSkeleton.hidden = true;
    generateButton.disabled = false;
    generateButton.ariaBusy = "false";
  }
});

// 예시 질문 칩: 누르면 질문 칸에 채운다(바로 생성하지는 않는다)
examples.addEventListener("click", (event) => {
  const target = event && event.target;
  const chip = target && typeof target.closest === "function" ? target.closest("[data-example]") : null;
  if (!chip) return;
  question.value = chip.dataset.example;
  question.focus();
});

openGatesButton.addEventListener("click", () => openPanel("gates"));
openSavedButton.addEventListener("click", () => openPanel("saved"));
closePanelButton.addEventListener("click", closePanel);
panelBackdrop.addEventListener("click", closePanel);

followupButton.addEventListener("click", async () => {
  const text = followupQuestion.value.trim();
  if (!text) return;
  if (!conversationId) {
    message.textContent = describeError(new Error("CONVERSATION-001"));
    return;
  }
  message.textContent = "후속 질문 처리 중… 요청을 고치는 경우 조성표와 해설을 다시 만듭니다.";
  followupButton.disabled = true;
  followupButton.ariaBusy = "true";
  try {
    const data = await jsonRequest("/api/followup", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        provider: provider.value, tier: tier.value, conversation_id: conversationId, question: text,
      }),
    });
    conversationId = data.conversation_id || conversationId;
    if (data.action === "refine" && data.changed) {
      showResult(data);
      saveStatus.textContent = "";   // 표가 바뀌었으니 저장본과 다르다
    }
    appendFollowupLog(data.answer_html || "");
    followupQuestion.value = "";
    if (data.action === "refine") {
      message.textContent = data.changed ? "요청을 수정해 다시 생성했습니다." : "변경할 내용이 없어 기존 결과를 유지합니다.";
    } else {
      message.textContent = "답변을 추가했습니다.";
    }
  } catch (error) {
    message.textContent = describeError(error);
    if (error.message === "CONVERSATION-001") resetConversation();
  } finally {
    followupButton.disabled = false;
    followupButton.ariaBusy = "false";
  }
});

// 클릭 설명: 근거 꼬리표·게이트 칩·배지(data-help)를 누르면 쉬운 말 설명이 팝오버로 뜬다.
function closeHelp() {
  helpPopover.hidden = true;
}

function openHelp(trigger) {
  const entry = helpText[trigger.dataset.help];
  helpTitle.textContent = entry ? entry.title : (trigger.textContent || "").trim();
  helpBody.textContent = entry ? entry.text : "이 항목의 설명이 아직 준비되지 않았습니다.";
  helpPopover.hidden = false;
  if (helpPopover.style && typeof trigger.getBoundingClientRect === "function") {
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(360, (window.innerWidth || 800) - 32);
    const left = Math.max(16, Math.min(rect.left + (window.scrollX || 0), (window.innerWidth || 800) - width - 16));
    helpPopover.style.top = `${rect.bottom + (window.scrollY || 0) + 6}px`;
    helpPopover.style.left = `${left}px`;
  }
  helpClose.focus();
}

function handleHelpClick(event) {
  const target = event && event.target;
  const trigger = target && typeof target.closest === "function" ? target.closest("[data-help]") : null;
  if (!trigger) return;
  if (typeof event.preventDefault === "function") event.preventDefault();
  openHelp(trigger);
}

results.addEventListener("click", handleHelpClick);
followupLog.addEventListener("click", handleHelpClick);
helpClose.addEventListener("click", closeHelp);
document.addEventListener("keydown", (event) => {
  if (event && event.key === "Escape") {
    closeHelp();
    closePanel();
  }
});
document.addEventListener("click", (event) => {
  if (helpPopover.hidden) return;
  const target = event && event.target;
  if (target && typeof target.closest === "function"
      && (target.closest("#help-popover") || target.closest("[data-help]"))) return;
  closeHelp();
});

// 저장된 작업: 수동 저장, 목록, 열기(읽기 전용), 이어서 질문(결정적 재계산, LLM 호출 없음), 삭제
function actionButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary compact";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function renderResultsList(items) {
  resultsList.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "저장된 작업이 없습니다.";
    resultsList.append(empty);
    return;
  }
  for (const item of items) {
    const row = document.createElement("li");
    const title = document.createElement("div");
    title.className = "saved-title";
    title.textContent = item.question_preview || "(질문 없음)";
    const meta = document.createElement("div");
    meta.className = "saved-meta";
    meta.textContent = `${item.saved_at} · ${(item.api_names || []).join(", ")} · 후보 ${item.n_candidates}개 · DB ${item.snapshot_id}`;
    const actions = document.createElement("div");
    actions.className = "saved-actions";
    actions.append(
      actionButton("열기", () => openResult(item.id)),
      actionButton("이어서 질문", () => resumeResult(item.id)),
      actionButton("삭제", () => deleteResult(item.id)),
    );
    row.append(title, meta, actions);
    resultsList.append(row);
  }
}

async function refreshResults() {
  try {
    const data = await jsonRequest("/api/results");
    renderResultsList(data.results || []);
  } catch (error) {
    renderResultsList([]);
  }
}

async function openResult(id) {
  try {
    const data = await jsonRequest(`/api/results/${id}`);
    resetConversation();
    showResult(data);
    showTurns(data.turns);
    followupPanel.hidden = false;
    setFollowupEnabled(false);        // 읽기 전용 — '이어서 질문'을 눌러야 대화가 열린다
    message.textContent = `저장된 작업을 열었습니다 (${data.saved_at}). 이어서 질문하려면 목록의 '이어서 질문'을 누르세요.`;
  } catch (error) {
    message.textContent = describeError(error);
  }
}

async function resumeResult(id) {
  message.textContent = "저장된 요청으로 조성표를 다시 계산합니다(LLM 호출 없음)…";
  try {
    const data = await jsonRequest(`/api/results/${id}/resume`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({provider: provider.value, tier: tier.value}),
    });
    resetConversation();
    showResult(data);
    showTurns(data.turns);
    conversationId = data.conversation_id;
    followupPanel.hidden = false;
    resultActions.hidden = false;
    saveStatus.textContent = `저장본 ${id} 에서 이어서 질문합니다. 질의응답은 그 폴더에도 기록됩니다.`;
    message.textContent = "이어서 질문할 수 있습니다.";
  } catch (error) {
    message.textContent = describeError(error);
  }
}

async function deleteResult(id) {
  try {
    await jsonRequest(`/api/results/${id}`, {method: "DELETE"});
    await refreshResults();
  } catch (error) {
    message.textContent = describeError(error);
  }
}

saveButton.addEventListener("click", async () => {
  if (!conversationId) return;
  saveButton.disabled = true;
  try {
    const data = await jsonRequest("/api/results", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({conversation_id: conversationId}),
    });
    saveStatus.textContent = `저장됨 (${data.result_id}) · 위치: %LOCALAPPDATA%\\PhramaProto\\results`;
    await refreshResults();
  } catch (error) {
    saveStatus.textContent = describeError(error);
  } finally {
    saveButton.disabled = false;
  }
});

refreshResultsButton.addEventListener("click", refreshResults);

applyTheme(document.documentElement.dataset.theme);
populateModels();
// 일부 브라우저(Firefox 등)는 새로고침 뒤 <select> 선택값을 change 이벤트 없이 복원한다.
// 복원이 끝난 pageshow 시점에 모델 이름 목록을 공급자에 맞춰 다시 채운다.
window.addEventListener("pageshow", populateModels);
refreshHealth();
