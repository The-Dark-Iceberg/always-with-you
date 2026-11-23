"""整理任务：把待整理的摘要和便条交给 AI，按 rules.md 写进记忆库。"""

from importlib import resources


def rules_text() -> str:
    return resources.files(__package__).joinpath("rules.md").read_text(encoding="utf-8")
