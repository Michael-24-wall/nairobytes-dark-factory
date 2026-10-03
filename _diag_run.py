import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.backend.db import session

RUN_ID = "db69954a-4cc8-4aa0-85ae-812a7997ab7d"


def main():
    with session() as conn:
        run = conn.execute("SELECT * FROM factory_runs WHERE id=%s", (RUN_ID,)).fetchone()
        print("=== RUN ===")
        print(json.dumps({k: (str(v) if k in {"id", "project_id"} else v) for k, v in dict(run).items()}, indent=2, default=str))

        print("\n=== TASKS ===")
        for row in conn.execute(
            "SELECT id, sequence, agent_role, task_type, status, verdict, handed_to, agent_session_id,"
            " started_at, completed_at, error, left(input, 200) AS input_head, left(output, 400) AS output_head"
            "  FROM factory_tasks WHERE factory_run_id=%s ORDER BY sequence, started_at",
            (RUN_ID,),
        ).fetchall():
            print(json.dumps(dict(row), indent=2, default=str))

        print("\n=== EVENTS ===")
        for row in conn.execute(
            "SELECT id, stage, event_type, agent_role, source_agent, destination_agent, status,"
            " left(message, 300) AS message, metadata, created_at"
            "  FROM factory_events WHERE factory_run_id=%s ORDER BY created_at, id",
            (RUN_ID,),
        ).fetchall():
            print(json.dumps(dict(row), indent=2, default=str))

        print("\n=== ARTIFACTS ===")
        for row in conn.execute(
            "SELECT artifact_type, path, sha256, created_at FROM factory_artifacts WHERE factory_run_id=%s",
            (RUN_ID,),
        ).fetchall():
            print(json.dumps(dict(row), indent=2, default=str))

        print("\n=== PROJECT ===")
        project = conn.execute("SELECT * FROM projects WHERE id=%s", (run["project_id"],)).fetchone()
        print(json.dumps({k: str(v)[:1500] for k, v in dict(project).items()}, indent=2, default=str))


if __name__ == "__main__":
    main()