import { request } from "./api.js";

const encoded = (value) => encodeURIComponent(value);

export async function loadLifecycleDashboard() {
  const [session, plans, adoptions] = await Promise.all([
    request("/api/session"),
    request("/api/lifecycle-plans"),
    request("/api/adoptions"),
  ]);
  const statuses = await Promise.all(
    plans.map((plan) => request(`/api/lifecycle-plans/${encoded(plan.plan_id)}`)),
  );
  return { session, plans, adoptions, statuses };
}

export function loadLifecyclePlan(planId) {
  const id = encoded(planId);
  return Promise.all([
    request(`/api/lifecycle-plans/${id}`),
    request(`/api/lifecycle-plans/${id}/trial-forecasts`),
    request(`/api/lifecycle-plans/${id}/trial-assessments`),
  ]).then(([status, forecasts, assessments]) => ({ status, forecasts, assessments }));
}

function post(path, payload = null) {
  const options = { method: "POST" };
  if (payload !== null) options.body = JSON.stringify(payload);
  return request(path, options);
}

export const createLifecyclePlan = (payload) => post("/api/lifecycle-plans", payload);
export const runLifecycleSchedule = () => post("/api/lifecycle-schedule");
export const completeCycle = (cycleId, payload) =>
  post(`/api/lifecycle-cycles/${encoded(cycleId)}/complete`, payload);
export const failCycle = (cycleId, payload) =>
  post(`/api/lifecycle-cycles/${encoded(cycleId)}/fail`, payload);
export const promoteCycle = (cycleId, payload) =>
  post(`/api/lifecycle-cycles/${encoded(cycleId)}/promote`, payload);
export const rollbackChampion = (planId, payload) =>
  post(`/api/lifecycle-plans/${encoded(planId)}/rollback`, payload);
export const recordTrialForecast = (planId, payload) =>
  post(`/api/lifecycle-plans/${encoded(planId)}/trial-forecasts`, payload);
export const assessTrial = (planId, payload) =>
  post(`/api/lifecycle-plans/${encoded(planId)}/trial-assessments`, payload);
