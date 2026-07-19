"""
세종대 수강편람 챗봇 - 임베딩 + 벡터DB + 검색 + 답변 생성 파이프라인

임베딩 모델: solar-embedding-2-query / solar-embedding-2-passage
    - 1,024차원 (기존 solar-embedding-1-large 계열은 4,096차원 - 서로 호환 안 됨)
    - 8K 컨텍스트 지원
    - Rate limit: 100 RPM / 300,000 TPM (143개 청크 정도는 문제없이 처리됨)

사전 준비:
    pip install chromadb openai requests --break-system-packages
    프로젝트 루트에 secrets.json 파일을 두고, 안에 아래처럼 키를 저장:
        { "UPSTAGE_API_KEY": "발급받은키" }

사용법:
    python chatbot/pipeline.py                    # cache/chunks.jsonl 임베딩해서 벡터DB 구축
    python chatbot/pipeline.py ask "질문 내용"      # 구축된 벡터DB로 질문에 답변
"""

import os
import json
import sys
import requests
import chromadb
from openai import OpenAI

# 노트북(Jupyter/Colab)에서는 __file__이 없어서, 있으면 스크립트 기준 경로, 없으면 현재 작업 폴더 기준으로 찾음
try:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _BASE_DIR = os.getcwd()

_PROJECT_ROOT = os.path.dirname(_BASE_DIR)

CHUNKS_FILE = os.path.join(_PROJECT_ROOT, "cache", "chunks.jsonl")
DB_DIR = os.path.join(_PROJECT_ROOT, "cache", "chroma_db")
COLLECTION_NAME = "sugang_pyeollam"

SECRETS_FILE = os.path.join(_PROJECT_ROOT, "secrets.json")

EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"
CHAT_BASE_URL = "https://api.upstage.ai/v1"


def load_api_key(path=SECRETS_FILE):
    """API 키를 읽어온다. 우선순위: 1) 환경변수 UPSTAGE_API_KEY  2) secrets.json  3) 둘 다 없으면 오류.
    (Render 등 배포 환경에는 secrets.json이 없으므로 환경변수를 우선 사용한다.)
    secrets.json 안의 키 이름은 UPSTAGE_API_KEY / upstage_api_key / api_key 중 아무거나 지원."""
    env_key = os.getenv("UPSTAGE_API_KEY")
    if env_key:
        return env_key

    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            secrets = json.load(f)
        for key_name in ("UPSTAGE_API_KEY", "upstage_api_key", "api_key"):
            if key_name in secrets and secrets[key_name]:
                return secrets[key_name]

    raise RuntimeError(
        "UPSTAGE_API_KEY를 찾을 수 없습니다. 환경변수 UPSTAGE_API_KEY를 설정하거나, "
        f"로컬 개발용으로 {path}에 secrets.json 파일을 두어주세요."
    )


try:
    UPSTAGE_API_KEY = load_api_key()
except RuntimeError as e:
    # 앱 임포트(기동) 시점에는 죽지 않고, 실제로 키가 필요한 호출(search/generate_answer 등)
    # 시점에 명확한 에러를 내도록 미룬다 (Render 콜드스타트/헬스체크가 막히지 않게 하기 위함).
    print(f"[경고] {e}")
    UPSTAGE_API_KEY = None


def _require_api_key():
    if not UPSTAGE_API_KEY:
        raise RuntimeError(
            "UPSTAGE_API_KEY가 설정되지 않았습니다. Render 환경변수에 UPSTAGE_API_KEY를 추가해주세요."
        )


# ────────────────────────────────────────────────────────────────
# 1단계: 임베딩
# ────────────────────────────────────────────────────────────────

def embed_texts(texts, model="solar-embedding-2-passage"):
    """텍스트 리스트를 받아서 임베딩 벡터 리스트를 반환.
    Upstage 임베딩 API는 한 번에 여러 개(batch)를 받을 수 있음.
    solar-embedding-2 계열: 1024차원, 8K 컨텍스트 (기존 1-large 대비 더 김)."""
    _require_api_key()
    headers = {"Authorization": f"Bearer {UPSTAGE_API_KEY}"}
    body = {"input": texts, "model": model}
    resp = requests.post(EMBEDDING_URL, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()["data"]
    # data는 index 순서대로 오지만, 안전하게 index 기준 정렬
    data.sort(key=lambda x: x["index"])
    return [d["embedding"] for d in data]


def embed_query(text):
    """질문 하나를 임베딩 (query 전용 모델 사용 - passage 모델과 다름)."""
    return embed_texts([text], model="solar-embedding-2-query")[0]


# ────────────────────────────────────────────────────────────────
# 2단계: 벡터DB 구축
# ────────────────────────────────────────────────────────────────

def build_vector_db(chunks_path=CHUNKS_FILE, batch_size=20):
    _require_api_key()
    if not os.path.exists(chunks_path):
        raise RuntimeError(f"청크 파일을 찾을 수 없습니다: {chunks_path}")
    with open(chunks_path, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]

    print(f"총 {len(chunks)}개 청크 로드됨. 임베딩 시작...")

    client = chromadb.PersistentClient(path=DB_DIR)
    # 이미 있으면 지우고 새로 만듦 (재실행 시 중복 방지)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c["text"] for c in batch]
        vectors = embed_texts(texts)

        collection.add(
            ids=[c["chunk_id"] for c in batch],
            embeddings=vectors,
            documents=texts,
            metadatas=[
                {
                    "section_path": " > ".join(c["section_path"]),
                    "source_file": c.get("source_file", ""),
                    "char_count": c.get("char_count", len(c["text"])),
                }
                for c in batch
            ],
        )
        print(f"  {min(i + batch_size, len(chunks))}/{len(chunks)} 임베딩 완료")

    print(f"벡터DB 구축 완료 → {DB_DIR}")
    return collection


# ────────────────────────────────────────────────────────────────
# 3단계: 검색
# ────────────────────────────────────────────────────────────────

def search(question, top_k=15):
    if not os.path.exists(DB_DIR):
        raise RuntimeError(
            f"벡터DB를 찾을 수 없습니다: {DB_DIR}. "
            "cache/chroma_db 폴더가 배포에 포함되었는지, 또는 "
            "python chatbot/pipeline.py 로 먼저 벡터DB를 구축했는지 확인해주세요."
        )
    client = chromadb.PersistentClient(path=DB_DIR)
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception as e:
        raise RuntimeError(f"벡터DB 컬렉션을 열지 못했습니다: {e}") from e

    query_vector = embed_query(question)
    results = collection.query(query_embeddings=[query_vector], n_results=top_k)

    hits = []
    for doc, meta, dist, cid in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
        results["ids"][0],
    ):
        hits.append({
            "chunk_id": cid,
            "section_path": meta["section_path"],
            "text": doc,
            "distance": dist,
        })
    return hits


# ────────────────────────────────────────────────────────────────
# 4단계: 답변 생성 (Chat API)
# ────────────────────────────────────────────────────────────────

def generate_answer(question, hits):
    _require_api_key()
    context = "\n\n---\n\n".join(
        f"[출처: {h['section_path']}]\n{h['text']}" for h in hits
    )

    system_prompt = (
        "너는 세종대학교 수강편람 안내 챗봇이야. 아래 규칙을 전부 지켜서 답변해.\n\n"
        "1. [출처 제한] 아래 [문서 내용]에 있는 정보만 사용해서 답변해. "
        "문서에 없는 내용이면 절대 추측하지 말고 "
        "'수강편람에서 해당 정보를 찾을 수 없습니다. 학사정보시스템에서 직접 확인해주세요.'라고 답해.\n\n"
        "2. [표 읽기] 표(table) 형태의 문서를 참고할 때는 질문 대상과 정확히 일치하는 행(row)만 인용하고, "
        "다른 행에 적힌 조건·비고·설명을 섞어서 답하지 마. "
        "예를 들어 '3학년' 관련 질문이면 '3학년' 행에 적힌 내용만 답하고, "
        "'1학년'이나 '전학년' 행에 적힌 비고 사항을 3학년에게도 적용되는 것처럼 덧붙이지 마.\n\n"
        "3. [학번 변환] 사용자가 'OO학번'이라고 말하면, 이는 '20OO학년도 입학자'를 의미해. "
        "예: '22학번' = '2022학년도 입학자', '19학번' = '2019학년도 입학자'. "
        "문서에는 2019~2026학년도 입학자 정보만 있으니, 범위 밖 학번이면 '해당 학번 정보는 문서에 없다'고 답해.\n\n"
        "4. [연도 범위 비교] 문서에 '2017~2020학년도 입학자' 같은 특정 연도 범위 조건이 나오면, "
        "질문 대상의 연도가 그 범위 안에 실제로 포함되는지 숫자로 직접 비교해서 확인해. "
        "예를 들어 22학번(2022학년도)은 '2017~2020학년도' 범위에 포함되지 않으니, "
        "이 경우 해당 예외 조건이 적용되지 않는다고 답하고 기본 규정을 적용해. "
        "범위 안에 있는지 없는지 확신이 안 서면, 임의로 '해당된다'고 판단하지 말고 그 계산 과정을 답변에 보여줘.\n\n"
        "5. [불확실성 처리] 확신이 없는 추가 정보(다른 행/조건에서 유추한 내용 등)는 답변에 포함하지 말고, "
        "필요하면 '그 외 조건은 원문을 직접 확인하라'고만 안내해.\n\n"
        "6. [근거 표시] 답변 마지막에는 근거가 된 섹션(section_path)을 괄호로 표시해."
    )
    user_prompt = f"[문서 내용]\n{context}\n\n[질문]\n{question}"

    client = OpenAI(api_key=UPSTAGE_API_KEY, base_url=CHAT_BASE_URL)
    resp = client.chat.completions.create(
        model="solar-pro3",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        reasoning_effort="medium",  # 연도 범위 비교 같은 계산이 필요한 질문이라 reasoning 켜둠
        # (기본값은 "minimal"이라 사실상 추론 없이 바로 답을 생성함 -> 범위 비교 오류의 원인이었을 가능성 높음)
    )
    return resp.choices[0].message.content


# ────────────────────────────────────────────────────────────────
# 전체 파이프라인
# ────────────────────────────────────────────────────────────────

def ask(question, top_k=15, verbose=True):
    hits = search(question, top_k=top_k)
    if verbose:
        print("검색된 청크:")
        for h in hits:
            print(f"  - {h['chunk_id']} | {h['section_path']} (거리: {h['distance']:.4f})")
        print()
    answer = generate_answer(question, hits)
    return answer


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "ask":
        question = sys.argv[2]
        print(ask(question))
    else:
        build_vector_db()