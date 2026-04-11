from pathlib import Path

from scripts.lib.time import utc_now_iso8601


def append_wiki_log(log_path: Path, title: str, lines: list[str]) -> None:
    if not log_path.exists():
        log_path.write_text("# Log\n\n", encoding="utf-8")
    timestamp = utc_now_iso8601()
    payload = [f"## [{timestamp}] {title}"]
    payload.extend(f"- {line}" for line in lines)
    payload.append("")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(payload) + "\n")
