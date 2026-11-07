"""
Updates the `cron:` schedule in `.github/workflows/daily_story.yml` to a new random
hour and minute every day so daily uploads happen at organic, unpredictable times.
"""
import os
from pathlib import Path
import re
import secrets

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "daily_story.yml"


def randomize_workflow_cron() -> str:
    min_hour = int(os.getenv("MIN_UTC_HOUR", "11"))
    max_hour = int(os.getenv("MAX_UTC_HOUR", "21"))

    random_hour = min_hour + secrets.randbelow(max_hour - min_hour + 1)
    random_minute = secrets.randbelow(60)
    new_cron = f"{random_minute} {random_hour} * * *"

    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    updated_content, count = re.subn(
        r"(\s*-\s*cron:\s*['\"])([^'\"]+)(['\"])",
        rf"\g<1>{new_cron}\g<3>",
        content,
        count=1,
    )

    if count == 0:
        raise RuntimeError(f"Could not find `- cron:` line in {WORKFLOW_PATH}")

    WORKFLOW_PATH.write_text(updated_content, encoding="utf-8")
    print(f"Updated next daily GitHub Actions schedule to: '{new_cron}' (UTC)")
    return new_cron


if __name__ == "__main__":
    randomize_workflow_cron()
