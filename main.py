"""공직 채용정보(PblJobService) MCP 서버.

인사혁신처 공직 채용정보 조회 서비스(apis.data.go.kr)를 MCP 도구 3개로 노출한다.
- search_jobs: 채용공고 목록 검색 (getList)
- get_job_detail: 공고 상세 조회 (getItem)
- get_job_files: 공고 첨부파일 조회 (getItemFile)

인증키는 환경변수 PUBJOB_API_KEY에서 읽는다 (.env 파일 지원).
"""

import json
import os
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote, unquote

import httpx
import xmltodict
from dotenv import load_dotenv
from mcp.server import MCPServer

load_dotenv()

BASE_URL = "https://apis.data.go.kr/1760000/PblJobService"
TIMEOUT = 10.0

INSTT_SE = {
    "g01": "국가공무원",
    "g02": "지방공무원",
    "g03": "공공기관",
    "g04": "교육청",
}
PBLANC_TY = {
    "e01": "공개경쟁",
    "e02": "경력경쟁",
    "e03": "계약직",
    "e04": "행정지원",
    "e06": "공모직위",
}

mcp = MCPServer(
    "pubjob-mcp",
    instructions="대한민국 공직(국가·지방공무원, 공공기관, 교육청) 채용공고를 검색·조회하는 서버",
)


async def _call_api(path: str, params: dict[str, Any]) -> dict[str, Any] | str:
    """API를 호출해 응답 body(dict)를 반환한다. 실패 시 에러 메시지(str)를 반환한다."""
    key = os.environ.get("PUBJOB_API_KEY")
    if not key:
        return "오류: 환경변수 PUBJOB_API_KEY가 비어 있습니다. .env 파일에 인증키를 입력하세요."
    if "%" in key:  # Encoding 키가 들어온 경우 원본(Decoding)으로 되돌린다 (httpx가 다시 인코딩하므로)
        key = unquote(key)

    query: dict[str, Any] = {"serviceKey": key, "pageNo": "1", "numOfRows": "10"}
    query.update({k: v for k, v in params.items() if v not in (None, "")})

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{BASE_URL}/{path}", params=query)
            resp.raise_for_status()
    except httpx.TimeoutException:
        return "오류: API 응답이 10초를 초과했습니다. 잠시 후 다시 시도하세요."
    except httpx.HTTPError as e:
        return f"오류: API 요청 실패 - {e}"

    try:
        parsed = xmltodict.parse(resp.text)
    except Exception as e:
        return f"오류: XML 파싱 실패 - {e} / 응답 일부: {resp.text[:200]}"

    # data.go.kr 게이트웨이 공통 에러(인증키 오류 등)는 response가 아니라 이 형식으로 온다
    if "OpenAPI_ServiceResponse" in parsed:
        hdr = (parsed["OpenAPI_ServiceResponse"] or {}).get("cmmMsgHeader") or {}
        reason = hdr.get("returnAuthMsg") or hdr.get("errMsg") or "설명 없음"
        return f"오류: API 게이트웨이 에러 (returnReasonCode={hdr.get('returnReasonCode')}, {reason})"

    response = parsed.get("response") or {}
    header = response.get("header") or {}
    code = header.get("resultCode")
    if code != "00":
        return f"오류: API 실패 응답 (resultCode={code}, resultMsg={header.get('resultMsg', '설명 없음')})"
    return response.get("body") or {}


def _extract_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """body에서 item을 꺼내 1건(dict)이든 여러 건(list)이든 list로 통일한다."""
    items = body.get("items")
    if isinstance(items, dict) and "item" in items:
        items = items["item"]
    if items is None:
        items = body.get("item")
    if items is None:
        return []
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict)]
    if isinstance(items, dict):
        return [items]
    return []


def _fmt_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


@mcp.tool()
async def search_jobs(
    keyword: str | None = None,
    instt_se: str | None = None,
    instt_nm: str | None = None,
    pblanc_ty: str | None = None,
    begin_de: str | None = None,
    end_de: str | None = None,
    num_rows: int = 10,
) -> str:
    """공직 채용공고를 검색한다. 모든 인자는 선택적이며 항상 최신 등록순으로 반환한다.

    Args:
        keyword: 제목 검색 키워드 (예: "전산", "간호")
        instt_se: 기관 구분 코드 — g01=국가공무원, g02=지방공무원, g03=공공기관, g04=교육청
        instt_nm: 기관명 (예: "서울특별시", "국세청")
        pblanc_ty: 공고 유형 코드 — e01=공개경쟁, e02=경력경쟁, e03=계약직, e04=행정지원, e06=공모직위
        begin_de: 조회 시작일 YYYYMMDD (미지정 시 오늘-30일)
        end_de: 조회 종료일 YYYYMMDD (미지정 시 오늘)
        num_rows: 최대 결과 수 (기본 10)
    """
    today = date.today()
    begin_de = begin_de or (today - timedelta(days=30)).strftime("%Y%m%d")
    end_de = end_de or today.strftime("%Y%m%d")

    body = await _call_api(
        "getList",
        {
            "Kwrd": keyword,
            "Instt_se": instt_se,
            "Instt_nm": instt_nm,
            "Pblanc_ty": pblanc_ty,
            "Begin_de": begin_de,
            "End_de": end_de,
            "Sort_order": "DESC",  # 항상 내림차순(최신순) 고정
            "numOfRows": str(max(1, num_rows)),
        },
    )
    if isinstance(body, str):
        return body

    conditions = [f"기간: {begin_de}~{end_de}"]
    if keyword:
        conditions.append(f"키워드: {keyword}")
    if instt_se:
        conditions.append(f"기관구분: {INSTT_SE.get(instt_se, instt_se)}({instt_se})")
    if instt_nm:
        conditions.append(f"기관명: {instt_nm}")
    if pblanc_ty:
        conditions.append(f"공고유형: {PBLANC_TY.get(pblanc_ty, pblanc_ty)}({pblanc_ty})")
    cond_text = " / ".join(conditions)

    items = _extract_items(body)
    if not items:
        return f"검색 결과 없음\n[검색 조건] {cond_text}"

    total = body.get("totalCount")
    lines = [f"[검색 조건] {cond_text}"]
    if total is not None:
        lines.append(f"전체 {total}건 중 {len(items)}건 표시")
    for it in items:
        lines.append(
            f"- [{_fmt_value(it.get('idx'))}] {_fmt_value(it.get('title'))}\n"
            f"  기관: {_fmt_value(it.get('insttname'))} | "
            f"등록일: {_fmt_value(it.get('regdate'))} | "
            f"마감일: {_fmt_value(it.get('enddate'))}"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_job_detail(idx: str) -> str:
    """채용공고 1건의 상세 정보를 조회한다.

    Args:
        idx: 공고 식별 번호 (search_jobs 결과의 [idx] 값)
    """
    body = await _call_api("getItem", {"idx": idx})
    if isinstance(body, str):
        return body

    items = _extract_items(body)
    if not items:
        return f"공고를 찾을 수 없습니다 (idx={idx})"

    lines = [f"[공고 상세] idx={idx}"]
    for item in items:
        for key, value in item.items():
            lines.append(f"{key}: {_fmt_value(value)}")
    return "\n".join(lines)


@mcp.tool()
async def get_job_files(idx: str) -> str:
    """채용공고의 첨부파일 목록(파일명·다운로드 정보)을 조회한다.

    Args:
        idx: 공고 식별 번호 (search_jobs 결과의 [idx] 값)
    """
    body = await _call_api("getItemFile", {"idx": idx})
    if isinstance(body, str):
        return body

    items = _extract_items(body)
    if not items:
        return f"첨부파일 없음 (idx={idx})"

    lines = [f"[첨부파일] idx={idx} / {len(items)}건"]
    for i, item in enumerate(items, 1):
        lines.append(f"({i})")
        for key, value in item.items():
            lines.append(f"  {key}: {_fmt_value(value)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 잡알리오 (공공기관 채용공시, opendata.alio.go.kr)
# ---------------------------------------------------------------------------

ALIO_BASE_URL = "https://opendata.alio.go.kr"

ALIO_ERROR_CODES = {
    "3": "데이터 없음",
    "7": "게이트웨이 인증 실패",
    "8": "활용신청 승인 확인 실패",
}

ALIO_FILE_TYPES = {"A": "공고문", "B": "입사지원서", "C": "직무기술서"}


async def _call_alio(path: str, params: dict[str, Any]) -> dict[str, Any] | str:
    """잡알리오 API 호출. 정상 시 응답 JSON(dict), 실패 시 에러 메시지(str) 반환.

    명세상 POST이지만 파라미터는 전부 query string으로 보낸다.
    POST가 실패하면 GET으로 재시도한다.
    """
    key = os.environ.get("ALIO_API_KEY")
    if not key:
        return "오류: 환경변수 ALIO_API_KEY가 비어 있습니다. .env 파일에 인증키를 입력하세요."
    if "%" in key:  # Encoding 키가 들어온 경우 원본(Decoding)으로 되돌린다
        key = unquote(key)

    query: dict[str, Any] = {"serviceKey": key}
    query.update({k: v for k, v in params.items() if v not in (None, "")})

    url = f"{ALIO_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                resp = await client.post(url, params=query)
                resp.raise_for_status()
            except httpx.HTTPError:
                resp = await client.get(url, params=query)  # POST 실패 시 GET 재시도
                resp.raise_for_status()
    except httpx.TimeoutException:
        return "오류: 잡알리오 API 응답이 10초를 초과했습니다. 잠시 후 다시 시도하세요."
    except httpx.HTTPError as e:
        return f"오류: 잡알리오 API 요청 실패 - {e}"

    try:
        data = resp.json()
    except Exception as e:
        return f"오류: JSON 파싱 실패 - {e} / 응답 일부: {resp.text[:200]}"

    code = str(data.get("resultCode"))
    if code not in ("0", "200"):  # 명세는 0이지만 실제 서버는 성공 시 200을 반환한다
        name = ALIO_ERROR_CODES.get(code, "")
        name_part = f" {name}," if name else ""
        return (
            f"오류: 잡알리오 API 실패 응답 (resultCode={code},{name_part} "
            f"resultMsg={data.get('resultMsg', '설명 없음')})"
        )
    return data


def _alio_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """응답에서 결과 목록을 꺼내 dict 1건이든 list든 list로 통일한다."""
    result = data.get("result")
    if result is None:
        result = data.get("items")
    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    return []


@mcp.tool()
async def search_alio_jobs(
    keyword: str | None = None,
    ongoing_only: bool = True,
    hire_type: str | None = None,
    ncs_code: str | None = None,
    recrut_se: str | None = None,
    inst_type: str | None = None,
    inst_clsf: str | None = None,
    region: str | None = None,
    begin_date: str | None = None,
    end_date: str | None = None,
    num_rows: int = 20,
    page_no: int = 1,
) -> str:
    """잡알리오에서 공공기관 채용공시를 검색한다. 모든 인자는 선택적.

    Args:
        keyword: 공고 제목 포함검색 키워드 (서버측 검색)
        ongoing_only: True(기본)면 접수 진행 중인 공고만
        hire_type: 고용형태 코드(쉼표로 복수 지정) — R1010=정규직, R1020=계약직,
            R1030=무기계약직, R1040=비정규직, R1050=청년인턴,
            R1060=청년인턴(체험형), R1070=청년인턴(채용형)
        ncs_code: NCS 직무분야 코드(쉼표로 복수 지정) — R600001=사업관리,
            R600002=경영회계사무, R600004=교육자연사회과학, R600006=보건의료,
            R600007=사회복지종교, R600020=정보통신, R600025=연구
        recrut_se: 채용구분 코드 — R2010=신입, R2020=경력, R2030=신입+경력,
            R2040=외국인전형
        inst_type: 기관유형 코드 — A2001=공기업(시장형), A2002=공기업(준시장형),
            A2003=준정부(기금관리), A2004=준정부(위탁집행), A2005=기타공공기관
        inst_clsf: 기관분류 코드 — 04=고용보건복지, 08=연구교육
        region: 근무지역 코드(쉼표로 복수 지정) — R3010=서울, R3017=경기, R3026=세종 등
        begin_date: 공고 시작일 YYYY-MM-DD
        end_date: 공고 종료일 YYYY-MM-DD
        num_rows: 페이지당 결과 수 (기본 20)
        page_no: 페이지 번호 (기본 1)
    """
    data = await _call_alio(
        "/new/v1/recruit/list.do",
        {
            # 잡알리오 서버가 쿼리를 두 번 디코딩하므로 한글 키워드는 미리 한 번 인코딩한다
            # (미리 안 하면 resultCode=6 서버 에러. ASCII 키워드는 인코딩해도 동일)
            "recrutPbancTtl": quote(keyword) if keyword else None,
            "ongoingYn": "Y" if ongoing_only else None,
            "hireTypeLst": hire_type,
            "ncsCdLst": ncs_code,
            "recrutSe": recrut_se,
            "instType": inst_type,
            "instClsf": inst_clsf,
            "workRgnLst": region,
            "pbancBgngYmd": begin_date,
            "pbancEndYmd": end_date,
            "numOfRows": str(max(1, num_rows)),
            "pageNo": str(max(1, page_no)),
        },
    )
    if isinstance(data, str):
        return data

    conditions = []
    if keyword:
        conditions.append(f"키워드: {keyword}")
    if ongoing_only:
        conditions.append("진행 중인 공고만")
    if hire_type:
        conditions.append(f"고용형태: {hire_type}")
    if ncs_code:
        conditions.append(f"NCS: {ncs_code}")
    if recrut_se:
        conditions.append(f"채용구분: {recrut_se}")
    if inst_type:
        conditions.append(f"기관유형: {inst_type}")
    if inst_clsf:
        conditions.append(f"기관분류: {inst_clsf}")
    if region:
        conditions.append(f"지역: {region}")
    if begin_date or end_date:
        conditions.append(f"기간: {begin_date or ''}~{end_date or ''}")
    cond_text = " / ".join(conditions) if conditions else "조건 없음"

    items = _alio_items(data)
    if not items:
        return f"검색 결과 없음\n[검색 조건] {cond_text}"

    total = data.get("totalCount")
    lines = [f"[검색 조건] {cond_text}"]
    if total is not None:
        lines.append(f"전체 {total}건 중 {len(items)}건 표시 (페이지 {page_no})")
    for it in items:
        lines.append(
            f"- [{_fmt_value(it.get('recrutPblntSn'))}] {_fmt_value(it.get('recrutPbancTtl'))}\n"
            f"  기관: {_fmt_value(it.get('instNm'))} | "
            f"고용형태: {_fmt_value(it.get('hireTypeNmLst'))} | "
            f"채용구분: {_fmt_value(it.get('recrutSeNm'))}\n"
            f"  공고기간: {_fmt_value(it.get('pbancBgngYmd'))}~{_fmt_value(it.get('pbancEndYmd'))} | "
            f"지역: {_fmt_value(it.get('workRgnNmLst'))} | "
            f"NCS: {_fmt_value(it.get('ncsCdNmLst'))}"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_alio_job_detail(sn: int) -> str:
    """잡알리오 채용공시 1건의 상세 정보(자격요건·우대·전형절차·첨부파일 등)를 조회한다.

    Args:
        sn: 공고 일련번호 (search_alio_jobs 결과의 [sn] 값, recrutPblntSn)
    """
    data = await _call_alio("/new/v1/recruit/detail.do", {"sn": sn})
    if isinstance(data, str):
        return data

    items = _alio_items(data)
    if not items:
        return f"공고를 찾을 수 없습니다 (sn={sn})"
    item = items[0]

    lines = [f"[공고 상세] sn={sn}"]
    lines.append(f"제목: {_fmt_value(item.get('recrutPbancTtl'))}")
    lines.append(f"기관: {_fmt_value(item.get('instNm'))}")
    lines.append(
        f"공고기간: {_fmt_value(item.get('pbancBgngYmd'))}~{_fmt_value(item.get('pbancEndYmd'))}"
    )
    for label, field in [
        ("고용형태", "hireTypeNmLst"),
        ("채용구분", "recrutSeNm"),
        ("근무지역", "workRgnNmLst"),
        ("NCS", "ncsCdNmLst"),
    ]:
        if item.get(field) is not None:
            lines.append(f"{label}: {_fmt_value(item.get(field))}")

    for label, field in [
        ("자격요건", "aplyQlfcCn"),
        ("우대사항", "prefCn"),
        ("우대조건", "prefCondCn"),
        ("결격사유", "disqlfcRsn"),
        ("전형절차", "scrnprcdrMthdExpln"),
    ]:
        value = item.get(field)
        if value not in (None, ""):
            lines.append(f"--- {label} ---")
            lines.append(_fmt_value(value))

    steps = item.get("steps")
    if isinstance(steps, dict):
        steps = [steps]
    if isinstance(steps, list) and steps:
        lines.append("--- 전형단계 ---")
        for i, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                continue
            parts = []
            for k, v in step.items():
                if k == "aplyNope":
                    parts.append(f"지원인원: {_fmt_value(v)}")
                elif k == "cmpttRt":
                    parts.append(f"경쟁률: {_fmt_value(v)}")
                else:
                    parts.append(f"{k}: {_fmt_value(v)}")
            lines.append(f"({i}) " + " | ".join(parts))

    files = item.get("files")
    if isinstance(files, dict):
        files = [files]
    if isinstance(files, list) and files:
        lines.append("--- 첨부파일 ---")
        for f in files:
            if not isinstance(f, dict):
                continue
            ftype = ALIO_FILE_TYPES.get(str(f.get("atchFileType")), _fmt_value(f.get("atchFileType")))
            lines.append(f"- [{ftype}] {_fmt_value(f.get('atchFileNm'))} | {_fmt_value(f.get('url'))}")

    if item.get("srcUrl"):
        lines.append(f"원문링크: {item['srcUrl']}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()  # stdio
