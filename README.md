# Framework Made Simple (framework)

Type in one framework/thinking-model word (MECE, SWOT, OKR, PDCA, ...) and Claude turns
it into an English post that explains it the way you'd explain it to a smart
12-year-old — one clear everyday analogy, a hand-drawn-style diagram, and a real-world
example.

사이트: https://framework.metacog.co.kr/

## 어떻게 동작하나 (hook-only — 크론 없음)

```
input/term.md (프레임워크 용어를 한 줄에 하나씩, GitHub 웹 UI에서 수정)
        │
        ▼  저장(커밋)하는 순간 push 후킹으로 즉시 실행 (크론 없음 — 입력이 있을 때만 동작)
pipeline/generate.py
  - 코드블록의 각 줄을 용어 1개로 읽음
  - 이미 게시된 용어(해시 기준)는 건너뜀 — pipeline/state.json 으로 추적
  - 입력이 비어 있으면 아무것도 만들지 않고 조용히 종료 (폴백 없음)
  - Claude가 용어를 분석해 섹션 구성:
      🔍 What Is It? (쉬운 정의+설명) / 🧸 Think Of It Like This (일상 비유) /
      🖼️ Picture It (SVG 도식) / 🔀 How It Breaks Down (Mermaid, 해당 시) /
      🌍 Real World Example / 🎯 Try It Yourself
  - content/posts/YYYY-MM-DD-....md 로 저장
        │
        ▼  변경사항 커밋 & push
Hugo build → GitHub Pages 배포
```

## 사용하는 방법

1. GitHub 저장소에서 [`input/term.md`](input/term.md) 파일을 연다.
   (블로그 상단 "Add a Framework ✏️" 버튼으로 바로 이동 가능)
2. 연필(✏️) 아이콘을 눌러 편집 모드로 들어간다.
3. 코드블록(```) 안에 프레임워크 용어를 한 줄에 하나씩 적는다 (예: `MECE`, 다음 줄에
   `SWOT`). 줄마다 포스트가 하나씩 생성된다.
4. 우측 상단 "Commit changes"로 저장한다. **저장하는 순간 GitHub Actions가
   후킹되어 즉시 분석·게시가 시작된다** (로컬 git 작업 불필요, 크론 없음 — 이 입력
   없이는 아무 것도 게시되지 않는다).
5. 몇 분 뒤 사이트에 새 포스트가 올라온다.

게시가 전부 성공하면 파이프라인이 커밋 시 `input/term.md` 코드블록을 자동으로
비운다 — 다음 용어를 넣을 때 기존 내용을 지울 필요 없이 바로 적으면 된다. (일부만
실패하면 재시도할 수 있도록 입력은 그대로 남는다.) 혹시 자동 초기화 전에 같은
용어가 다시 남아 있어도, 텍스트 해시 기준 dedup으로 재게시되지 않는다. Actions 탭 →
"Framework Explainer Pipeline" → "Run workflow"로 수동 실행도 가능하다.

## 최초 설정 (1회만, 사람이 직접 해야 하는 단계)

자동 생성 단계는 Claude Code CLI를 사용한다. GitHub Actions에서 이 CLI를 인증하려면
Claude 구독 계정으로 발급한 OAuth 토큰을 저장소 Secret으로 등록해야 한다. 이 과정은
브라우저 로그인이 필요해 에이전트가 대신할 수 없다.

```bash
claude setup-token
```

터미널에 표시되는 인증 코드를 브라우저에 붙여넣고 로그인하면, **그 다음에** 터미널에
`sk-ant-oat01-...` 로 시작하는 토큰이 출력된다. (브라우저에 표시된 인증 코드 자체가
아니라, 붙여넣은 뒤 터미널에 최종 출력되는 토큰이어야 한다.)

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo jeonck/framework
# 위 토큰을 붙여넣기
```

등록 후 Actions 탭에서 워크플로를 한 번 수동 실행(`workflow_dispatch`)해 정상 동작을
확인한다.

## 저장소 구조

| 경로 | 역할 |
|---|---|
| `input/term.md` | 프레임워크 용어를 적는 곳 (사람이 수정 — 저장 즉시 후킹 실행) |
| `pipeline/generate.py` | 용어 분석 → Hugo 포스트 작성. 도메인 설정은 파일 상단 "도메인 설정" 블록 |
| `pipeline/state.json` | 게시에 사용된 용어 해시 목록 (중복 게시 방지) |
| `content/posts/` | 생성된 포스트 |
| `.github/workflows/daily.yml` | push 후킹 전용 생성/배포 워크플로 (크론 없음) |
| `themes/PaperMod` | Hugo 테마 (git submodule) |
| `layouts/_partials/extend_footer.html` | Mermaid.js 렌더링(포스트 내 ```mermaid``` 블록용) |
| `assets/css/extended/cards.css` | 카드 그리드 레이아웃 + PaperMod 여백 버그 수정 |
| `static/CNAME` | 커스텀 도메인 (https://framework.metacog.co.kr/) |

## 로컬에서 테스트

```bash
hugo server -D                           # http://localhost:1313/
python3 pipeline/generate.py --dry-run   # 파일 생성 없이 결과만 확인
```

로컬에는 `claude` CLI 로그인 세션이 있으면 그대로 사용되고(`JUDGE_BACKEND=claude-code`),
없으면 `ANTHROPIC_API_KEY` 를 설정해 `JUDGE_BACKEND=api` 로 실행할 수 있다.
