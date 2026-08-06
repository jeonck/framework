#!/usr/bin/env python3
"""Framework explainer pipeline — a framework word/term → a kid-simple study post.

input/term.md 코드블록에 한 줄에 하나씩 적은 프레임워크 용어(예: MECE, SWOT, OKR)를
읽어, Claude로 분석해 12살도 이해할 수 있는 영문 설명 포스트를 생성한다:
  - What Is It? (쉬운 말 한 줄 정의 + 2~3문단 설명, 비유를 녹여서 서술)
  - Think Of It Like This (하나의 구체적인 일상 비유 이야기)
  - Picture It (손으로 그린 듯한 단순 도식 SVG)
  - How It Breaks Down (구조를 보여주는 Mermaid 다이어그램, 해당될 때만)
  - Real World Example (실제 업무/생활 예시)
  - Try It Yourself (짧은 실천 질문)

한 줄 = 용어 하나. 이미 게시된 용어(텍스트 해시 기준)는 다시 나타나도 건너뛴다.
후킹 전용 모드 — 입력이 비어 있으면 아무것도 생성하지 않고 건너뛴다 (크론/폴백 없음).

Usage:
    python pipeline/generate.py [--dry-run]

Env:
    JUDGE_BACKEND            "claude-code" | "api" (기본: 자동 — claude CLI가 있으면
                             claude-code, 없으면 api)
    CLAUDE_CODE_OAUTH_TOKEN  claude-code 백엔드 CI 인증 (claude setup-token으로 발급,
                             로컬은 claude 로그인 세션 사용)
    ANTHROPIC_API_KEY        api 백엔드 필수
    CLAUDE_MODEL             생성 모델 (기본 claude-sonnet-4-6)
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERM_FILE = ROOT / "input" / "term.md"
STATE_FILE = ROOT / "pipeline" / "state.json"
CONTENT_DIR = ROOT / "content" / "posts"

KST = timezone(timedelta(hours=9))

# 포스트 1개는 SVG 도식 2개를 포함해 ~11KB를 생성하므로 실측 8~9분이 걸린다.
# 360초(기본값이던 값)로는 매번 타임아웃 → 재시도까지 12분 낭비 후 실패했다.
# CLI_TIMEOUT_SEC 환경변수로 조정 가능.
CLI_TIMEOUT = int(os.environ.get("CLI_TIMEOUT_SEC", "1200"))

# ============================== 도메인 설정 =================================
# 이 블록만 새 프로젝트 주제에 맞게 교체한다. 아래 엔진 코드는 건드릴 필요 없다.
#
# 후킹 전용 모드: 입력이 없는 날 대체 콘텐츠를 만들지 않는다 (크론도 없음 —
# .github/workflows/daily.yml 에 schedule 트리거가 없다). 빈 입력은 조용히 스킵한다.

# Claude에게 부여할 역할/톤
SYSTEM_PROMPT = """You are a friendly teacher who explains grown-up business, \
management, and thinking frameworks to curious 12-year-olds. You never use jargon \
without immediately explaining it in plain words, and every explanation is anchored \
in one clear, concrete everyday analogy (toys, school, sports, family life, pets, \
chores). Your tone is warm, encouraging, and simple — short sentences, no filler. \
All output is natural English."""

# {term} 자리를 반드시 유지. JSON 스키마의 이중 중괄호는 str.format() 이스케이프이므로
# 스키마를 고칠 때도 그대로 유지한다.
GENERATE_PROMPT = """The framework/term to explain is: "{term}"

Explain this framework so a smart 12-year-old fully understands what it is, why
grown-ups use it, and could explain it back in their own words. Respond ONLY with
JSON in exactly this format, no other text:

{{"title": "Short catchy English title naming the framework, e.g. 'MECE: Sorting Your Toys So Nothing Gets Left Out'",
 "one_liner": "one simple sentence a 12-year-old would say to define it",
 "explanation": "2-3 short paragraphs (plain English, short sentences) explaining what the framework is and why it's useful, weaving the analogy in naturally. Separate paragraphs with a single newline character.",
 "analogy_title": "short punchy name for the everyday analogy, e.g. 'The Toy Box Rule'",
 "analogy_story": "a concrete 4-6 sentence everyday story (toys/school/sports/family/chores) that maps every important part of the framework onto something a kid has actually experienced",
 "svg_diagram": "a complete, self-contained <svg>...</svg> string that draws a simple, clean, hand-drawn-style schematic of the framework using only <rect>, <circle>, <ellipse>, <line>, <path>, <text>, and <tspan> (no external images/fonts/scripts). viewBox=\\"0 0 600 320\\". Use a small friendly palette (e.g. #2563eb, #16a34a, #f59e0b, #ef4444, #64748b) with white/light fills and readable dark text labels (font-family sans-serif). Label every part in plain English so it teaches on its own.",
 "mermaid_diagram": "a short Mermaid diagram (flowchart TD, or graph TD, or mindmap) that shows the framework's structure or steps in 4-10 lines, using plain English labels in square brackets. Leave this as an empty string if a flow/tree diagram would not add anything beyond the svg_diagram.",
 "real_world_example": "2-4 sentences giving one concrete real-world example of this framework actually being used (business, school project, sports team, etc.), in plain English",
 "example_svg_diagram": "a second, complete, self-contained <svg>...</svg> string — same technical rules as svg_diagram — that diagrams THIS SPECIFIC real_world_example (its actual groups/steps/numbers), NOT the kid analogy again. This is a different picture from svg_diagram: it shows the grown-up example visually so a 12-year-old can map the analogy onto a real situation.",
 "try_it_yourself": ["3-4 bullets, each applying this framework to a DIFFERENT current/recent industry issue or trend (e.g. AI adoption, chip/supply-chain shortages, streaming or retail consolidation, remote-work policy, climate/EV transition, layoffs, data privacy regulation — pick whichever fit this framework best). Each bullet names the real situation and says concretely what applying this framework would mean there. Plain English, no jargon left unexplained."],
 "tags": ["kebab-case-tag", "max 3, first one should be the framework name itself in kebab-case"]}}

Requirements: never use the word "jargon" or say "in simple terms" — just BE simple.
Do not define the framework using other business jargon; if you must name a related
concept, explain that too in one plain clause. The analogy in analogy_story and the
svg_diagram should reinforce the SAME mental picture (don't introduce a second,
unrelated analogy in the diagram). example_svg_diagram must depict the
real_world_example instead — its own boxes/labels, not the analogy's toys/candy/etc.

try_it_yourself rules: these bullets are NOT about the reader's own school/hobby life
— every bullet must name a real, currently-relevant industry or business situation
(company, sector, or trend) and describe how this framework would actually be applied
there. Vary the industries across the 3-4 bullets (don't repeat the same sector as
real_world_example). Each bullet is 1-2 sentences, concrete, and still in plain,
jargon-free English a curious teenager could follow.

SVG rules (applies to both svg_diagram and example_svg_diagram): escape every double
quote inside the string as \\" and use \\n for line breaks so the result is valid JSON.
Keep each one strictly under 40 lines of markup, purely geometric/text (no raster
images, no <script>), and make sure text labels do not overlap shapes.
"""

# 포스트 본문 섹션 제목
HEADING_WHAT = "🔍 What Is It?"
HEADING_ANALOGY = "🧸 Think Of It Like This"
HEADING_PICTURE = "🖼️ Picture It"
HEADING_BREAKDOWN = "🔀 How It Breaks Down"
HEADING_EXAMPLE = "🌍 Real World Example"
HEADING_TRY = "🎯 Try It Yourself"

# ============================ 도메인 설정 끝 =================================


def log(msg: str) -> None:
    print(msg, flush=True)


def term_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return (slug or "framework")[:60].rstrip("-")


def read_terms() -> list[str]:
    """input/term.md 코드블록 안의 프레임워크 용어를 한 줄에 하나씩 읽는다."""
    if not TERM_FILE.exists():
        log(f"오류: {TERM_FILE} 파일이 없습니다")
        sys.exit(1)
    text = TERM_FILE.read_text(encoding="utf-8")
    fenced = re.search(r"```[a-zA-Z]*\n(.*?)```", text, re.DOTALL)
    body = fenced.group(1) if fenced else text
    terms = []
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("<!--") and not line.startswith("#"):
            terms.append(line)
    return terms


def build_queue(terms: list[str]) -> list[dict]:
    return [{"text": t, "dedup_key": term_hash(t)} for t in terms]


class FatalAPIError(Exception):
    """재시도가 무의미한 오류(크레딧 부족, 인증 실패) — 실행 전체 중단."""


def is_fatal_api_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in (
        "credit balance", "authenticat", "invalid x-api-key",
        "invalid api key", "invalid bearer token", "oauth token", "/login",
        "401",
    ))


def parse_result(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    required = ("title", "one_liner", "explanation", "analogy_title",
                "analogy_story", "svg_diagram", "real_world_example",
                "example_svg_diagram")
    if not all(isinstance(data.get(k), str) and data.get(k).strip() for k in required):
        return None
    if "<svg" not in data["svg_diagram"] or "<svg" not in data["example_svg_diagram"]:
        return None
    mermaid = data.get("mermaid_diagram") or ""
    data["mermaid_diagram"] = str(mermaid).strip()
    data["real_world_example"] = str(data["real_world_example"]).strip()
    try_it = data.get("try_it_yourself") or []
    if isinstance(try_it, str):  # 모델이 옛 형식(단일 문장)으로 답한 경우 한 항목으로 감쌈
        try_it = [try_it] if try_it.strip() else []
    data["try_it_yourself"] = [str(b).strip() for b in try_it if str(b).strip()]
    if not data["try_it_yourself"]:
        return None
    tags = data.get("tags") or []
    data["tags"] = [slugify(str(t)) for t in tags[:3] if str(t).strip()] or ["framework"]
    return data


def build_prompt(term: str) -> str:
    return GENERATE_PROMPT.format(term=term)


def generate_api(client, model: str, term: str) -> dict | None:
    prompt = build_prompt(term)
    for attempt in (1, 2):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            if is_fatal_api_error(exc):
                raise FatalAPIError(str(exc)) from exc
            log(f"  API 오류 (시도 {attempt}): {exc}")
            if attempt == 2:
                return None
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        result = parse_result(text)
        if result:
            return result
        log(f"  JSON 파싱 실패 (시도 {attempt}): {text[:120]!r}")
    return None


def generate_cli(model: str, term: str) -> dict | None:
    prompt = build_prompt(term)
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    cmd = ["claude", "-p", "--model", model, "--tools", "",
           "--output-format", "text", "--append-system-prompt", SYSTEM_PROMPT]
    for attempt in (1, 2):
        try:
            result = subprocess.run(cmd, input=prompt, env=env, timeout=CLI_TIMEOUT,
                                     capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            log(f"  CLI 타임아웃 {CLI_TIMEOUT}초 (시도 {attempt})")
            continue
        if result.returncode != 0:
            err = (result.stderr or result.stdout).strip()
            if is_fatal_api_error(RuntimeError(err)):
                raise FatalAPIError(err[:300])
            log(f"  CLI 오류 (시도 {attempt}): {err[:200]}")
            if attempt == 2:
                return None
            continue
        parsed = parse_result(result.stdout)
        if parsed:
            return parsed
        log(f"  JSON 파싱 실패 (시도 {attempt}): {result.stdout[:120]!r}")
    return None


def yaml_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_post(term: str, result: dict, date: datetime) -> Path:
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{date.date().isoformat()}-{slugify(term)}"
    path = CONTENT_DIR / f"{base}.md"
    n = 2
    while path.exists():
        path = CONTENT_DIR / f"{base}-{n}.md"
        n += 1

    tags_str = ", ".join(yaml_quote(t) for t in result["tags"])

    sections = [
        f"## {HEADING_WHAT}\n\n**{result['one_liner']}**\n\n{result['explanation']}\n",
        f"## {HEADING_ANALOGY}\n\n**{result['analogy_title']}**\n\n{result['analogy_story']}\n",
        f"## {HEADING_PICTURE}\n\n{result['svg_diagram']}\n",
    ]

    if result["mermaid_diagram"]:
        sections.append(f"## {HEADING_BREAKDOWN}\n\n```mermaid\n{result['mermaid_diagram']}\n```\n")

    if result["real_world_example"]:
        example = f"## {HEADING_EXAMPLE}\n\n{result['real_world_example']}\n"
        if result["example_svg_diagram"]:
            example += f"\n{result['example_svg_diagram']}\n"
        sections.append(example)

    if result["try_it_yourself"]:
        bullets = "\n".join(f"- {b}" for b in result["try_it_yourself"])
        sections.append(f"## {HEADING_TRY}\n\n{bullets}\n")

    post = f"""---
title: {yaml_quote(result['title'])}
date: {date.isoformat()}
tags: [{tags_str}]
---
""" + "\n".join(sections)
    path.write_text(post, encoding="utf-8")
    return path


def clear_input() -> None:
    """게시가 끝난 뒤 input/term.md 코드블록을 비운다 (안내 주석은 유지)."""
    text = TERM_FILE.read_text(encoding="utf-8")
    cleared = re.sub(r"```[a-zA-Z]*\n.*?```", "```\n```", text, count=1, flags=re.DOTALL)
    if cleared != text:
        TERM_FILE.write_text(cleared, encoding="utf-8")
        log("input/term.md 코드블록을 비웠습니다 (게시 완료)")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Framework explainer pipeline")
    parser.add_argument("--dry-run", action="store_true",
                         help="파일 생성/state.json 갱신 없이 결과만 출력")
    args = parser.parse_args()

    backend = os.environ.get("JUDGE_BACKEND", "").strip() or (
        "claude-code" if shutil.which("claude") else "api"
    )
    client = None
    if backend == "api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log("오류: api 백엔드에는 ANTHROPIC_API_KEY 환경변수가 필요합니다")
            return 1
        import anthropic  # 지연 임포트

        client = anthropic.Anthropic()
    elif backend == "claude-code":
        if not shutil.which("claude"):
            log("오류: claude-code 백엔드에는 claude CLI가 PATH에 있어야 합니다")
            return 1
    else:
        log(f"오류: 알 수 없는 JUDGE_BACKEND={backend!r} (claude-code | api)")
        return 1

    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    terms = read_terms()
    queue = build_queue(terms)
    if terms:
        log(f"입력된 프레임워크 용어 {len(terms)}개")
    else:
        log("input/term.md 에 용어가 없어 오늘은 건너뜁니다 (후킹 전용 모드 — 크론/폴백 없음)")
        return 0

    state = load_state()
    processed: dict = state.get("processed", {})

    log(f"=== 생성 시작 (backend={backend}, model={model}, dry_run={args.dry_run}) ===")

    new_count = 0
    skipped_dup = 0
    failed = 0
    fatal_error = None
    for item in queue:
        term, h = item["text"], item["dedup_key"]
        if h in processed:
            skipped_dup += 1
            continue

        log(f"\n오늘의 용어: {term}")
        try:
            if backend == "claude-code":
                result = generate_cli(model, term)
            else:
                result = generate_api(client, model, term)
        except FatalAPIError as exc:
            fatal_error = exc
            break

        if result is None:
            log("  생성 실패 — 건너뜁니다 (다음 실행에서 재시도)")
            failed += 1
            continue

        now = datetime.now(KST)
        log(f"  → {result['title']}")

        if args.dry_run:
            log(json.dumps(result, ensure_ascii=False, indent=2))
            continue

        path = write_post(term, result, now)
        log(f"  생성 파일: {path.relative_to(ROOT)}")
        processed[h] = now.date().isoformat()
        new_count += 1

    log(f"\n=== 결과: 신규 {new_count} / 중복 스킵 {skipped_dup} / 생성 실패 {failed} ===")

    if args.dry_run:
        log("(dry-run — 파일 생성/기록 갱신 없음)")
        return 1 if fatal_error else 0

    if new_count:
        state["processed"] = processed
        STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")

    # 전부 성공했을 때만 입력란 초기화 — 실패분이 있으면 다음 실행 재시도를 위해 남겨둔다
    if terms and new_count and not failed and fatal_error is None:
        clear_input()

    if fatal_error:
        log(f"\n중단: 복구 불가능한 API 오류 — {fatal_error}")
        log("→ Anthropic 크레딧/API 키(또는 CLAUDE_CODE_OAUTH_TOKEN)를 확인하세요.")
        log("→ 성공한 항목은 이미 게시/기록되었습니다.")
        return 1
    return 1 if failed and not new_count else 0


if __name__ == "__main__":
    sys.exit(main())
