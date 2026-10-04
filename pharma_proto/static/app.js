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

function showApiSetup() {
  researchApp.hidden = true;
  apiSetup.hidden = false;
  results.replaceChildren();
  reviewNotice.hidden = true;
  setupMessage.textContent = "";
  apiKey.focus();
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
    document.querySelector("#health").textContent = error.message;
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
    setupMessage.textContent = error.message;
    apiKey.focus();
  }
});

document.querySelector("#change-key").addEventListener("click", showApiSetup);
provider.addEventListener("change", populateModels);
tier.addEventListener("change", () => {
  selectedModel.textContent = modelCatalog[provider.value][tier.value];
});

const generateButton = document.querySelector("#generate");
generateButton.addEventListener("click", async () => {
  message.textContent = "생성 중… 조성표를 만든 뒤 LLM 해설을 작성합니다. 1~2분 걸릴 수 있습니다.";
  results.replaceChildren();
  reviewNotice.hidden = true;
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
    message.textContent = "완료";
  } catch (error) {
    message.textContent = error.message;
  } finally {
    generateButton.disabled = false;
    generateButton.ariaBusy = "false";
  }
});

populateModels();
refreshHealth();
