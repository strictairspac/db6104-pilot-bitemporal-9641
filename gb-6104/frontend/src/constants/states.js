export const States = Object.freeze({
  queued: "等待执行", running: "正在执行", done: "已完成", failed: "执行失败", voided: "已作废",
});

export const Actions = Object.freeze({
  create_case: "登记资料", enqueue: "提交执行", done: "执行完成", failed: "执行失败",
  review: "复核签署", correct: "登记更正",
});
