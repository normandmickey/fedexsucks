import asyncio
import os
from dataclasses import dataclass


@dataclass
class ResearchResult:
    topic: str
    report: str
    sources: list[str]


class ResearchConfigurationError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = (os.getenv(name) or '').strip()
    if not value:
        raise ResearchConfigurationError(f'Missing required environment variable: {name}')
    return value


async def _run_gpt_researcher(topic: str) -> ResearchResult:
    from gpt_researcher import GPTResearcher

    _require_env('OPENAI_API_KEY')
    _require_env('TAVILY_API_KEY')

    researcher = GPTResearcher(query=topic)
    await researcher.conduct_research()
    report = await researcher.write_report()

    context = getattr(researcher, 'context', []) or []
    sources: list[str] = []
    for item in context:
        if isinstance(item, dict):
            url = (item.get('url') or item.get('source') or '').strip()
            if url and url not in sources:
                sources.append(url)
    return ResearchResult(topic=topic, report=report or '', sources=sources)


def run_research(topic: str) -> ResearchResult:
    cleaned = (topic or '').strip()
    if not cleaned:
        raise ValueError('Topic is required.')
    return asyncio.run(_run_gpt_researcher(cleaned))
