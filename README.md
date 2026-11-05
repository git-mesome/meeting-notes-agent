# meeting-notes-agent

회의 녹음을 올리면 전사문과 회의록 초안을 만드는 도구다. 전사와 화자 구분은 노트북에서 WhisperX로 처리하고, 회의록은 전사문을 Claude API로 보내 작성한다.

## 준비

- [uv](https://docs.astral.sh/uv/)와 `ffmpeg`가 필요하다.
- Hugging Face에서 [`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1) 약관에 동의하고 Read 토큰을 만든다.
- 프로젝트 폴더의 `.env`에 아래 값을 넣는다. 이 파일은 커밋되지 않는다.

```
HF_TOKEN=Hugging Face 토큰
ANTHROPIC_API_KEY=Claude API 키
ACCESS_CODE=웹 화면 접속 코드
```

- 사내 용어를 한 줄에 하나씩 `glossary.txt`에 적으면 전사와 회의록 작성에 함께 쓴다. 이 파일도 커밋되지 않는다.

## 웹 화면

```bash
uv run --env-file .env uvicorn app:create_app --factory
```

http://127.0.0.1:8000 에 접속해 접속 코드를 입력한다. 녹음을 올리면 한 번에 한 건씩 처리하며, 결과는 `jobs/`에 저장한다. 회의록은 사람이 내용을 확인하고 수정한 뒤 확정한다.

### 핸드폰에서 접속

서버는 `127.0.0.1`에 그대로 두고 Tailscale이 같은 네트워크의 기기에만 중계하게 한다. 노트북과 핸드폰에 Tailscale을 설치해 같은 계정으로 로그인한 뒤, 노트북(Windows)에서 아래 명령을 한 번 실행한다.

```bash
tailscale serve --bg --http=80 http://127.0.0.1:8000
```

명령이 출력한 `http://<기기 이름>.<tailnet>.ts.net/` 주소를 핸드폰 브라우저로 연다. IP 주소로 접속하면 404가 난다. 중계를 끄려면 `tailscale serve --http=80 off`를 실행한다. 노트북이 꺼지거나 절전 상태이면 접속되지 않는다.

## 명령줄

```bash
uv run --env-file .env python meeting_notes.py recordings/회의.m4a --glossary glossary.txt
```

결과는 `outputs/<파일 이름>/`에 저장한다.

## 처리 시간

CPU(i7-1360P)에서 `large-v3`를 8스레드로 돌리면 음성 길이의 2.2~2.7배가 걸린다. 36분 녹음은 79분 걸렸다. 처리하는 동안 노트북이 켜져 있어야 한다.

## 테스트

```bash
uv run pytest
```
