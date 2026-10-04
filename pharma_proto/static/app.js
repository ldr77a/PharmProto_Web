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
// 서버 메모리에 있는 현재 대화의 id. 새로고침·로그아웃이면 사라진다(브라우저에 저장하지 않음).
let conversationId = null;

// 화면 색: 선택값은 서버의 preferences.json 에 저장한다(브라우저 저장소를 쓰지 않는 규칙).
const THEME_ORDER = ["system", "light", "dark"];
const THEME_LABELS = {system: "화면: 시스템", light: "화면: 밝게", dark: "화면: 어둡게"};

function applyTheme(theme) {
  const value = THEME_ORDER.includes(theme) ? theme : "system";
  document.documentElement.dataset.theme = value;
  themeToggle.textContent = THEME_LABELS[value];
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

function resetConversation() {
  conversationId = null;
  followupPanel.hidden = true;
  followupLog.replaceChildren();
  followupQuestion.value = "";
}

function showApiSetup() {
  researchApp.hidden = true;
  apiSetup.hidden = false;
  results.replaceChildren();
  reviewNotice.hidden = true;
  resetConversation();
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
  const current = document.documentElement.dataset.theme || "system";
  const next = THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length];
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
  generateButton.disabled = true;
  generateButton.ariaBusy = "true";
  try {
    const data = await jsonRequest("/api/generate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({provider: provider.value, tier: tier.value, question: question.value}),
    });
    results.innerHTML = data.html;
    enableDownloads(data.downloads || []);
    reviewNotice.hidden = results.querySelector(".card") === null;
    conversationId = data.conversation_id || null;
    followupPanel.hidden = conversationId === null || reviewNotice.hidden;
    message.textContent = "완료";
  } catch (error) {
    message.textContent = describeError(error);
  } finally {
    generateButton.disabled = false;
    generateButton.ariaBusy = "false";
  }
});

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
      results.innerHTML = data.html;
      enableDownloads(data.downloads || []);
      reviewNotice.hidden = results.querySelector(".card") === null;
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

applyTheme(document.documentElement.dataset.theme);
populateModels();
refreshHealth();
