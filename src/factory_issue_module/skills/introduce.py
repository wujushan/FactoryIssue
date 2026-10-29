"""介绍（设计 §4.3 `introduce` 一行、§9.4）：不取数，事件为 `delta` → `suggestions`。

- 寒暄、问能力（含「嗯」「测试」「讲个笑话」这类招呼与闲聊）：做能力介绍，三域都介绍，没权限的域注「申请后可查」。
- 只读之外的请求、本助手管不着的事：按总述「业务定位」答，附能力介绍的 3 个按钮；不介绍别的模块。
"""

from __future__ import annotations

from forge_core.events import Event
from forge_core.module import ModuleManifest

from factory_issue_module.turn import errors, greeting
from factory_issue_module.turn.gate import DomainAccess

_ANSWER = {"只读请求": errors.READ_ONLY, "超出范围": errors.OUT_OF_SCOPE}


def run(params: dict, manifest: ModuleManifest, access: DomainAccess) -> list[Event]:
    answer = _ANSWER.get(str(params.get("kind") or ""))
    if answer is None:
        return greeting.introduce(manifest, access)
    events = [Event.delta(f"{answer}。")]
    recs = greeting.buttons(access)
    if recs:
        events.append(Event.suggestions(recs))
    return events
