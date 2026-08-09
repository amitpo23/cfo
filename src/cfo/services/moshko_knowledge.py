"""Human-facing, read-only view over Moshko's existing knowledge sources."""
from __future__ import annotations

from typing import Any

from . import kb_loader, rezef_kb


def list_topics() -> dict[str, Any]:
    topics = [
        {
            "id": f"rezef:{key}",
            "source": "rezef_kb",
            "title": key,
            "summary": rezef_kb.TOPIC_SUMMARIES[key],
        }
        for key in rezef_kb.TOPICS
    ]
    index = kb_loader.kb_index()
    if index.get("available"):
        center = next(
            (item for item in index["centers"] if item["key"] == "bookkeeper_kb"),
            None,
        )
        if center is None:
            document_knowledge = {
                "available": False,
                "topics": None,
                "reason": "מרכז הידע המקצועי bookkeeper_kb אינו ארוז בסביבה זו",
            }
        else:
            document_topics = [
                {
                    "id": f"bookkeeper_kb:{item['filename']}",
                    "source": "bookkeeper_kb",
                    "title": item["title"],
                    "summary": item["summary"],
                }
                for item in center["files"]
            ]
            topics.extend(document_topics)
            document_knowledge = {
                "available": True,
                "topics": document_topics,
                "reason": None,
            }
    else:
        document_knowledge = {
            "available": False,
            "topics": None,
            "reason": index.get("reason") or kb_loader.NOT_AVAILABLE_REASON,
        }
    return {
        "available": True,
        "topics": topics,
        "document_knowledge": document_knowledge,
    }


def get_topic(topic_id: str) -> dict[str, Any]:
    if topic_id.startswith("rezef:"):
        key = topic_id.removeprefix("rezef:")
        if key not in rezef_kb.TOPICS:
            return {"available": True, "found": False}
        return {
            "available": True,
            "found": True,
            "id": topic_id,
            "source": "rezef_kb",
            "title": key,
            "format": "markdown",
            "content": rezef_kb.TOPICS[key],
        }
    if topic_id.startswith("bookkeeper_kb:"):
        filename = topic_id.removeprefix("bookkeeper_kb:")
        result = kb_loader.kb_document("bookkeeper_kb", filename)
        if not result.get("available"):
            return {
                "available": False,
                "found": None,
                "id": topic_id,
                "reason": result["reason"],
                "content": None,
            }
        if not result.get("found"):
            return {"available": True, "found": False}
        return {
            "available": True,
            "found": True,
            "id": topic_id,
            "source": "bookkeeper_kb",
            "title": result["title"],
            "format": "markdown",
            "content": result["content"],
        }
    return {"available": True, "found": False}
