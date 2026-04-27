"""Entry point for `python -m agent`."""

import sys
from pathlib import Path

from .main import Agent
from .memory import list_sessions
from . import ui


def main():
    session_name = "default"

    # Check for --session flag
    args = sys.argv[1:]
    if "--session" in args:
        idx = args.index("--session")
        if idx + 1 < len(args):
            session_name = args[idx + 1]
        else:
            print("Usage: python -m agent --session <name>")
            sys.exit(1)
    elif "--sessions" in args or "--list" in args:
        sessions = list_sessions()
        if not sessions:
            print("  No sessions yet. Start one with: python -m agent --session myname")
        else:
            print(f"  {ui.C.CYAN}{ui.C.BOLD}Available Sessions:{ui.C.RESET}")
            for s in sessions:
                print(f"    {ui.C.WHITE}{s}{ui.C.RESET}")
        sys.exit(0)
    elif "--new" in args:
        idx = args.index("--new")
        if idx + 1 < len(args):
            session_name = args[idx + 1]
        else:
            print("Usage: python -m agent --new <name>")
            sys.exit(1)
    elif "--clear" in args:
        import shutil
        sessions_dir = Path("sessions")
        if sessions_dir.exists():
            count = len(list(sessions_dir.glob("*.db")))
            shutil.rmtree(sessions_dir)
            print(f"  {ui.C.GREEN}✓{ui.C.RESET} Cleared {count} session(s)")
        else:
            print(f"  {ui.C.DIM}No sessions to clear{ui.C.RESET}")
        sys.exit(0)
    elif "--help" in args or "-h" in args:
        print("Usage: python -m agent [OPTIONS]")
        print()
        print("Options:")
        print("  --session <name>   Resume a named session")
        print("  --new <name>       Start a new named session")
        print("  --sessions         List all sessions")
        print("  --clear            Delete all sessions and start fresh")
        print("  --help             Show this help")
        print()
        print("Examples:")
        print("  python -m agent                     # default session")
        print("  python -m agent --new morning-ride   # new session")
        print("  python -m agent --session morning-ride  # resume session")
        print("  python -m agent --sessions           # list all")
        sys.exit(0)

    Agent(session_name=session_name).start()


main()
