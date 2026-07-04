from __future__ import annotations

from dataclasses import dataclass, field
from urllib.robotparser import RobotFileParser


@dataclass(slots=True)
class RobotsPolicy:
    robots_url: str
    body: str
    available: bool = True
    _parser: RobotFileParser = field(init=False, repr=False)

    def __post_init__(self) -> None:
        parser = RobotFileParser()
        parser.set_url(self.robots_url)
        parser.parse(self.body.splitlines())
        self._parser = parser

    @classmethod
    def unavailable(cls, robots_url: str) -> "RobotsPolicy":
        return cls(robots_url=robots_url, body="", available=False)

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if not self.available:
            return True
        return self._parser.can_fetch(user_agent, url)

    def crawl_delay(self, user_agent: str) -> float | None:
        if not self.available:
            return None
        delay = self._parser.crawl_delay(user_agent)
        if delay is None:
            delay = self._parser.crawl_delay("*")
        return float(delay) if delay is not None else None
