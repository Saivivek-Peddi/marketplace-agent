"""Terminal UI — colors, formatting, and pretty output."""

from __future__ import annotations

# ANSI color codes
class C:
    RESET    = "\033[0m"
    BOLD     = "\033[1m"
    DIM      = "\033[2m"
    ITALIC   = "\033[3m"

    # Colors
    BLUE     = "\033[38;5;75m"
    GREEN    = "\033[38;5;78m"
    YELLOW   = "\033[38;5;220m"
    RED      = "\033[38;5;203m"
    PURPLE   = "\033[38;5;141m"
    CYAN     = "\033[38;5;116m"
    GRAY     = "\033[38;5;245m"
    WHITE    = "\033[38;5;255m"
    ORANGE   = "\033[38;5;215m"

    # Backgrounds
    BG_DARK  = "\033[48;5;236m"
    BG_BLUE  = "\033[48;5;24m"
    BG_GREEN = "\033[48;5;22m"
    BG_RED   = "\033[48;5;52m"
    BG_YELLOW= "\033[48;5;58m"


# Box drawing
BOX_H = "─"
BOX_V = "│"
BOX_TL = "╭"
BOX_TR = "╮"
BOX_BL = "╰"
BOX_BR = "╯"

WIDTH = 60


def banner():
    """Print the startup banner."""
    print()
    print(f"  {C.BLUE}{C.BOLD}╭{'─' * 50}╮{C.RESET}")
    print(f"  {C.BLUE}{C.BOLD}│{C.RESET}  {C.PURPLE}{C.BOLD}  Marketplace Agent  {C.RESET}                            {C.BLUE}{C.BOLD}│{C.RESET}")
    print(f"  {C.BLUE}{C.BOLD}│{C.RESET}  {C.DIM}AI-powered ride booking assistant{C.RESET}               {C.BLUE}{C.BOLD}│{C.RESET}")
    print(f"  {C.BLUE}{C.BOLD}╰{'─' * 50}╯{C.RESET}")
    print()


def model_menu(models: dict) -> str:
    """Pretty model selection menu."""
    print(f"  {C.CYAN}{C.BOLD}Select a model:{C.RESET}")
    print()
    for key, (model_id, desc) in models.items():
        icon = "⚡" if "Haiku" in desc else "🧠" if "Opus" in desc else "✨"
        print(f"    {C.WHITE}{C.BOLD}{key}{C.RESET}{C.DIM} ){C.RESET}  {icon}  {C.WHITE}{desc}{C.RESET}")
    print()
    choice = input(f"  {C.CYAN}Choice [1]: {C.RESET}").strip() or "1"
    return choice


def status_line(model: str, guardrails: bool = True):
    """Print the status bar."""
    g_status = f"{C.GREEN}ON{C.RESET}" if guardrails else f"{C.RED}OFF{C.RESET}"
    print(f"  {C.DIM}Model:{C.RESET} {C.WHITE}{model}{C.RESET}  {C.DIM}│{C.RESET}  {C.DIM}Guardrails:{C.RESET} {g_status}")
    print(f"  {C.DIM}Type {C.WHITE}'quit'{C.DIM} to exit{C.RESET}")
    print()
    print(f"  {C.DIM}{'─' * 50}{C.RESET}")
    print()


def user_prompt() -> str:
    """Styled user input prompt."""
    try:
        return input(f"  {C.GREEN}{C.BOLD}You ➤{C.RESET}  ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def agent_message(text: str):
    """Print agent response with styling."""
    lines = text.split("\n")
    print()
    for i, line in enumerate(lines):
        if i == 0:
            print(f"  {C.BLUE}{C.BOLD}Agent ➤{C.RESET}  {C.WHITE}{line}{C.RESET}")
        else:
            print(f"           {C.WHITE}{line}{C.RESET}")
    print()


def agent_blocked():
    """Print when guardrail blocks output."""
    print()
    print(f"  {C.BLUE}{C.BOLD}Agent ➤{C.RESET}  {C.WHITE}I'm a ride booking assistant. Where would you like to go?{C.RESET}")
    print()


def thinking():
    """Print thinking indicator."""
    print(f"  {C.DIM}  ⏳ Thinking...{C.RESET}", end="\r")


def clear_thinking():
    """Clear thinking indicator."""
    print(f"  {' ' * 30}", end="\r")


def tool_call(name: str):
    """Show tool being called."""
    icons = {
        "search_rides": "🔍",
        "get_quote": "💰",
        "book_ride": "🚗",
        "check_status": "📍",
        "cancel_ride": "❌",
        "save_place": "📌",
        "save_preference": "⚙️",
        "get_profile": "👤",
        "check_surge": "📈",
        "get_suggestions": "💡",
    }
    icon = icons.get(name, "🔧")
    print(f"  {C.DIM}  {icon} {name}{C.RESET}")


def confirmation_box(tool_name: str, details: list[str] | None = None) -> str:
    """Pretty confirmation gate. Returns user input."""
    icons = {"book_ride": "🚗", "cancel_ride": "❌"}
    icon = icons.get(tool_name, "⚠️")
    actions = {"book_ride": "BOOK this ride", "cancel_ride": "CANCEL this ride"}
    action = actions.get(tool_name, tool_name)

    print()
    print(f"  {C.YELLOW}╭{'─' * 48}╮{C.RESET}")
    print(f"  {C.YELLOW}│{C.RESET}  {icon}  {C.YELLOW}{C.BOLD}CONFIRMATION REQUIRED{C.RESET}                      {C.YELLOW}│{C.RESET}")
    print(f"  {C.YELLOW}│{C.RESET}                                                {C.YELLOW}│{C.RESET}")
    print(f"  {C.YELLOW}│{C.RESET}  The agent wants to {C.WHITE}{C.BOLD}{action}{C.RESET}{'.' * max(0, 27 - len(action))}{C.YELLOW}│{C.RESET}")

    if details:
        for detail in details:
            padded = detail[:44].ljust(44)
            print(f"  {C.YELLOW}│{C.RESET}  {C.DIM}{padded}{C.RESET}  {C.YELLOW}│{C.RESET}")

    print(f"  {C.YELLOW}│{C.RESET}                                                {C.YELLOW}│{C.RESET}")
    answer = input(f"  {C.YELLOW}│{C.RESET}  {C.YELLOW}Approve? (yes/no):{C.RESET} ")
    approved = answer.strip().lower() in ("yes", "y")

    if approved:
        print(f"  {C.YELLOW}│{C.RESET}  {C.GREEN}✓ Approved{C.RESET}                                     {C.YELLOW}│{C.RESET}")
    else:
        print(f"  {C.YELLOW}│{C.RESET}  {C.RED}✗ Denied{C.RESET}                                       {C.YELLOW}│{C.RESET}")

    print(f"  {C.YELLOW}╰{'─' * 48}╯{C.RESET}")
    print()
    return answer.strip().lower()


def error(msg: str):
    """Print error message."""
    print(f"  {C.RED}{C.BOLD}Error:{C.RESET} {C.RED}{msg}{C.RESET}")


def info(msg: str):
    """Print info message."""
    print(f"  {C.DIM}{msg}{C.RESET}")


def success(msg: str):
    """Print success message."""
    print(f"  {C.GREEN}✓{C.RESET} {C.WHITE}{msg}{C.RESET}")


def recovery(msg: str):
    """Print recovery message."""
    print(f"  {C.ORANGE}↺{C.RESET} {C.ORANGE}{msg}{C.RESET}")


def goodbye():
    """Print exit message."""
    print()
    print(f"  {C.DIM}Thanks for riding! 👋{C.RESET}")
    print()


def saved_places(places: dict[str, str]):
    """Show saved places on startup."""
    if not places:
        print(f"  {C.DIM}No saved places yet. Say \"save home as 123 Main St\" to add one.{C.RESET}")
        return
    print(f"  {C.CYAN}{C.BOLD}Your Places:{C.RESET}")
    for name, addr in places.items():
        icon = "🏠" if name == "home" else "🏢" if name == "work" else "📍"
        print(f"    {icon}  {C.WHITE}{C.BOLD}{name}{C.RESET} {C.DIM}→{C.RESET} {C.WHITE}{addr}{C.RESET}")
    print(f"  {C.DIM}Say \"save gym as 456 Oak St\" to add more, or \"change home to ...\" to update.{C.RESET}")


def preferences(prefs: dict):
    """Show preferences on startup."""
    if not prefs:
        return
    car = prefs.get("default_car_type", "comfort")
    confirm = prefs.get("always_confirm", True)
    print(f"  {C.DIM}Default car:{C.RESET} {C.WHITE}{car}{C.RESET}  {C.DIM}│{C.RESET}  {C.DIM}Confirm before booking:{C.RESET} {C.WHITE}{'yes' if confirm else 'no'}{C.RESET}")


def recent_rides(rides: list[dict]):
    """Show recent rides on startup."""
    if not rides:
        return
    print(f"  {C.CYAN}{C.BOLD}Recent Rides:{C.RESET}")
    for r in rides[:5]:
        fr = r.get("from", "?")
        to = r.get("to", "?")
        car = r.get("car_type", "?")
        price = r.get("price", "?")
        status = r.get("status", "")
        status_icon = {"completed": "✅", "canceled": "❌", "processing": "⏳"}.get(status, "🚗")
        price_str = f"${price}" if isinstance(price, (int, float)) else str(price)
        print(f"    {status_icon}  {C.DIM}{fr} → {to}{C.RESET} {C.DIM}({car}, {price_str}){C.RESET}")


def session_info(session_name: str):
    """Show current session name."""
    print(f"  {C.DIM}Session:{C.RESET} {C.WHITE}{session_name}{C.RESET}")


def conversation_history(messages: list[dict], stats: dict):
    """Print conversation history on session resume."""
    import datetime

    last_ts = stats.get("last_message_at")
    if last_ts:
        dt = datetime.datetime.fromtimestamp(last_ts)
        ago = datetime.datetime.now() - dt
        if ago.days > 0:
            time_str = f"{ago.days}d ago"
        elif ago.seconds > 3600:
            time_str = f"{ago.seconds // 3600}h ago"
        elif ago.seconds > 60:
            time_str = f"{ago.seconds // 60}m ago"
        else:
            time_str = "just now"
    else:
        time_str = "unknown"

    msg_count = stats.get("messages", 0)
    ep_count = stats.get("episodes", 0)

    print(f"  {C.CYAN}{C.BOLD}Conversation History:{C.RESET} {C.DIM}({msg_count} messages, {ep_count} events, last active {time_str}){C.RESET}")
    print()

    for msg in messages:
        content = msg["content"]
        role = msg["role"]
        # Truncate long messages
        if len(content) > 120:
            content = content[:117] + "..."

        if role == "user":
            print(f"    {C.GREEN}You ➤{C.RESET}  {C.DIM}{content}{C.RESET}")
        else:
            print(f"    {C.BLUE}Agent ➤{C.RESET}  {C.DIM}{content}{C.RESET}")

    print()
    print(f"  {C.DIM}{'─' * 50}{C.RESET}")
    print(f"  {C.DIM}Resuming conversation...{C.RESET}")
    print()


def server_connected():
    """Print server connected."""
    print(f"  {C.GREEN}✓{C.RESET} {C.DIM}Server connected{C.RESET}")


def server_failed(url: str):
    """Print server connection failure."""
    print(f"  {C.RED}✗{C.RESET} {C.RED}Server not running at {url}{C.RESET}")
    print(f"  {C.DIM}  Start it first: ./start-agent.sh{C.RESET}")
