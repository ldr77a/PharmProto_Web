import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const appSource = readFileSync(
  new URL("../pharma_proto/static/app.js", import.meta.url),
  "utf8",
);

function fakeElement(initial = {}) {
  const listeners = new Map();
  return Object.assign({
    value: "",
    textContent: "",
    hidden: false,
    disabled: false,
    dataset: {},
    children: [],
    focused: false,
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    async dispatch(type, event) {
      return listeners.get(type)?.(event);
    },
    append(...children) {
      for (const child of children) {
        this.children.push(child);
        if (child.selected) this.value = child.value;
      }
    },
    replaceChildren() {
      this.children = [];
      this.value = "";
    },
    focus() {
      this.focused = true;
    },
  }, initial);
}

function browserHarness({generatePayload, followupPayloads = [], routes = {}} = {}) {
  const eventLog = [];
  const provider = fakeElement({value: "openai"});
  const tier = fakeElement({value: "normal"});
  const apiKey = fakeElement();
  const question = fakeElement({value: "배합 질문"});
  const results = fakeElement();
  const reviewNotice = fakeElement({hidden: true});
  const elements = {
    "#provider": provider,
    "#tier": tier,
    "#api-key": apiKey,
    "#question": question,
    "#message": fakeElement(),
    "#setup-message": fakeElement(),
    "#results": results,
    "#api-setup": fakeElement(),
    "#research-app": fakeElement({hidden: true}),
    "#review-notice": reviewNotice,
    "#selected-model": fakeElement(),
    "#model-catalog": fakeElement({
      textContent: JSON.stringify({
        openai: {
          cheap: "gpt-5.6-luna",
          normal: "gpt-5.6-terra",
          good: "gpt-5.6-sol",
        },
      }),
    }),
    "#health": fakeElement(),
    "#save-key": fakeElement(),
    "#logout": fakeElement(),
    "#theme-toggle": fakeElement({textContent: "화면: 시스템"}),
    "#print": fakeElement(),
    "#result-actions": fakeElement({hidden: true}),
    "#save-result": fakeElement(),
    "#save-status": fakeElement(),
    "#refresh-results": fakeElement(),
    "#results-list": fakeElement(),
    "#help-popover": fakeElement({hidden: true}),
    "#help-title": fakeElement(),
    "#help-body": fakeElement(),
    "#help-close": fakeElement(),
    "#help-text": fakeElement({textContent: JSON.stringify({
      "src:kg_role": {title: "KG 역할별 범위", text: "같은 역할로 쓰인 배합의 중앙값입니다."},
      "gate:1": {title: "게이트1 사용량 범위", text: "실제 배합 범위와 비교합니다."},
    })}),
    "#followup-panel": fakeElement({hidden: true}),
    "#followup-question": fakeElement(),
    "#followup-log": fakeElement(),
    "#followup": fakeElement(),
    "#generate": fakeElement(),
  };

  Object.defineProperty(results, "innerHTML", {
    get() {
      return this._innerHTML || "";
    },
    set(value) {
      this._innerHTML = value;
      this.buttons = [...value.matchAll(/data-candidate-index="(\d+)"/g)].map(
        (match) => fakeElement({
          disabled: true,
          dataset: {candidateIndex: match[1]},
        }),
      );
      this.hasCard = value.includes('class="card"');
    },
  });
  results.replaceChildren = function replaceChildren() {
    this.innerHTML = "";
  };
  results.querySelectorAll = (selector) => (
    selector === ".download-xlsx" ? (results.buttons || []) : []
  );
  results.querySelector = (selector) => (
    selector === ".card" && results.hasCard ? {} : null
  );

  const body = {
    children: [],
    append(child) {
      child.isConnected = true;
      this.children.push(child);
      eventLog.push(["append", child.download]);
    },
  };

  const documentElement = fakeElement({dataset: {theme: "system"}});
  const windowListeners = new Map();
  const documentListeners = new Map();
  const window = {
    print() {
      eventLog.push(["print"]);
    },
    addEventListener(type, listener) {
      windowListeners.set(type, listener);
    },
  };
  const document = {
    body,
    documentElement,
    querySelector(selector) {
      return elements[selector];
    },
    querySelectorAll() {
      return [];
    },
    addEventListener(type, listener) {
      documentListeners.set(type, listener);
    },
    createElement(tag) {
      if (tag === "option") return fakeElement({selected: false});
      if (tag === "a") {
        const anchor = fakeElement({href: "", download: "", isConnected: false});
        anchor.click = () => eventLog.push([
          "click",
          anchor.download,
          anchor.isConnected,
        ]);
        anchor.remove = () => {
          anchor.isConnected = false;
          body.children = body.children.filter((item) => item !== anchor);
          eventLog.push(["remove", anchor.download]);
        };
        return anchor;
      }
      return fakeElement();
    },
  };

  const fetchCalls = [];
  async function fetch(url, options = {}) {
    fetchCalls.push([url, options]);
    const routeKey = `${options.method || "GET"} ${url}`;
    if (routeKey in routes) {
      const route = routes[routeKey];
      const routed = typeof route === "function" ? route(options) : route;
      return {ok: true, async json() { return routed; }};
    }
    const payload = url === "/health"
      ? {
          status: "ok",
          app_version: "0.1.0",
          snapshot_id: "test",
          schema_version: 1,
        }
      : url === "/api/generate"
        ? generatePayload
        : url === "/api/followup"
          ? followupPayloads.shift()
          : url === "/api/logout"
            ? {ok: true}
            : {provider: "openai", configured: true};
    return {ok: true, async json() { return payload; }};
  }

  let urlIndex = 0;
  const context = vm.createContext({
    document,
    window,
    fetch,
    console,
    Blob,
    Uint8Array,
    atob,
    URL: {
      createObjectURL() {
        const url = `blob:test-${++urlIndex}`;
        eventLog.push(["create", url]);
        return url;
      },
      revokeObjectURL(url) {
        eventLog.push(["revoke", url]);
      },
    },
    setTimeout(callback) {
      callback();
    },
  });
  vm.runInContext(appSource, context);

  return {elements, eventLog, fetchCalls, results, documentElement, windowListeners, documentListeners};
}

test("API 확인 후 선택한 전체 모델명과 연구 화면을 표시한다", async () => {
  const harness = browserHarness();
  harness.elements["#api-key"].value = "test-key";

  await harness.elements["#save-key"].dispatch("click");

  assert.equal(harness.elements["#api-setup"].hidden, true);
  assert.equal(harness.elements["#research-app"].hidden, false);
  assert.equal(harness.elements["#selected-model"].textContent, "gpt-5.6-terra");
  assert.equal(harness.elements["#api-key"].value, "");
});

test("로그아웃하면 서버의 키를 지우고 이전 결과를 제거한다", async () => {
  const harness = browserHarness();
  harness.results.innerHTML = '<div class="card">이전 결과</div>';
  harness.elements["#review-notice"].hidden = false;

  await harness.elements["#logout"].dispatch("click");

  const logoutCall = harness.fetchCalls.find(([url]) => url === "/api/logout");
  assert.equal(logoutCall[1].method, "POST");
  assert.equal(harness.results.innerHTML, "");
  assert.equal(harness.elements["#review-notice"].hidden, true);
  assert.equal(harness.elements["#research-app"].hidden, true);
  assert.equal(harness.elements["#api-setup"].hidden, false);
});

test("생성된 후보 3개의 Excel 버튼을 각각 올바른 파일에 연결한다", async () => {
  const html = [1, 2, 3].map(
    (index) => `<div class="card"><button class="download-xlsx" data-candidate-index="${index}" disabled></button></div>`,
  ).join("");
  const downloads = [1, 2, 3].map((index) => ({
    candidate_idx: index,
    filename: `조성_후보_${index}.xlsx`,
    content_base64: "WA==",
  }));
  const harness = browserHarness({generatePayload: {html, downloads}});

  await harness.elements["#generate"].dispatch("click");

  assert.equal(harness.results.buttons.length, 3);
  assert.deepEqual(harness.results.buttons.map((button) => button.disabled), [false, false, false]);
  assert.equal(harness.elements["#review-notice"].hidden, false);

  for (const button of harness.results.buttons) await button.dispatch("click");
  const clicks = harness.eventLog.filter(([event]) => event === "click");
  assert.deepEqual(
    clicks,
    [1, 2, 3].map((index) => ["click", `조성_후보_${index}.xlsx`, true]),
  );
  assert.equal(harness.eventLog.filter(([event]) => event === "revoke").length, 3);
});

test("후속 질문: refine 이면 결과를 교체하고 answer 면 로그에만 덧붙인다", async () => {
  const card = (label) => `<div class="card"><button class="download-xlsx" data-candidate-index="1" disabled></button>${label}</div>`;
  const downloads = [{candidate_idx: 1, filename: "조성_후보_1.xlsx", content_base64: "WA=="}];
  const conversationId = "a".repeat(32);
  const harness = browserHarness({
    generatePayload: {html: card("처음"), downloads, conversation_id: conversationId},
    followupPayloads: [
      {conversation_id: conversationId, action: "refine", changed: true, html: card("수정"), downloads,
       answer_html: "<div class='card followup'>후보 수: 3 → 1</div>"},
      {conversation_id: conversationId, action: "answer", html: card("수정"), downloads,
       answer_html: "<div class='card followup'>근거</div>"},
    ],
  });

  await harness.elements["#generate"].dispatch("click");
  assert.equal(harness.elements["#followup-panel"].hidden, false);

  harness.elements["#followup-question"].value = "후보 1개로";
  await harness.elements["#followup"].dispatch("click");
  const [, refineOptions] = harness.fetchCalls.find(([url]) => url === "/api/followup");
  assert.deepEqual(JSON.parse(refineOptions.body), {
    provider: "openai", tier: "normal", conversation_id: conversationId, question: "후보 1개로",
  });
  assert.ok(harness.results.innerHTML.includes("수정"));
  assert.equal(harness.elements["#followup-log"].children.length, 1);
  assert.equal(harness.elements["#followup-question"].value, "");

  harness.elements["#followup-question"].value = "왜 이 결합제?";
  await harness.elements["#followup"].dispatch("click");
  assert.equal(harness.elements["#followup-log"].children.length, 2);
  assert.ok(harness.results.innerHTML.includes("수정"));

  await harness.elements["#logout"].dispatch("click");
  assert.equal(harness.elements["#followup-panel"].hidden, true);
  assert.equal(harness.elements["#followup-log"].children.length, 0);
});

test("화면 색 토글은 시스템→밝게→어둡게로 순환하며 서버에 저장하고, 인쇄 버튼은 window.print 를 부른다", async () => {
  const harness = browserHarness();
  assert.equal(harness.elements["#theme-toggle"].textContent, "화면: 시스템");

  await harness.elements["#theme-toggle"].dispatch("click");

  assert.equal(harness.documentElement.dataset.theme, "light");
  assert.equal(harness.elements["#theme-toggle"].textContent, "화면: 밝게");
  const [, options] = harness.fetchCalls.find(([url]) => url === "/api/preferences");
  assert.equal(options.method, "PUT");
  assert.deepEqual(JSON.parse(options.body), {theme: "light"});

  await harness.elements["#theme-toggle"].dispatch("click");
  assert.equal(harness.documentElement.dataset.theme, "dark");
  await harness.elements["#theme-toggle"].dispatch("click");
  assert.equal(harness.documentElement.dataset.theme, "system");

  await harness.elements["#print"].dispatch("click");
  assert.ok(harness.eventLog.some(([event]) => event === "print"));
  assert.ok(harness.windowListeners.has("beforeprint") && harness.windowListeners.has("afterprint"));
});

test("저장 버튼은 대화를 저장하고 목록을 갱신하며, 열기는 읽기 전용으로·삭제는 목록에서 지운다", async () => {
  const card = (label) => `<div class="card"><button class="download-xlsx" data-candidate-index="1" disabled></button>${label}</div>`;
  const downloads = [{candidate_idx: 1, filename: "조성_후보_1.xlsx", content_base64: "WA=="}];
  const resultId = "20261004T120000Z-aaaaaaaa";
  const summary = {id: resultId, saved_at: "2026-10-04T12:00:00+00:00", question_preview: "아세트아미노펜 500 mg",
                   api_names: ["acetaminophen"], n_candidates: 1, snapshot_id: "test"};
  let deleted = false;
  const harness = browserHarness({
    generatePayload: {html: card("처음"), downloads, conversation_id: "a".repeat(32)},
    routes: {
      "POST /api/results": {result_id: resultId},
      "GET /api/results": () => ({results: deleted ? [] : [summary]}),
      [`GET /api/results/${resultId}`]: {id: resultId, saved_at: summary.saved_at, html: card("저장본"), downloads,
        turns: [{role: "assistant", kind: "answer", text: "x", html: "<div class='card followup'>x</div>"}], resumable: true},
      [`DELETE /api/results/${resultId}`]: () => { deleted = true; return {deleted: true}; },
    },
  });

  await harness.elements["#generate"].dispatch("click");
  assert.equal(harness.elements["#result-actions"].hidden, false);

  await harness.elements["#save-result"].dispatch("click");
  const [, saveOptions] = harness.fetchCalls.find(([url, options]) => url === "/api/results" && options.method === "POST");
  assert.deepEqual(JSON.parse(saveOptions.body), {conversation_id: "a".repeat(32)});
  assert.ok(harness.elements["#save-status"].textContent.includes("저장됨"));
  assert.equal(harness.elements["#results-list"].children.length, 1);

  const [openButton, , deleteButton] = harness.elements["#results-list"].children[0].children[2].children;
  await openButton.dispatch("click");
  assert.ok(harness.results.innerHTML.includes("저장본"));
  assert.equal(harness.elements["#followup-log"].children.length, 1);
  assert.equal(harness.elements["#followup-panel"].hidden, false);
  assert.equal(harness.elements["#followup"].disabled, true);          // 열람만 — '이어서 질문' 전에는 입력 불가

  await deleteButton.dispatch("click");
  assert.equal(harness.elements["#results-list"].children.length, 1);
  assert.equal(harness.elements["#results-list"].children[0].className, "empty");
});

test("근거 꼬리표·게이트 칩을 클릭하면 쉬운 말 설명이 열리고 닫기·ESC 로 닫힌다", async () => {
  const harness = browserHarness();
  const trigger = (help, text) => ({
    dataset: {help}, textContent: text,
    closest(selector) { return selector === "[data-help]" ? this : null; },
  });

  await harness.results.dispatch("click", {target: trigger("src:kg_role", "KG 역할별 범위, n=10"), preventDefault() {}});

  assert.equal(harness.elements["#help-popover"].hidden, false);
  assert.equal(harness.elements["#help-title"].textContent, "KG 역할별 범위");
  assert.ok(harness.elements["#help-body"].textContent.includes("중앙값"));
  assert.equal(harness.elements["#help-close"].focused, true);

  await harness.elements["#help-close"].dispatch("click");
  assert.equal(harness.elements["#help-popover"].hidden, true);

  await harness.results.dispatch("click", {target: trigger("src:mystery", "정체불명")});
  assert.equal(harness.elements["#help-title"].textContent, "정체불명");
  assert.ok(harness.elements["#help-body"].textContent.includes("준비되지"));

  harness.documentListeners.get("keydown")({key: "Escape"});
  assert.equal(harness.elements["#help-popover"].hidden, true);

  await harness.results.dispatch("click", {target: {closest: () => null}});     // 설명 아닌 곳 클릭은 무시
  assert.equal(harness.elements["#help-popover"].hidden, true);
});
