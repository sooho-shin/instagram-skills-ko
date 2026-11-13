# instagram-skills-ko

인스타그램 작업용 Claude Code 스킬 13개입니다. 한국어 글도 처리합니다(음절 수로 대본 길이 계산, 한국어 AI 티 단어 목록 등).

원본: [Jakeschincariol/instagram-agent-skill](https://github.com/Jakeschincariol/instagram-agent-skill) (MIT). 이 저장소는 원본을 바탕으로 한국어 지원을 더한 것입니다.

## 스킬

| 스킬 | 하는 일 |
|---|---|
| ig-reel | 릴스 훅·대본·자막·타이밍표 |
| ig-caption | 캡션 작성과 점검(더보기 전 첫 줄, 해시태그 수) |
| ig-carousel | 캐러셀 장별 문구와 1080x1350 파일 |
| ig-story | 하루치 스토리 구성과 스티커 |
| ig-plan | 한 주 게시 계획 |
| ig-profile | 프로필 100점 채점과 수정안 |
| ig-audit | 지난 게시물 성과 분석 |
| ig-viral | 분야별로 잘 되는 릴스 찾기 |
| ig-repurpose | 긴 영상·글을 릴스·캐러셀로 쪼개기 |
| ig-comment | 다른 계정 게시물에 달 댓글 |
| ig-reply | 내 게시물 댓글 답글 |
| ig-dm | DM 초안 |
| ig-human | AI 티 제거와 점수 |

## 설치

프로젝트에서만 쓰려면 프로젝트의 `.claude/skills/`에, 모든 프로젝트에서 쓰려면 `~/.claude/skills/`에 복사합니다.

```bash
git clone https://github.com/sooho-shin/instagram-skills-ko.git
cp -R instagram-skills-ko/skills/ig-* ~/.claude/skills/
```

파이썬 도구는 표준 라이브러리만 씁니다(python3 필요).
