"""Generate high-fidelity animated walkthrough GIF for Project Compass README & X."""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 900, 520
BG = (10, 14, 23)
PANEL_BG = (18, 24, 38)
CARD_BG = (255, 255, 255)
BORDER_COLOR = (40, 50, 70)
TEXT_WHITE = (255, 255, 255)
TEXT_MUTED = (148, 163, 184)
TEXT_DARK = (15, 23, 42)
ORANGE = (255, 85, 0)
YELLOW = (253, 224, 71)
GREEN = (34, 197, 94)
GREEN_BG = (220, 252, 231)
GREEN_TEXT = (21, 128, 61)
SHADOW = (0, 0, 0)

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
FONT_TITLE = ImageFont.truetype(FONT_PATH, 20)
FONT_SUB = ImageFont.truetype(FONT_PATH, 12)
FONT_CARD_TITLE = ImageFont.truetype(FONT_PATH, 15)
FONT_BODY = ImageFont.truetype(FONT_PATH, 13)
FONT_TAG = ImageFont.truetype(FONT_PATH, 11)
FONT_MONO = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 12)
FONT_MONO_BOLD = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 13)


def draw_rounded_rectangle(draw, bounds, radius=8, fill=None, outline=None, width=1):
    draw.rounded_rectangle(bounds, radius=int(radius), fill=fill, outline=outline, width=int(width))


def draw_header(draw, active_step):
    # Topbar
    draw.rectangle([0, 0, W, 48], fill=(14, 20, 32))
    draw.line([0, 48, W, 48], fill=(30, 41, 59), width=1)
    
    # Brand
    draw.rounded_rectangle([24, 10, 52, 38], radius=6, fill=ORANGE)
    draw.text((32, 13), "PC", fill=TEXT_WHITE, font=FONT_MONO_BOLD)
    draw.text((60, 11), "PROJECT COMPASS 2.0", fill=TEXT_WHITE, font=FONT_TITLE)
    draw.text((290, 16), "·  Human-Centered Evidence & Truth Board", fill=TEXT_MUTED, font=FONT_SUB)
    
    # Pulse
    draw.ellipse([W - 130, 20, W - 122, 28], fill=GREEN)
    draw.text((W - 115, 16), "Local-First Active", fill=TEXT_MUTED, font=FONT_SUB)

    # Step progress tabs
    steps = [
        "1. 提议 (Claim)",
        "2. AST 穿透",
        "3. 0.15s 取证",
        "4. 静默沙箱",
        "5. 团队真理"
    ]
    tab_w = (W - 48) // len(steps)
    for i, s in enumerate(steps):
        x1 = 24 + i * tab_w
        x2 = x1 + tab_w - 6
        is_curr = (i == active_step)
        is_done = (i < active_step)
        
        tab_fill = (30, 41, 59) if not is_curr else ORANGE
        txt_color = (255, 255, 255) if is_curr or is_done else TEXT_MUTED
        draw_rounded_rectangle(draw, [x1, 58, x2, 84], radius=4, fill=tab_fill)
        prefix = "✓ " if is_done else ""
        draw.text((x1 + 14, 63), prefix + s, fill=txt_color, font=FONT_TAG)


def render_frame(step, anim_sub=0):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_header(draw, step)

    # Main stage container
    stage_box = [24, 96, W - 24, H - 24]
    draw_rounded_rectangle(draw, stage_box, radius=10, fill=PANEL_BG, outline=BORDER_COLOR, width=1)

    # Scene 0: Propose Claim
    if step == 0:
        draw.text((44, 114), "STEP 01 / AGENT PROPOSES CANDIDATE CLAIM", fill=ORANGE, font=FONT_TAG)
        draw.text((44, 132), "Coding Agent 提交新任务完成提议（初始状态严格限制为 Proposed，隔离于团队事实之外）", fill=TEXT_WHITE, font=FONT_TITLE)

        # Card shadow & card
        cx, cy = 60, 185
        draw_rounded_rectangle(draw, [cx + 4, cy + 4, cx + 540 + 4, cy + 180 + 4], radius=8, fill=SHADOW)
        draw_rounded_rectangle(draw, [cx, cy, cx + 540, cy + 180], radius=8, fill=CARD_BG, outline=(0, 0, 0), width=2)

        draw.text((cx + 18, cy + 16), "TASK · PROPOSED", fill=ORANGE, font=FONT_TAG)
        draw.text((cx + 18, cy + 38), "实现 OAuth 2.0 PKCE 认证流程与多端 Token 安全流转", fill=TEXT_DARK, font=FONT_CARD_TITLE)
        draw.text((cx + 18, cy + 68), "Author: claude-agent-01  ·  Session: rollout-9b0f57  ·  Evidence: 2 items", fill=(100, 116, 139), font=FONT_SUB)

        # Evidence pill
        px, py = cx + 18, cy + 96
        draw_rounded_rectangle(draw, [px, py, px + 120, py + 26], radius=4, fill=(241, 245, 249), outline=(203, 213, 225))
        draw.text((px + 8, py + 5), "[ev-auth-pkce-01]", fill=TEXT_DARK, font=FONT_TAG)

        # Status badge
        bx = cx + 420
        draw_rounded_rectangle(draw, [bx, cy + 16, bx + 100, cy + 42], radius=4, fill=(254, 243, 199), outline=(245, 158, 11))
        draw.text((bx + 14, cy + 21), "待审核候选", fill=(180, 83, 9), font=FONT_TAG)

        # Aside note
        ax, ay = 640, 185
        draw_rounded_rectangle(draw, [ax, ay, ax + 210, ay + 180], radius=8, fill=(15, 23, 42), outline=BORDER_COLOR)
        draw.text((ax + 16, ay + 18), "🛡️ 事实不可篡改红线", fill=ORANGE, font=FONT_CARD_TITLE)
        draw.text((ax + 16, ay + 50), "• 任何 Agent 的产出\n  初始必为 Proposed\n• 严禁直接修改团队事实\n• 保留完整取证元数据", fill=TEXT_MUTED, font=FONT_SUB)

    # Scene 1: AST Topology Traversal
    elif step == 1:
        draw.text((44, 114), "STEP 02 / DEEP AST TOPOLOGY TRAVERSAL & CONTRACT RISK", fill=ORANGE, font=FONT_TAG)
        draw.text((44, 132), "确定性 AST 链式召回：跨模块 2-hop 调用链穿透与契约破坏预警", fill=TEXT_WHITE, font=FONT_TITLE)

        nodes = [
            ("oauth_handler()", 100, 220),
            ("verify_pkce_challenge()", 340, 220),
            ("token_store.save()", 580, 220)
        ]
        # Draw edges
        draw.line([250, 245, 340, 245], fill=ORANGE, width=3)
        draw.polygon([(335, 240), (345, 245), (335, 250)], fill=ORANGE)

        draw.line([540, 245, 580, 245], fill=ORANGE, width=3)
        draw.polygon([(575, 240), (585, 245), (575, 250)], fill=ORANGE)

        for name, nx, ny in nodes:
            draw_rounded_rectangle(draw, [nx + 3, ny + 3, nx + 170 + 3, ny + 56 + 3], radius=6, fill=SHADOW)
            draw_rounded_rectangle(draw, [nx, ny, nx + 170, ny + 56], radius=6, fill=(248, 250, 252), outline=(15, 23, 42), width=2)
            draw.text((nx + 14, ny + 10), "AST CALL NODE", fill=ORANGE, font=FONT_TAG)
            draw.text((nx + 14, ny + 28), name, fill=TEXT_DARK, font=FONT_MONO_BOLD)

        # Risk warning badge
        rx, ry = 100, 320
        draw_rounded_rectangle(draw, [rx, ry, rx + 650, ry + 60], radius=6, fill=(236, 253, 245), outline=GREEN, width=1.5)
        draw.text((rx + 20, ry + 12), "✓ 契约安全性通过 (Contract Safety Check):", fill=GREEN_TEXT, font=FONT_CARD_TITLE)
        draw.text((rx + 20, ry + 34), "下游 3 个调用点入参签名 100% 匹配 · 无破坏性签名变更 · AST 调用边去重校验通过", fill=TEXT_DARK, font=FONT_SUB)

    # Scene 2: 0.15s Proximity Prefetch & Quote Popover
    elif step == 2:
        draw.text((44, 114), "STEP 03 / 0.15s PROXIMITY PRE-FETCH & QUOTE POPOVER", fill=ORANGE, font=FONT_TAG)
        draw.text((44, 132), "鼠标光标接近 10px 触发后台预取，0.15s 零延迟浮现原文精准切片", fill=TEXT_WHITE, font=FONT_TITLE)

        cx, cy = 60, 185
        draw_rounded_rectangle(draw, [cx + 4, cy + 4, cx + 460 + 4, cy + 180 + 4], radius=8, fill=SHADOW)
        draw_rounded_rectangle(draw, [cx, cy, cx + 460, cy + 180], radius=8, fill=CARD_BG, outline=(0, 0, 0), width=2)

        draw.text((cx + 18, cy + 16), "TASK · [ev-auth-pkce-01]", fill=ORANGE, font=FONT_TAG)
        draw.text((cx + 18, cy + 40), "OAuth 2.0 PKCE 认证流程已实现", fill=TEXT_DARK, font=FONT_CARD_TITLE)

        # Active Radar Pill (Yellow!)
        px, py = cx + 18, cy + 86
        draw_rounded_rectangle(draw, [px + 2, py + 2, px + 140 + 2, py + 30 + 2], radius=4, fill=SHADOW)
        draw_rounded_rectangle(draw, [px, py, px + 140, py + 30], radius=4, fill=YELLOW, outline=(0, 0, 0), width=2)
        draw.text((px + 10, py + 7), "⚡ [ev-auth-pkce-01]", fill=(0, 0, 0), font=FONT_MONO_BOLD)

        # Simulated Cursor pointer
        cur_x, cur_y = px + 148, py + 32
        draw.polygon([(cur_x, cur_y), (cur_x + 12, cur_y + 16), (cur_x + 5, cur_y + 16), (cur_x + 8, cur_y + 24), (cur_x + 4, cur_y + 25), (cur_x + 1, cur_y + 17), (cur_x - 3, cur_y + 20)], fill=TEXT_WHITE, outline=(0, 0, 0))

        # Floating Popover
        pop_x, pop_y = 480, 160
        draw_rounded_rectangle(draw, [pop_x + 4, pop_y + 4, pop_x + 360 + 4, pop_y + 230 + 4], radius=10, fill=SHADOW)
        draw_rounded_rectangle(draw, [pop_x, pop_y, pop_x + 360, pop_y + 230], radius=10, fill=(255, 255, 255), outline=(0, 0, 0), width=2)

        # Popover header
        draw.text((pop_x + 16, pop_y + 14), "ORIGINAL CITATION (0.15s POPOVER)", fill=ORANGE, font=FONT_TAG)
        draw.text((pop_x + 16, pop_y + 32), "claude-agent-01 · 10:24 UTC", fill=TEXT_MUTED, font=FONT_SUB)

        # Quote Box (Yellow accent)
        draw_rounded_rectangle(draw, [pop_x + 16, pop_y + 56, pop_x + 344, pop_y + 166], radius=6, fill=(254, 249, 195), outline=(245, 158, 11), width=1)
        draw.rectangle([pop_x + 16, pop_y + 56, pop_x + 20, pop_y + 166], fill=ORANGE)
        quote_text = "“已完成与 IDP 的 PKCE 握手实现，\n包含 state 校验与 SHA-256 挑战码生成。\n全部 14 项认证测试集均返回 exit_code 0。”"
        draw.text((pop_x + 28, pop_y + 68), quote_text, fill=TEXT_DARK, font=FONT_BODY)

        draw.text((pop_x + 16, pop_y + 180), "Exact Span: source[142:256] · SHA-256 Verified", fill=TEXT_MUTED, font=FONT_TAG)

    # Scene 3: Silent Speculative Sandbox Worker
    elif step == 3:
        draw.text((44, 114), "STEP 04 / SILENT SPECULATIVE SANDBOX WORKER", fill=ORANGE, font=FONT_TAG)
        draw.text((44, 132), "后台独立沙箱静默执行单元测试，恪守绝对静默原则，100% 绿灯加盖验证印章", fill=TEXT_WHITE, font=FONT_TITLE)

        # Terminal Box (Left)
        tx, ty = 60, 185
        draw_rounded_rectangle(draw, [tx + 3, ty + 3, tx + 420 + 3, ty + 185 + 3], radius=6, fill=SHADOW)
        draw_rounded_rectangle(draw, [tx, ty, tx + 420, ty + 185], radius=6, fill=(15, 23, 42), outline=(30, 41, 59), width=2)
        draw.text((tx + 16, ty + 14), "SILENT SANDBOX RUNNER (ISOLATED SUBPROCESS)", fill=TEXT_MUTED, font=FONT_TAG)
        term_text = "$ python -m unittest tests.test_auth_pkce -q\n\n....................\n--------------------------------------\nRan 14 tests in 0.842s\n\nOK  (exit_code: 0, 100% green)"
        draw.text((tx + 16, ty + 40), term_text, fill=(74, 222, 128), font=FONT_MONO)

        # Verified Stamp Box (Right)
        sx, sy = 510, 185
        draw_rounded_rectangle(draw, [sx + 4, sy + 4, sx + 340 + 4, sy + 185 + 4], radius=8, fill=SHADOW)
        draw_rounded_rectangle(draw, [sx, sy, sx + 340, sy + 185], radius=8, fill=CARD_BG, outline=GREEN, width=2)
        draw.text((sx + 18, sy + 18), "投机验证结果判定 (SPECULATIVE VERIFIED)", fill=GREEN_TEXT, font=FONT_TAG)
        draw.text((sx + 18, sy + 44), "OAuth 2.0 PKCE 认证流程已实现", fill=TEXT_DARK, font=FONT_CARD_TITLE)

        # The Stamp (✦ 单测已验证)
        draw_rounded_rectangle(draw, [sx + 18, sy + 80, sx + 180, sy + 116], radius=6, fill=GREEN_BG, outline=GREEN, width=2)
        draw.text((sx + 26, sy + 88), "✦ 单测已验证 100%", fill=GREEN_TEXT, font=FONT_CARD_TITLE)

        draw.text((sx + 18, sy + 134), "• 遵循静默原则：测试未过绝不弹窗打扰人类\n• 测试全绿：前端加盖绿色真理微印章", fill=TEXT_MUTED, font=FONT_SUB)

    # Scene 4: Human-in-the-Loop Truth Promotion
    elif step == 4:
        draw.text((44, 114), "STEP 05 / HUMAN-IN-THE-LOOP · TRUTH PROMOTION", fill=ORANGE, font=FONT_TAG)
        draw.text((44, 132), "人类项目负责人一键采纳（一秒批红），正式晋升为全队不可篡改的权威真理", fill=TEXT_WHITE, font=FONT_TITLE)

        # Final Card
        fx, fy = 60, 180
        draw_rounded_rectangle(draw, [fx + 4, fy + 4, fx + 500 + 4, fy + 200 + 4], radius=8, fill=SHADOW)
        draw_rounded_rectangle(draw, [fx, fy, fx + 500, fy + 200], radius=8, fill=CARD_BG, outline=GREEN, width=2.5)

        draw.text((fx + 18, fy + 16), "TEAM TRUTH · ACCEPTED FACT", fill=GREEN_TEXT, font=FONT_TAG)
        draw.text((fx + 18, fy + 38), "OAuth 2.0 PKCE 认证流程与多端 Token 安全流转", fill=TEXT_DARK, font=FONT_CARD_TITLE)

        # Badges row
        bx = fx + 18
        draw_rounded_rectangle(draw, [bx, fy + 72, bx + 120, fy + 98], radius=4, fill=GREEN_BG, outline=GREEN)
        draw.text((bx + 10, fy + 76), "✦ 单测已验证", fill=GREEN_TEXT, font=FONT_TAG)

        bx2 = bx + 130
        draw_rounded_rectangle(draw, [bx2, fy + 72, bx2 + 130, fy + 98], radius=4, fill=(240, 253, 244), outline=(34, 197, 94))
        draw.text((bx2 + 10, fy + 76), "✓ 负责人已确认为真理", fill=(21, 128, 61), font=FONT_TAG)

        draw.text((fx + 18, fy + 118), "Confirmed by: project-owner  ·  Timestamp: 2026-11-09T15:00:00Z", fill=TEXT_MUTED, font=FONT_SUB)
        draw.text((fx + 18, fy + 142), "Evidence Hash: sha256:7b1e8a9f...  ·  Relations: 2 confirmed", fill=TEXT_MUTED, font=FONT_SUB)

        # Right Summary Box
        rx, ry = 580, 180
        draw_rounded_rectangle(draw, [rx, ry, rx + 270, ry + 200], radius=8, fill=(15, 23, 42), outline=BORDER_COLOR)
        draw.text((rx + 18, ry + 18), "🏛️ 团队权威共识确立", fill=ORANGE, font=FONT_CARD_TITLE)
        draw.text((rx + 18, ry + 50), "• 个人视图 ➔ 团队共识\n• 自动进入 MCP project_context\n• 其他 Agent 将以此为基准\n• 生成 PRD / PR 变更纪要", fill=TEXT_WHITE, font=FONT_BODY)

    return img


def generate_gif():
    frames = []
    # 5 steps, with hold durations
    for step in range(5):
        # generate 2-3 frames per step for smooth holding
        frame = render_frame(step)
        frames.extend([frame] * 6)  # 6 * 400ms = 2.4s per step

    out_path = "docs/images/compass_process_walkthrough.gif"
    os.makedirs("docs/images", exist_ok=True)
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=400,
        loop=0
    )
    print(f"Generated animated walkthrough GIF: {out_path} ({len(frames)} frames)")


if __name__ == "__main__":
    generate_gif()
