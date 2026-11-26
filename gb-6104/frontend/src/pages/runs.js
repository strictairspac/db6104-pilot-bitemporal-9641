import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { status } from "../components/common/status.js";
import { table } from "../components/common/table.js";
import { poll } from "../hooks/poll.js";
import { submit } from "../hooks/submit.js";
import { el } from "../utils/dom.js";
import { time } from "../utils/format.js";

const OPEN = new Set(["queued", "running"]);

function reportState(run) {
  return el("div", {class: "stack", id: "run-state"}, status(run.status),
    el("p", {}, OPEN.has(run.status) ? "后台正在处理，页面会自动更新。"
      : run.status === "voided" ? "此稿已作废，不能签核；晚到的结果也不会再入库。"
      : run.failure || run.result?.summary),
    run.superseded_by_run_id
      ? el("a", {href: `#runs/${run.superseded_by_run_id}`}, `已由更正 ${run.superseded_by_code} 取代，查看新批次 #${run.superseded_by_run_id}`)
      : null,
    run.status === "done" && !run.superseded_by_run_id
      ? el("a", {class: "button", href: `#evidence/${run.id}`}, "查看业务证据") : null);
}

function correctionForm(run) {
  const previous = run.adjustments && Object.keys(run.adjustments).length
    ? JSON.stringify(run.adjustments, null, 2) : "{}";
  const form = el("form", {id: "correction-form"},
    field("更正单号", el("input", {name: "code", required: true, maxlength: 30, placeholder: "例如 ADJ-20261126-1"})),
    field("更正吨位", el("textarea", {name: "adjustments", required: true, rows: 6, spellcheck: "false"}, previous),
      "按航次填写更正后的总吨，例如 {\"LC-V21\": 3700}。原账仍按开账吨位，复核账按更正吨位。"),
    field("更正说明", el("textarea", {name: "note", maxlength: 500, rows: 2})),
    errorText(), el("button", {type: "submit"}, "登记更正"));
  submit(form, async values => {
    let adjustments;
    try {
      adjustments = JSON.parse(values.get("adjustments"));
    } catch {
      throw new Error("更正吨位 JSON 无法解析，请检查括号、引号和逗号");
    }
    const correction = await api.submitCorrection(run.id, {
      code: values.get("code").trim(), adjustments, note: values.get("note").trim(),
    });
    location.hash = `runs/${correction.run_id}`;
  });
  return form;
}

function correctionPanel(run, review, canCorrect) {
  if (run.superseded_by_run_id) {
    return section("吨位更正",
      el("p", {}, `本批次已由更正 ${run.superseded_by_code} 取代并作废，不能再签核或登记更正。`),
      el("a", {class: "button", href: `#runs/${run.superseded_by_run_id}`}, "查看新批次"));
  }
  const context = run.correction_code
    ? [el("p", {}, `本批次由更正单 ${run.correction_code} 生成：原账照用开账吨位，复核账用更正吨位，按原复核日重算。`)]
    : [];
  if (review) context.push(el("p", {}, "本批次已签核，不能再登记更正。"));
  if (!canCorrect) return context.length ? section("吨位更正", context) : null;
  return section("吨位更正", ...context, [
    el("p", {}, "原账照用开账吨位，复核账用更正吨位，按原复核日重算。更正后另起一批待签，未签的旧稿作废。"),
    correctionForm(run),
  ]);
}

export async function runsPage(config, user, route, signal) {
  const items = await api.runs();
  const latest = route.id ? await api.run(route.id, signal) : items[0];
  const detail = latest ? reportState(latest) : empty("进入资料页，选用一个业务样本并提交执行。");
  const review = latest ? await api.review(latest.id) : null;
  const canCorrect = Boolean(latest) && user.role === "operator" && !review
    && !latest.superseded_by_run_id && (latest.status === "done" || OPEN.has(latest.status));

  async function refresh() {
    try {
      const next = await api.run(latest.id, signal);
      if (!signal.aborted) {
        detail.replaceChildren(...reportState(next).childNodes);
        const badge = document.querySelector(`[data-run="${next.id}"] .status`);
        if (badge) badge.replaceWith(status(next.status));
      }
      return OPEN.has(next.status);
    } catch (error) {
      if (!signal.aborted) detail.append(el("p", {role: "alert"}, error.message));
      return false;
    }
  }
  if (latest && OPEN.has(latest.status)) poll(refresh, signal);

  const panel = latest ? correctionPanel(latest, review, canCorrect) : null;
  return el("div", {class: "page"},
    pageHeading(config.modules[2], config.parameter_label),
    latest ? section(latest.case_title, detail) : detail,
    panel,
    section("执行批次", items.length ? table(["资料", "编号", "参数", "类型", "状态", "提交时间"],
      items.map(run => [el("a", {"data-run": run.id, href: `#runs/${run.id}`}, run.case_title), run.id,
        run.parameter, run.kind === "correction" ? `更正 ${run.correction_code || ""}`.trim() : "原复核",
        el("span", {"data-run": run.id}, status(run.status)), time(run.created_at)]), "执行批次") :
      empty("暂无执行记录。")));
}
