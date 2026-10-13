"""Request-scoped model/usage hooks; unrelated callers retain their defaults."""

from contextvars import ContextVar

CURRENT = ContextVar("bunsen_ai_request", default=None)


def options(default_model):
    context = CURRENT.get()
    model = context["model"] if context else default_model
    if model == "gpt-4.1-mini":
        return {"model": model, "temperature": 0}
    return {"model": model, "reasoning": {"effort": "none" if model == "gpt-6-luna" else "low"}}


def observe(response):
    context = CURRENT.get()
    if context:
        context["response"] = response
