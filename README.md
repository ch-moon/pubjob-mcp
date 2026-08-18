# pubjob-mcp

나라일터(인사혁신처) + 잡알리오(공공기관 채용공시) **이중 소스** 공공채용 검색 MCP 서버.

Claude 등 MCP 클라이언트에서 국가·지방공무원, 공공기관, 교육청 채용공고를 검색하고
자격요건·전형절차·첨부파일까지 조회할 수 있다.

## 도구

| 도구 | 데이터 소스 | 기능 |
|---|---|---|
| `search_jobs` | 나라일터 | 채용공고 검색 (기관구분·기관명·공고유형·기간 필터, 최신순) |
| `get_job_detail` | 나라일터 | 공고 상세 조회 (본문·접수기간·링크 등 전체 필드) |
| `get_job_files` | 나라일터 | 공고 첨부파일 목록·다운로드 정보 |
| `search_alio_jobs` | 잡알리오 | 채용공시 검색 (제목 키워드·고용형태·NCS 직무·채용구분·기관유형·지역 필터, 진행 중 공고 필터) |
| `get_alio_job_detail` | 잡알리오 | 공시 상세 조회 (자격요건·우대·결격·전형절차·단계별 경쟁률·첨부파일·원문링크) |

기관구분·고용형태·NCS 등 검색 코드표는 각 도구의 docstring에 포함되어 있어
MCP 클라이언트(LLM)가 바로 활용할 수 있다.

## 설치

```bash
git clone https://github.com/ch-moon/pubjob-mcp.git
cd pubjob-mcp
uv sync
```

### API 키 설정

`.env` 파일을 만들고 인증키 2개를 넣는다 (Encoding/Decoding 키 아무거나 — 자동 판별):

```dotenv
PUBJOB_API_KEY=나라일터_인증키
ALIO_API_KEY=잡알리오_인증키
```

| 키 | 발급처 |
|---|---|
| `PUBJOB_API_KEY` | [공공데이터포털(data.go.kr)](https://www.data.go.kr)에서 **"인사혁신처 공직 채용정보"** 검색 → 활용신청 |
| `ALIO_API_KEY` | [잡알리오(job.alio.go.kr)](https://job.alio.go.kr) OpenAPI 메뉴에서 인증키 신청 |

### 동작 확인

```bash
uv run mcp dev main.py   # MCP Inspector로 테스트
```

## MCP 클라이언트 등록

### Claude Desktop

`%APPDATA%\Claude\claude_desktop_config.json` (Windows) 의 `mcpServers`에 추가:

```json
{
  "mcpServers": {
    "pubjob": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\Users\\<사용자>\\pubjob-mcp", "python", "main.py"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add pubjob -- uv run --directory /path/to/pubjob-mcp python main.py
```

> Windows PowerShell 5.1은 `--` 구분자를 삼켜버리므로 cmd나 Git Bash에서 실행할 것.

## Known API quirks

공식 명세와 실서버 동작이 다른 지점들. 이 저장소의 코드는 전부 실호출로 검증하며 대응해두었다.

### 잡알리오 (opendata.alio.go.kr)

1. **한글 파라미터는 이중 인코딩 필요** — 서버가 query string을 **두 번 디코딩**한다.
   한글 키워드를 일반적인 percent-encoding 한 번으로 보내면 `resultCode=6 (서버 에러)`.
   미리 한 번 인코딩한 값을 보내야(전송 시점엔 이중 인코딩 상태) 정상 검색된다.
   ASCII 키워드는 두 방식이 동일해서 이 버그가 드러나지 않는다.
2. **성공 resultCode가 명세(0)와 달리 200** — 실서버는 성공 시
   `resultCode=200, resultMsg=성공했습니다.`를 반환한다. 본 코드는 0/200을 모두 성공으로 처리.
3. **GET 미지원** — 명세상 파라미터는 전부 query string이지만 메서드는 POST만 받는다.
   GET으로 보내면 HTTP 405 (`Request method 'GET' not supported`) HTML 페이지가 돌아온다.

### 나라일터 (apis.data.go.kr/1760000/PblJobService)

4. **Encoding 인증키를 그대로 쓰면 403** — HTTP 클라이언트가 `serviceKey`를 다시
   인코딩해 이중 인코딩이 되기 때문. 본 코드는 키에 `%`가 있으면 자동으로 디코딩 후 전송한다
   (Encoding/Decoding 키 어느 쪽을 넣어도 동작).
5. **`Kwrd` 키워드 파라미터가 서버에서 무시됨** — 어떤 키워드를 보내도 totalCount가
   동일하게 반환된다. 키워드 검색이 필요하면 전체 목록을 받아 로컬 필터링할 것.

## 기술 스택

- Python 3.13 / [uv](https://docs.astral.sh/uv/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 2.0 (`MCPServer`, stdio)
- httpx (비동기, 10초 타임아웃) / xmltodict (나라일터 XML 파싱)
- 모든 오류는 예외 대신 `resultMsg`를 포함한 안내 메시지로 반환 — LLM이 스스로 재시도·조정 가능
