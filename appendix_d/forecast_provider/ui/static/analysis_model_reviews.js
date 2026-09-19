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

const labels = {
  INVESTIGATING: ["確認中", "warning"],
  DATA_ISSUE: ["データ要因", "negative"],
  BUSINESS_EVENT: ["業務要因", "neutral"],
  MODEL_ISSUE: ["モデル要因", "negative"],
  NO_ACTION: ["問題なし", "positive"],
};

export function renderModelReviewOptions(drift, reviews) {
  const select = document.getElementById("model-review-profile");
  const previous = select.value;
  const options = (drift?.series || [])
    .filter((series) => series.history_count >= 2)
    .map((series) => node("option", {
      value: series.comparison_profile_id,
      text: `${series.provider_id} / ${series.model_id}｜${series.latest.test_start}〜${series.latest.test_end}｜${directionLabel(series.direction)}`,
    }));
  select.replaceChildren(...options);
  if (options.some((option) => option.value === previous)) select.value = previous;
  const button = document.getElementById("model-review-submit");
  button.dataset.locked = String(!options.length);
  if (!document.getElementById("model-review-version").value) {
    setSuggestedReviewVersion(reviews);
  }
}

export function setSuggestedReviewVersion(reviews) {
  const profileId = document.getElementById("model-review-profile").value;
  const count = (reviews || []).filter(
    (review) => review.comparison_profile_id === profileId,
  ).length;
  document.getElementById("model-review-version").value = `review-v${count + 1}`;
}

export function renderModelReviews(reviews) {
  const values = reviews || [];
  document.getElementById("model-review-count").textContent = `${values.length}件`;
  if (!values.length) {
    document.getElementById("model-review-list").replaceChildren(node("div", {
      className: "empty-inline",
      text: "精度変化の調査・判断履歴はまだありません。",
    }));
    return;
  }
  const cards = values.map((review) => {
    const [label, tone] = labels[review.conclusion] || [review.conclusion, "neutral"];
    const evidence = review.evidence;
    return node("article", { className: "model-review-card" }, [
      node("div", { className: "model-review-card-heading" }, [
        node("strong", { text: `${evidence.provider_id} / ${evidence.model_id}` }),
        node("span", { className: `pill ${tone}`, text: label }),
      ]),
      node("p", {
        text: `${evidence.latest.test_start}〜${evidence.latest.test_end} / WAPE変化 ${signed(evidence.wape_change_pct_points)}pt`,
      }),
      node("dl", {}, [
        node("dt", { text: "判断版" }), node("dd", { text: review.decision_version }),
        node("dt", { text: "根拠" }), node("dd", { text: review.reason }),
        node("dt", { text: "対応" }), node("dd", { text: review.action }),
        node("dt", { text: "記録者" }), node("dd", { text: review.reviewed_by }),
        node("dt", { text: "記録日時" }), node("dd", { text: review.reviewed_at }),
      ]),
    ]);
  });
  document.getElementById("model-review-list").replaceChildren(...cards);
}

function directionLabel(direction) {
  return {
    WAPE_UP: "WAPE上昇",
    WAPE_DOWN: "WAPE低下",
    UNCHANGED: "変化なし",
  }[direction] || direction;
}

function signed(value) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${Number(value).toFixed(2)}`;
}
