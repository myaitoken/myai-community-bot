"""
MyAI Network — TGE Marketing & Community Bot v2.0
===================================================
@MyAI_Token_bot — 24/7 marketing, community engagement, and TGE conversion engine.
"""

import asyncio, logging, os, json, aiohttp, sqlite3
from datetime import datetime, timedelta, timezone
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ChatMemberHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ChatMemberStatus, ParseMode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("MYAI_COMMUNITY_BOT_TOKEN", "")
CHANNEL_ID  = int(os.getenv("MYAI_CHANNEL_ID", "0"))
ADMIN_IDS   = {6116357813, 549224749, 1626015659}  # Jason, Justin, Tanner
ANTI_SPAM   = os.getenv("ANTI_SPAM", "true").lower() == "true"
DB_PATH     = "/opt/myai-community-bot/analytics.db"

# ── Token constants ───────────────────────────────────────────────────────────
CONTRACT    = "0xAfF22CC20434ce43B3ea10efe10e9360390D327c"
SHORT_ADDR  = "0xAfF22CC...327c"
CHAIN_ID    = "8453"
GENESIS_MAX = 100

# URLs
URL_MARKET  = "https://myaitoken.io/marketplace"
URL_DOCS    = "https://myaitoken.io/docs"
URL_NETWORK = "https://myaitoken.io/network"
URL_INVEST  = "https://myaitoken.io/invest"
URL_BUY     = "https://myaitoken.io/buy"
URL_SECURITY= "https://myaitoken.io/security"
URL_COMM    = "https://myaitoken.io/community"
URL_BASE    = f"https://basescan.org/token/{CONTRACT}"
URL_AERO    = f"https://aerodrome.finance/swap?outputCurrency={CONTRACT}"

# ── Analytics DB ──────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        joined_at TEXT, referrer_id INTEGER, genesis_slot INTEGER,
        commands_used INTEGER DEFAULT 0, last_seen TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS referrals (
        referrer_id INTEGER, referred_id INTEGER, created_at TEXT,
        PRIMARY KEY (referrer_id, referred_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS command_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, command TEXT, ts TEXT
    )""")
    conn.commit()
    conn.close()

def db_get_user_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count

def db_get_genesis_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM users WHERE genesis_slot IS NOT NULL").fetchone()[0]
    conn.close()
    return count

def db_register_user(user_id: int, username: str, first_name: str, referrer_id: int = None) -> int:
    """Register user, assign genesis slot if available. Returns genesis slot or 0."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = c.execute("SELECT genesis_slot FROM users WHERE user_id=?", (user_id,)).fetchone()
    if existing:
        conn.close()
        return existing[0] or 0
    genesis_count = c.execute("SELECT COUNT(*) FROM users WHERE genesis_slot IS NOT NULL").fetchone()[0]
    slot = (genesis_count + 1) if genesis_count < GENESIS_MAX else None
    now = datetime.now(timezone.utc).isoformat()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, referrer_id, genesis_slot, last_seen) VALUES (?,?,?,?,?,?,?)",
              (user_id, username, first_name, now, referrer_id, slot, now))
    if referrer_id:
        c.execute("INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (?,?,?)",
                  (referrer_id, user_id, now))
    conn.commit()
    conn.close()
    return slot or 0

def db_log_command(user_id: int, command: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    c.execute("INSERT INTO command_log (user_id, command, ts) VALUES (?,?,?)", (user_id, command, now))
    c.execute("UPDATE users SET commands_used=commands_used+1, last_seen=? WHERE user_id=?", (now, user_id))
    conn.commit()
    conn.close()

def db_get_referral_count(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,)).fetchone()[0]
    conn.close()
    return count

def db_get_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    genesis = c.execute("SELECT COUNT(*) FROM users WHERE genesis_slot IS NOT NULL").fetchone()[0]
    referrals = c.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
    cmds_today = c.execute("SELECT COUNT(*) FROM command_log WHERE ts >= date('now')").fetchone()[0]
    active_week = c.execute("SELECT COUNT(*) FROM users WHERE last_seen >= date('now','-7 days')").fetchone()[0]
    conn.close()
    return {"total": total, "genesis": genesis, "referrals": referrals, "cmds_today": cmds_today, "active_week": active_week}

# ── TGE Countdown ─────────────────────────────────────────────────────────────
TGE_TARGET = datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc)

def tge_countdown() -> str:
    now = datetime.now(timezone.utc)
    diff = TGE_TARGET - now
    if diff.total_seconds() <= 0:
        return "🎉 TGE IS LIVE"
    days = diff.days
    hours, rem = divmod(diff.seconds, 3600)
    mins, secs = divmod(rem, 60)
    return f"{days}d {hours:02d}h {mins:02d}m {secs:02d}s"

def genesis_bar() -> str:
    claimed = db_get_genesis_count()
    remaining = GENESIS_MAX - claimed
    pct = int((claimed / GENESIS_MAX) * 10)
    bar = "█" * pct + "░" * (10 - pct)
    return f"[{bar}] {claimed}/{GENESIS_MAX} claimed • {remaining} remaining"

# ── Keyboards ─────────────────────────────────────────────────────────────────
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 TGE Status", callback_data="tge"),
         InlineKeyboardButton("🎯 Genesis Window", callback_data="genesis")],
        [InlineKeyboardButton("🖥 List My GPU", url=URL_MARKET),
         InlineKeyboardButton("💰 Buy MYAI", url=URL_AERO)],
        [InlineKeyboardButton("📚 Developer Docs", url=URL_DOCS),
         InlineKeyboardButton("📊 Live Network", url=URL_NETWORK)],
        [InlineKeyboardButton("📄 Investor Info", url=URL_INVEST),
         InlineKeyboardButton("🔐 Security", url=URL_SECURITY)],
        [InlineKeyboardButton("📢 Official Channel", url="https://t.me/MyAITokenNews"),
         InlineKeyboardButton("🌐 Website", url="https://myaitoken.io")],
        [InlineKeyboardButton("🔗 Refer & Earn", callback_data="refer"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
    ])

def kb_tge() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💧 Trade on Aerodrome", url=URL_AERO),
         InlineKeyboardButton("🦄 Uniswap (Base)", url=f"https://app.uniswap.org/swap?outputCurrency={CONTRACT}&chain=base")],
        [InlineKeyboardButton("📊 Live Network", url=URL_NETWORK),
         InlineKeyboardButton("🔍 Basescan", url=URL_BASE)],
        [InlineKeyboardButton("🎯 Join Genesis Window", callback_data="genesis"),
         InlineKeyboardButton("📚 How It Works", url=URL_DOCS)],
        [InlineKeyboardButton("📢 TGE Channel", url="https://t.me/MyAITokenNews"),
         InlineKeyboardButton("🔒 Security", url=URL_SECURITY)],
        [InlineKeyboardButton("◀ Back", callback_data="main")],
    ])

def kb_gpu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥 List My Node", url=URL_MARKET)],
        [InlineKeyboardButton("📚 Provider Guide", url=f"{URL_DOCS}#providers"),
         InlineKeyboardButton("📊 Live Stats", url=URL_NETWORK)],
        [InlineKeyboardButton("◀ Back", callback_data="main")],
    ])

def kb_dev() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Full Docs", url=URL_DOCS),
         InlineKeyboardButton("⚡ ADK Quickstart", url=f"{URL_DOCS}#sdk")],
        [InlineKeyboardButton("🌐 API Reference", url=f"{URL_DOCS}#api"),
         InlineKeyboardButton("💼 Wallets Guide", url=f"{URL_DOCS}#wallets")],
        [InlineKeyboardButton("◀ Back", callback_data="main")],
    ])

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀ Back to Menu", callback_data="main")]])

# ── Message templates ─────────────────────────────────────────────────────────
def msg_welcome(first_name: str, genesis_slot: int, referrals: int = 0) -> str:
    genesis_line = f"\n🏅 *Genesis Slot #{genesis_slot} secured\\!* \\+2\\-5x staking boost earned\\." if genesis_slot else f"\n⚠️ Genesis window \\({GENESIS_MAX} slots\\) is {genesis_bar()}"
    return (
        f"👋 Welcome to *MyAI Network*, {escape(first_name)}\\! 🚀\n\n"
        f"We're building the world's largest decentralized GPU compute marketplace on Base\\.\n"
        f"{genesis_line}\n\n"
        f"📌 *TGE STATUS*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 Liquidity lock: *PENDING* \\(Aerodrome Finance\\)\n"
        f"⏱ Estimated: `{escape(tge_countdown())}`\n"
        f"🪙 Token: *MYAI* on Base \\(`{SHORT_ADDR}`\\)\n"
        f"🎯 Genesis: {genesis_bar()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*How to participate:*\n"
        f"• 🖥 GPU Provider → /marketplace → List My Node\n"
        f"• 💻 Developer → `pip install myai\\-adk` → /docs\n"
        f"• 💰 Investor → /invest\n"
        f"• 🔗 Refer friends → /refer\n\n"
        f"_Testnet participants: 1:1 ratio to mainnet\\. Migration is automatic\\._"
    )

def msg_tge_status() -> str:
    claimed = db_get_genesis_count()
    return (
        f"🚀 *MyAI TGE Status*\n\n"
        f"⏱ *Countdown:* `{escape(tge_countdown())}`\n"
        f"🔒 *Liquidity:* PENDING — Aerodrome Finance \\(Base\\)\n"
        f"🪙 *Token:* MYAI \\| Base Chain ID 8453\n"
        f"📍 *Contract:* `{CONTRACT}`\n\n"
        f"🎯 *Genesis Window:*\n"
        f"{genesis_bar()}\n"
        f"First {GENESIS_MAX} participants → NFT badge \\+ 2\\-5x staking boost\n\n"
        f"✅ *Token Features:*\n"
        f"• OpenAI\\-compatible API \\(1/10th the cost\\)\n"
        f"• DePIN: real GPU compute, real payouts\n"
        f"• Locked liquidity — no rug risk\n"
        f"• 1:1 testnet → mainnet for ambassadors\n\n"
        f"[View Contract on Basescan]({URL_BASE})"
    )

def msg_genesis(user_id: int) -> str:
    claimed = db_get_genesis_count()
    remaining = GENESIS_MAX - claimed
    referrals = db_get_referral_count(user_id)
    ref_bonus = "✅ Referral bonus active\\!" if referrals > 0 else f"Refer friends to boost your chances: /refer"
    heat_msg = "🔥 Almost full — join NOW\\!" if remaining < 20 else f"⚡ {remaining} slots remaining"
    return (
        f"🎯 *Genesis Window*\n\n"
        f"*{genesis_bar()}*\n\n"
        f"{heat_msg}\n\n"
        f"*Genesis perks:*\n"
        f"• 🏅 Exclusive Genesis NFT badge\n"
        f"• ⚡ 2\\-5x staking boost at TGE\n"
        f"• 🗳 Enhanced governance weight\n"
        f"• 📊 Priority job routing on network\n"
        f"• 🏆 Listed on leaderboard as Genesis member\n\n"
        f"*Your referrals:* {referrals} friends referred\n"
        f"{ref_bonus}\n\n"
        f"_List your GPU or submit a job to lock your slot:_"
    )

def msg_refer(user_id: int) -> str:
    count = db_get_referral_count(user_id)
    bot_link = f"https://t.me/MyAI_Token_bot?start=ref_{user_id}"
    return (
        f"🔗 *Refer \\& Earn*\n\n"
        f"*Your referral link:*\n"
        f"`{bot_link}`\n\n"
        f"*Your referrals:* {count} friends\n\n"
        f"*Rewards per referral:*\n"
        f"• 🎯 Each friend you bring → counts toward your Genesis slot\n"
        f"• 🏆 Top referrers featured on leaderboard\n"
        f"• 💰 10% of referred user earnings \\(post\\-TGE\\)\n"
        f"• 🏅 5\\+ referrals → guaranteed Genesis slot\n\n"
        f"_Share your link and help build the world's largest GPU compute marketplace\\!_"
    )

def escape(text: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

def is_admin(uid): return uid in ADMIN_IDS

# ── Callback handler ──────────────────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id

    if data == "main":
        await q.edit_message_text(
            "🤖 *MyAI Network — TGE Marketing Bot*\n\nChoose an option below:",
            parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_main()
        )
    elif data == "tge":
        await q.edit_message_text(msg_tge_status(), parse_mode=ParseMode.MARKDOWN_V2,
                                   reply_markup=kb_tge(), disable_web_page_preview=True)
    elif data == "genesis":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖥 List My GPU Node", url=URL_MARKET)],
            [InlineKeyboardButton("💰 Buy MYAI", url=URL_AERO)],
            [InlineKeyboardButton("🔗 Refer Friends", callback_data="refer")],
            [InlineKeyboardButton("◀ Back", callback_data="main")],
        ])
        await q.edit_message_text(msg_genesis(uid), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb)
    elif data == "refer":
        await q.edit_message_text(msg_refer(uid), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_back())
    elif data == "help":
        await q.edit_message_text(msg_help(), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_back())
    elif data == "gpu":
        await q.edit_message_text(
            "🖥 *GPU Provider Guide*\n\nTurn idle hardware into MYAI income\\.\n\n"
            "*Supported hardware:* Any GPU with 8GB\\+ VRAM\n"
            "*Setup:* Install Ollama → Register node → Earn per job\n"
            "*Models:* DeepSeek R1, Llama 3, Qwen 2\\.5, Mistral\n\n"
            "`pip install ollama`\n`ollama serve`\n\nThen register at marketplace →",
            parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_gpu()
        )
    elif data == "dev":
        await q.edit_message_text(
            "💻 *Developer Quickstart*\n\nOpenAI\\-compatible API — zero code changes\\.\n\n"
            "*Python ADK:*\n`pip install myai\\-adk`\n\n"
            "*Node.js SDK:*\n`npm install @myai/adk`\n\n"
            "*API endpoint:*\n`https://api.myaitoken.io/v1/chat/completions`\n\n"
            "*Cost:* ~0\\.001 MYAI per job \\(sub\\-cent\\)",
            parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_dev()
        )

# ── Command handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = ctx.args
    referrer_id = None
    if args and args[0].startswith("ref_"):
        try:
            referrer_id = int(args[0][4:])
            if referrer_id == user.id:
                referrer_id = None
        except ValueError:
            pass

    slot = db_register_user(user.id, user.username or "", user.first_name or "", referrer_id)
    db_log_command(user.id, "start")

    if referrer_id:
        try:
            await ctx.bot.send_message(
                referrer_id,
                f"🎉 *New referral\\!* {escape(user.first_name or 'Someone')} joined via your link\\!\n"
                f"Total referrals: {db_get_referral_count(referrer_id)}",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            pass

    await update.message.reply_text(
        msg_welcome(user.first_name or "friend", slot),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb_main(),
        disable_web_page_preview=True
    )

async def cmd_tgelaunch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "tgelaunch")
    await update.message.reply_text(msg_tge_status(), parse_mode=ParseMode.MARKDOWN_V2,
                                     reply_markup=kb_tge(), disable_web_page_preview=True)

async def cmd_tge(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "tge")
    await update.message.reply_text(msg_tge_status(), parse_mode=ParseMode.MARKDOWN_V2,
                                     reply_markup=kb_tge(), disable_web_page_preview=True)

async def cmd_marketplace(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "marketplace")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥 List My GPU Node", url=URL_MARKET)],
        [InlineKeyboardButton("🤖 Browse AI Agents", url=f"{URL_MARKET}#agents")],
        [InlineKeyboardButton("💼 Post a Job", url=f"{URL_MARKET}#jobs")],
        [InlineKeyboardButton("📊 Live Network", url=URL_NETWORK)],
    ])
    await update.message.reply_text(
        "🖥 *MyAI Marketplace*\n\n"
        "The decentralized GPU compute marketplace on Base\\.\n\n"
        "*For GPU Providers:*\n"
        "• Install Ollama → Register node → Earn MYAI\n"
        "• Any GPU with 8GB\\+ VRAM qualifies\n"
        "• Mac Mini, gaming PC, server, cloud VM\n\n"
        "*For AI Developers:*\n"
        "• Browse available agents and models\n"
        "• Post compute jobs\n"
        "• Pay sub\\-cent per inference\n\n"
        f"🎯 Genesis window: {genesis_bar()}",
        parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb
    )

async def cmd_docs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "docs")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Full Docs", url=URL_DOCS),
         InlineKeyboardButton("⚡ ADK Quickstart", url=f"{URL_DOCS}#sdk")],
        [InlineKeyboardButton("🌐 API Reference", url=f"{URL_DOCS}#api"),
         InlineKeyboardButton("🔑 TGE Guide", url=f"{URL_DOCS}#liquidity")],
        [InlineKeyboardButton("💼 Wallet Integration", url=f"{URL_DOCS}#wallets")],
    ])
    await update.message.reply_text(
        "📚 *Developer Docs*\n\n"
        "*Python ADK:*\n`pip install myai\\-adk`\n\n"
        "*Node\\.js SDK:*\n`npm install @myai/adk`\n\n"
        "*API \\(OpenAI\\-compatible\\):*\n"
        "`POST https://api.myaitoken.io/v1/chat/completions`\n"
        "`Authorization: Bearer myai\\-sk\\-YOUR_KEY`\n\n"
        "*Models:* DeepSeek R1, Llama 3\\.2, Qwen 2\\.5, Mistral 7B\n"
        "*Cost:* 0\\.001 MYAI per job \\(~$0\\.0001\\)",
        parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb
    )

async def cmd_network(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "network")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://myaitoken.io/healthz", timeout=aiohttp.ClientTimeout(total=5)) as r:
                health = "🟢 OPERATIONAL" if r.status == 200 else f"🔴 HTTP {r.status}"
    except Exception:
        health = "🟡 Unknown"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Live Dashboard", url=URL_NETWORK)],
        [InlineKeyboardButton("🖥 Register Your Node", url=URL_MARKET)],
        [InlineKeyboardButton("🏆 Leaderboard", url="https://myaitoken.io/leaderboard")],
    ])
    await update.message.reply_text(
        f"🌐 *MyAI Live Network*\n\n"
        f"API Status: {escape(health)}\n"
        f"Contract: Deployed ✅\n"
        f"Liquidity: Pending 🔒\n"
        f"Community: {db_get_user_count()} bot users\n\n"
        f"_Real\\-time GPU providers, job volume, burn tracker, and leaderboard_",
        parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb
    )

async def cmd_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "wallet")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Coinbase Wallet (Best)", url="https://wallet.coinbase.com")],
        [InlineKeyboardButton("🦊 MetaMask", url="https://metamask.io"),
         InlineKeyboardButton("🌈 Rainbow", url="https://rainbow.me")],
        [InlineKeyboardButton("💰 Buy MYAI", url=URL_AERO),
         InlineKeyboardButton("🔍 Add to Wallet", url=URL_BUY)],
    ])
    await update.message.reply_text(
        "👛 *Connect Your Wallet*\n\n"
        "*Network:* Base \\(Chain ID 8453\\)\n"
        f"*MYAI Contract:*\n`{CONTRACT}`\n\n"
        "*Recommended wallets:*\n"
        "• 🔵 Coinbase Wallet — native Base support\n"
        "• 🦊 MetaMask — add Base via chainlist\\.org/chain/8453\n"
        "• 🌈 Rainbow — best mobile UX\n"
        "• WalletConnect v2 — hardware wallets\n\n"
        "*Add MYAI to MetaMask:*\n"
        "1\\. Network: Base \\(8453\\)\n"
        f"2\\. Contract: `{CONTRACT}`\n"
        "3\\. Symbol: MYAI \\| Decimals: 18\n\n"
        "⚠️ _Always verify the contract address above\\!_",
        parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "status")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://myaitoken.io/healthz", timeout=aiohttp.ClientTimeout(total=5)) as r:
                health = "🟢 OPERATIONAL" if r.status == 200 else f"🔴 HTTP {r.status}"
    except Exception:
        health = "🟡 Unreachable"
    genesis = db_get_genesis_count()
    users = db_get_user_count()
    await update.message.reply_text(
        f"📡 *System Status*\n\n"
        f"API: {escape(health)}\n"
        f"Contract: ✅ Verified on Base\n"
        f"Liquidity: 🔒 Pending lock\n"
        f"TGE Countdown: `{escape(tge_countdown())}`\n\n"
        f"👥 Bot Community: {users} users\n"
        f"🎯 Genesis: {genesis}/{GENESIS_MAX} claimed",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def cmd_refer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_log_command(user.id, "refer")
    await update.message.reply_text(
        msg_refer(user.id), parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Check Genesis Status", callback_data="genesis")],
            [InlineKeyboardButton("📊 Live Network", url=URL_NETWORK)],
        ])
    )

async def cmd_invest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "invest")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Full One-Pager", url=URL_INVEST)],
        [InlineKeyboardButton("💰 Buy MYAI", url=URL_AERO),
         InlineKeyboardButton("🔍 Contract", url=URL_BASE)],
        [InlineKeyboardButton("📬 Press Contact", url="mailto:press@myaitoken.io")],
    ])
    await update.message.reply_text(
        "📄 *Investor Information*\n\n"
        "*Token:* MYAI \\| Base \\(Chain ID 8453\\)\n"
        f"*Contract:* `{CONTRACT}`\n"
        "*DEX:* Aerodrome Finance \\(vAMM, locked liquidity\\)\n"
        "*Model:* DePIN — real GPU compute, real payouts\n"
        "*Testnet ratio:* 1:1 → mainnet for ambassadors\n\n"
        "*InfiniHash compliance stack:*\n"
        "• KYC identity verification \\(18,715\\+ OFAC entries\\)\n"
        "• KYT transaction monitoring \\(BTC/ETH/TRX\\)\n"
        "• ClearBox atomic settlement \\(Lloyd's underwritten\\)\n\n"
        "*Contact:* press@myaitoken\\.io",
        parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb
    )

async def cmd_contract(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "contract")
    await update.message.reply_text(
        f"🪙 *MYAI Token Contract*\n\n`{CONTRACT}`\n\n"
        f"*Network:* Base \\(Chain ID 8453\\)\n"
        f"*Standard:* ERC\\-20\n"
        f"*DEX:* Aerodrome Finance \\(vAMM\\)\n\n"
        f"[View on Basescan]({URL_BASE})",
        parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True
    )

async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "buy")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Aerodrome (Primary)", url=URL_AERO)],
        [InlineKeyboardButton("🦄 Uniswap (Base)", url=f"https://app.uniswap.org/swap?outputCurrency={CONTRACT}&chain=base"),
         InlineKeyboardButton("🔵 BaseSwap", url=f"https://app.baseswap.fi/swap?outputCurrency={CONTRACT}")],
        [InlineKeyboardButton("📖 Full Buy Guide", url=URL_BUY)],
    ])
    await update.message.reply_text(
        f"💰 *Buy MYAI Token*\n\n"
        f"*Contract:* `{CONTRACT}`\n"
        f"*Network:* Base \\(Chain ID 8453\\)\n\n"
        f"*Primary DEX:* Aerodrome Finance \\(locked liquidity\\)\n\n"
        f"⚠️ Always verify the contract before buying\\!",
        parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb
    )

async def cmd_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "rules")
    await update.message.reply_text(
        "📋 *Community Rules*\n\n"
        "1\\. Be respectful — no harassment or hate speech\n"
        "2\\. No spam or repetitive messages\n"
        "3\\. No unsolicited links — admins only\n"
        "4\\. No price speculation or moon talk\n"
        "5\\. No scams — we *never* DM first\n"
        "6\\. Stay on topic — MyAI, DePIN, GPU, Base, AI\n"
        "7\\. English only in main chat\n"
        "8\\. DYOR — do your own research\n\n"
        "⚠️ _3 warnings = kick\\. Scams = instant ban\\._",
        parse_mode=ParseMode.MARKDOWN_V2
    )

# ── Agent-friendly JSON commands ──────────────────────────────────────────────
async def cmd_status_json(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "status_json")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://myaitoken.io/healthz", timeout=aiohttp.ClientTimeout(total=5)) as r:
                api_status = "operational" if r.status == 200 else f"error_{r.status}"
    except Exception:
        api_status = "unreachable"
    stats = db_get_stats()
    data = {
        "token": "MYAI",
        "contract": CONTRACT,
        "chain_id": 8453,
        "network": "Base",
        "tge_status": "pending",
        "liquidity_lock": "pending",
        "dex": "Aerodrome Finance",
        "countdown": tge_countdown(),
        "genesis_claimed": db_get_genesis_count(),
        "genesis_max": GENESIS_MAX,
        "api_status": api_status,
        "community_users": stats["total"],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    await update.message.reply_text(f"```json\n{json.dumps(data, indent=2)}\n```", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_network_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "network_stats")
    stats = db_get_stats()
    data = {
        "community": {"total_users": stats["total"], "active_7d": stats["active_week"], "referrals": stats["referrals"]},
        "genesis": {"claimed": stats["genesis"], "max": GENESIS_MAX, "remaining": GENESIS_MAX - stats["genesis"]},
        "engagement": {"commands_today": stats["cmds_today"]},
        "tge": {"countdown": tge_countdown(), "status": "pending"},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    await update.message.reply_text(f"```json\n{json.dumps(data, indent=2)}\n```", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_get_compute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "get_compute")
    data = {
        "api_endpoint": "https://api.myaitoken.io/v1/chat/completions",
        "api_compatible": "OpenAI v1",
        "auth": "Bearer myai-sk-YOUR_KEY",
        "models": ["deepseek-r1:7b", "llama3.2:latest", "qwen2.5:7b", "qwen2.5-coder:7b", "llama3.1:8b", "mistral:7b"],
        "cost_per_job": "0.001 MYAI",
        "cost_usd_approx": "$0.0001",
        "docs": "https://myaitoken.io/docs",
        "contract": CONTRACT,
        "chain_id": 8453
    }
    await update.message.reply_text(f"```json\n{json.dumps(data, indent=2)}\n```", parse_mode=ParseMode.MARKDOWN_V2)

def msg_help() -> str:
    return (
        "🤖 *MyAI Bot Commands*\n\n"
        "*Community:*\n"
        "/start — Welcome \\& join genesis window\n"
        "/tge — TGE countdown \\& status\n"
        "/marketplace — GPU marketplace\n"
        "/wallet — Wallet setup guide\n"
        "/buy — Where to buy MYAI\n"
        "/contract — Token contract address\n"
        "/invest — Investor information\n"
        "/refer — Referral link \\& rewards\n"
        "/network — Live network stats\n"
        "/docs — Developer documentation\n"
        "/rules — Community rules\n"
        "/status — System health check\n\n"
        "*For AI Agents:*\n"
        "/status\\_json — Machine\\-readable status\n"
        "/network\\_stats — Community analytics JSON\n"
        "/get\\_compute — API endpoint info JSON\n\n"
        "*Admin only:*\n"
        "/pin /warn /mute /kick /ban /analytics"
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_log_command(update.effective_user.id, "help")
    await update.message.reply_text(msg_help(), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_main())

# ── Admin commands ────────────────────────────────────────────────────────────
async def cmd_analytics(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    stats = db_get_stats()
    await update.message.reply_text(
        f"📊 *Analytics Dashboard*\n\n"
        f"👥 Total users: {stats['total']}\n"
        f"🎯 Genesis claimed: {stats['genesis']}/{GENESIS_MAX}\n"
        f"🔗 Total referrals: {stats['referrals']}\n"
        f"⚡ Commands today: {stats['cmds_today']}\n"
        f"📅 Active this week: {stats['active_week']}\n\n"
        f"⏱ TGE countdown: `{escape(tge_countdown())}`",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def cmd_pin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    msg = await update.message.reply_text(
        "Welcome to the *MyAI Network* community\\! 🚀\n\n"
        "We're building the world's largest decentralized GPU compute marketplace on Base\\.\n\n"
        "📌 *PINNED — TGE ANNOUNCEMENT*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 Liquidity lock: *PENDING* \\(Aerodrome Finance\\)\n"
        f"⏱ Countdown: `{escape(tge_countdown())}`\n"
        f"🪙 Token: *MYAI* on Base \\(`{SHORT_ADDR}`\\)\n"
        f"🎯 Genesis window: {genesis_bar()}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*How to participate:*\n"
        "• GPU Provider → myaitoken\\.io/marketplace → List My Node\n"
        "• AI Developer → `pip install myai\\-adk` → myaitoken\\.io/docs\n"
        "• Investor → myaitoken\\.io/invest\n\n"
        "_Testnet participants: 1:1 ratio to mainnet\\. Migration is automatic\\._",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Live Network", url=URL_NETWORK),
             InlineKeyboardButton("💰 Buy MYAI", url=URL_AERO)],
            [InlineKeyboardButton("🖥 List GPU", url=URL_MARKET),
             InlineKeyboardButton("📚 Docs", url=URL_DOCS)],
        ]),
        disable_web_page_preview=True
    )
    await ctx.bot.pin_chat_message(update.effective_chat.id, msg.message_id)
    await update.message.reply_text("📌 Pinned\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    warn_counts[target.id] = warn_counts.get(target.id, 0) + 1
    count = warn_counts[target.id]
    if count >= 3:
        await ctx.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"🚫 {escape(target.full_name)} banned after 3 warnings\\.", parse_mode=ParseMode.MARKDOWN_V2)
        warn_counts.pop(target.id, None)
    else:
        await update.message.reply_text(f"⚠️ Warning {count}/3 — {escape(target.full_name)}", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    await ctx.bot.restrict_chat_member(update.effective_chat.id, target.id,
        ChatPermissions(can_send_messages=False), until_date=datetime.now(timezone.utc) + timedelta(hours=1))
    await update.message.reply_text(f"🔇 {escape(target.full_name)} muted 1h\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    await ctx.bot.ban_chat_member(update.effective_chat.id, target.id)
    await ctx.bot.unban_chat_member(update.effective_chat.id, target.id)
    await update.message.reply_text(f"👢 {escape(target.full_name)} kicked\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    await ctx.bot.ban_chat_member(update.effective_chat.id, target.id)
    await update.message.reply_text(f"🚫 {escape(target.full_name)} banned\\.", parse_mode=ParseMode.MARKDOWN_V2)

# ── Auto-welcome ──────────────────────────────────────────────────────────────
warn_counts: dict[int, int] = {}

async def on_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.chat_member
    if not result:
        return
    old = result.old_chat_member.status
    new = result.new_chat_member.status
    user = result.new_chat_member.user
    if old in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) and new == ChatMemberStatus.MEMBER:
        slot = db_register_user(user.id, user.username or "", user.first_name or "")
        await ctx.bot.send_message(
            result.chat.id,
            msg_welcome(user.first_name or "friend", slot),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb_main(),
            disable_web_page_preview=True
        )

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ANTI_SPAM:
        return
    msg = update.message
    if not msg or not msg.text:
        return
    uid = msg.from_user.id if msg.from_user else None
    if is_admin(uid):
        return
    if msg.entities:
        for ent in msg.entities:
            if ent.type in {"url", "text_link"}:
                try:
                    await msg.delete()
                    warn_counts[uid] = warn_counts.get(uid, 0) + 1
                    count = warn_counts[uid]
                    await ctx.bot.send_message(msg.chat_id,
                        f"⚠️ @{msg.from_user.username or 'user'}: Links not allowed\\. Warning {count}/3\\.",
                        parse_mode=ParseMode.MARKDOWN_V2)
                    if count >= 3:
                        await ctx.bot.ban_chat_member(msg.chat_id, uid)
                        warn_counts.pop(uid, None)
                except Exception:
                    pass
                break

# ── App builder ───────────────────────────────────────────────────────────────
def build_app() -> Application:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    commands = [
        ("start", cmd_start), ("tge", cmd_tge), ("tgelaunch", cmd_tgelaunch),
        ("marketplace", cmd_marketplace), ("docs", cmd_docs), ("network", cmd_network),
        ("wallet", cmd_wallet), ("status", cmd_status), ("refer", cmd_refer),
        ("invest", cmd_invest), ("buy", cmd_buy), ("contract", cmd_contract),
        ("rules", cmd_rules), ("help", cmd_help),
        ("status_json", cmd_status_json), ("network_stats", cmd_network_stats),
        ("get_compute", cmd_get_compute),
        ("analytics", cmd_analytics), ("pin", cmd_pin), ("warn", cmd_warn),
        ("mute", cmd_mute), ("kick", cmd_kick), ("ban", cmd_ban),
    ]
    for name, handler in commands:
        app.add_handler(CommandHandler(name, handler))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("Set MYAI_COMMUNITY_BOT_TOKEN")
    logger.info("MyAI Community Bot v2.0 starting...")
    build_app().run_polling(drop_pending_updates=True, allowed_updates=["message", "chat_member", "callback_query"])
