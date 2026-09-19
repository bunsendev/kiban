import { renderRetestComparison } from "./analysis_retest_results.js";

const node = (tag, options = {}, children = []) => {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "className") element.className = value;
    else if (name === "text") element.textContent = value;
    else if (value !== undefined && value !== null) element.setAttribute(name, value);
  }
  element.append(...children);
  return element;
};

const statusLabels = {
  OPEN: "未着手", IN_PROGRESS: "対応中", BLOCKED: "保留",
  COMPLETED: "完了", CANCELLED: "中止",
};

export function renderReviewActionOptions(reviews, actions) {
  const reviewSelect = document.getElementById("review-action-review");
  const previousReview = reviewSelect.value;
  const reviewOptions = (reviews || []).map((review) => node("option", {
    value: review.review_id,
    text: `${review.decision_version}｜${review.evidence.provider_id} / ${review.evidence.model_id}`,
  }));
  reviewSelect.replaceChildren(...reviewOptions);
  if (reviewOptions.some((item) => item.value === previousReview)) reviewSelect.value = previousReview;
  document.getElementById("review-action-create").dataset.locked = String(!reviewOptions.length);

  const actionSelect = document.getElementById("review-action-update-id");
  const previousAction = actionSelect.value;
  const actionOptions = (actions || []).map((action) => node("option", {
    value: action.action_id,
    text: `${statusLabels[action.status]}｜${action.title}`,
  }));
  actionSelect.replaceChildren(...actionOptions);
  if (actionOptions.some((item) => item.value === previousAction)) actionSelect.value = previousAction;
  document.getElementById("review-action-update").dataset.locked = String(!actionOptions.length);
  fillReviewActionUpdate(actions || []);
}

export function fillReviewActionUpdate(actions) {
  const actionId = document.getElementById("review-action-update-id").value;
  const action = actions.find((item) => item.action_id === actionId);
  if (!action) return;
  document.getElementById("review-action-update-status").value = action.status;
  document.getElementById("review-action-update-assignee").value = action.assignee;
  document.getElementById("review-action-update-due").value = action.due_date;
  document.getElementById("review-action-update-revision").value = action.revision;
  toggleCompletionEvidence();
}

export function renderReviewRetestOptions(actions, snapshots) {
  const actionSelect = document.getElementById("review-retest-action");
  const previousAction = actionSelect.value;
  const eligible = (actions || []).filter((item) => (
    item.action_type === "RETEST" && ["OPEN", "BLOCKED"].includes(item.status)
  ));
  const actionOptions = eligible.map((action) => node("option", {
    value: action.action_id,
    text: `${statusLabels[action.status]}｜${action.title}`,
    "data-revision": action.revision,
  }));
  actionSelect.replaceChildren(...actionOptions);
  if (actionOptions.some((item) => item.value === previousAction)) actionSelect.value = previousAction;

  const snapshotSelect = document.getElementById("review-retest-snapshot");
  const previousSnapshot = snapshotSelect.value;
  const snapshotOptions = (snapshots || []).map((snapshot) => node("option", {
    value: snapshot.snapshot_id,
    text: `${snapshot.manifest.test_start}〜${snapshot.manifest.test_end}｜${snapshot.manifest.selection_version}`,
  }));
  snapshotSelect.replaceChildren(...snapshotOptions);
  if (snapshotOptions.some((item) => item.value === previousSnapshot)) {
    snapshotSelect.value = previousSnapshot;
  }
  document.getElementById("review-retest-submit").dataset.locked = String(
    !actionOptions.length || !snapshotOptions.length,
  );
}

export function toggleCompletionEvidence() {
  const completed = document.getElementById("review-action-update-status").value === "COMPLETED";
  const field = document.getElementById("review-action-evidence-field");
  const input = document.getElementById("review-action-update-evidence");
  field.hidden = !completed;
  input.required = completed;
  if (!completed) input.value = "";
}

export function renderReviewActions(actions, events, retests, onRetestHandoff) {
  const values = actions || [];
  document.getElementById("review-action-count").textContent = `${values.length}件`;
  if (!values.length) {
    document.getElementById("review-action-list").replaceChildren(node("div", {
      className: "empty-inline", text: "対応タスクはまだありません。",
    }));
    return;
  }
  const cards = values.map((action) => {
    const history = (events || []).filter((item) => item.action_id === action.action_id);
    const eventList = node("ol", { className: "review-action-events" }, history.map((item) => (
      node("li", { text: `v${item.revision} ${statusLabels[item.status]}｜${item.recorded_by}｜${item.note}` })
    )));
    const actionRetests = (retests || []).filter((item) => item.action_id === action.action_id);
    const retestList = node("div", { className: "review-action-retests" }, actionRetests.map((item) => {
      const comparison = renderRetestComparison(item, onRetestHandoff);
      return node("article", { className: "review-action-retest" }, [
        node("strong", { text: `追加テスト ${item.status}` }),
        node("code", { text: `campaign ${item.campaign_id}${item.comparison_id ? `｜comparison ${item.comparison_id}` : ""}` }),
        ...(comparison ? [comparison] : []),
      ]);
    }));
    return node("article", { className: `review-action-card${action.overdue ? " overdue" : ""}` }, [
      node("div", { className: "model-review-card-heading" }, [
        node("strong", { text: action.title }),
        node("span", { className: `pill ${action.status === "COMPLETED" ? "positive" : "neutral"}`, text: statusLabels[action.status] }),
      ]),
      node("p", { text: `${action.action_type}｜担当 ${action.assignee}｜期限 ${action.due_date}${action.overdue ? "（期限超過）" : ""}` }),
      node("p", { text: `最新: ${action.note}｜更新者 ${action.recorded_by}` }),
      ...(action.completion_evidence ? [node("p", { text: `完了根拠: ${action.completion_evidence}` })] : []),
      eventList,
      ...(actionRetests.length ? [retestList] : []),
    ]);
  });
  document.getElementById("review-action-list").replaceChildren(...cards);
}
