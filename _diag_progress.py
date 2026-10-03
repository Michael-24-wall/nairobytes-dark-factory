import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.backend.db import session

RUN_ID = sys.argv[1]


def main():
    with session() as conn:
        run = conn.execute("SELECT status, current_stage, error, execution_mode, started_at,"
                           " completed_at FROM factory_runs WHERE id=%s", (RUN_ID,)).fetchone()
        print("RUN:", json.dumps({k: str(v) for k, v in dict(run).items()}, indent=2))
        print("\nEVENT COUNTS:")
        for row in conn.execute("SELECT event_type, count(*) AS n, max(created_at) AS last"
                                "  FROM factory_events WHERE factory_run_id=%s"
                                " GROUP BY event_type ORDER BY event_type", (RUN_ID,)).fetchall():
            print(f"   {row['event_type']:24} {row['n']:4}  {row['last']}")
        print("\nRECENT EVENTS:")
        for row in conn.execute("SELECT stage, event_type, left(message,110) AS msg, created_at"
                                "  FROM factory_events WHERE factory_run_id=%s"
                                " ORDER BY created_at DESC, id DESC LIMIT 14", (RUN_ID,)).fetchall():
            print(f"   {row['created_at']} {row['stage']:11} {row['event_type']:20} {row['msg']}")
        print("\nTASKS:")
        for row in conn.execute("SELECT sequence, agent_role, status, verdict, handed_to,"
                                " agent_session_id, started_at, completed_at"
                                "  FROM factory_tasks WHERE factory_run_id=%s ORDER BY sequence",
                                (RUN_ID,)).fetchall():
            print(f"   seq{row['sequence']} {row['agent_role']:10} {row['status']:11} "
                  f"verdict={row['verdict'] or '-':5} ->{row['handed_to'] or '-':9} "
                  f"session={row['agent_session_id'] or '-'} {row['started_at']} -> {row['completed_at']}")


if __name__ == "__main__":
    main()