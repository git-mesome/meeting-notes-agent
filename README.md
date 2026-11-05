# meeting-notes-agent

회의 녹음을 올리면 전사문과 회의록 초안을 만드는 도구다. 전사와 화자 구분은 노트북에서 WhisperX로 처리하고, 회의록은 전사문을 Claude API로 보내 작성한다.

## 준비

- [uv](https://docs.astral.sh/uv/)와 `ffmpeg`가 필요하다.
- Hugging Face에서 [`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1) 약관에 동의하고 Read 토큰을 만든다.
- 프로젝트 폴더의 `.env`에 아래 값을 넣는다. 이 파일은 커밋되지 않는다.

```
HF_TOKEN=Hugging Face 토큰
ANTHROPIC_API_KEY=Claude API 키
```

- 사내 용어를 한 줄에 하나씩 `glossary.txt`에 적으면 전사와 회의록 작성에 함께 쓴다. 이 파일도 커밋되지 않는다.

## 웹 화면

```bash
uv run --env-file .env uvicorn app:create_app --factory
```

http://127.0.0.1:8000 에 접속한다. 녹음을 올리면 한 번에 한 건씩 처리하며, 결과는 `jobs/`에 저장한다. 회의록은 사람이 내용을 확인하고 수정한 뒤 확정한다. 화자는 말한 부분을 들어 보고 이름을 정할 수 있고, 이름은 내려받은 파일에도 적용된다. 처리 중인 항목은 중지할 수 있고, 항목을 삭제하면 녹음과 전사문, 회의록이 함께 지워진다.

### 핸드폰에서 접속

서버는 `127.0.0.1`에 그대로 두고 Tailscale이 같은 네트워크의 기기에만 중계하게 한다. 노트북과 핸드폰에 Tailscale을 설치해 같은 계정으로 로그인한 뒤, 노트북(Windows)에서 아래 명령을 한 번 실행한다.

```bash
tailscale serve --bg --http=80 http://127.0.0.1:8000
```

명령이 출력한 `http://<기기 이름>.<tailnet>.ts.net/` 주소를 핸드폰 브라우저로 연다. IP 주소로 접속하면 404가 난다. 중계를 끄려면 `tailscale serve --http=80 off`를 실행한다. 노트북이 꺼지거나 절전 상태이면 접속되지 않는다.

웹 화면에는 아직 로그인이 없다. 서버를 `0.0.0.0`으로 열거나 Tailscale Funnel로 공개하면 누구나 회의록을 보고 API 비용을 쓸 수 있으므로 그렇게 실행하지 않는다.

### 회의 양식과 질문

올릴 때 일반 회의, 주간 회의, 고객 미팅, 기술 검토 중에서 양식을 고른다. 완성한 뒤에도 더보기에서 다른 양식으로 다시 쓸 수 있다. 회의록 화면에서 회의 내용을 질문하면 근거 시각과 함께 답한다. 첫 화면에서 지난 회의의 회의록과 전사문을 검색한다.

### 완료 알림

처리가 끝나면 웹 푸시로 알린다. 브라우저 정책상 HTTPS가 필요하므로 Tailscale HTTPS를 켜고 아래 명령을 실행한다. 아이폰은 Safari에서 HTTPS 주소를 열고 홈 화면에 추가한 뒤, 추가한 앱에서 알림을 켠다. HTTPS 인증서를 발급하면 기기 이름이 공개 인증서 기록에 남는다.

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8000
```

### 화자 자동 인식

화자 이름을 정할 때 "다음 회의에서도 이 목소리 알아보기"를 켜면, 다음 회의부터 같은 사람에게 이름이 자동으로 붙는다. 목소리 특징은 생체 정보이므로 본인 동의를 받은 사람만 등록한다. `jobs/voices.json`에만 저장하고 외부로 보내지 않으며, "등록한 목소리 관리"에서 지운다. 기준값은 회의 하나로 정했으므로 다른 회의에서는 알아보지 못하거나 틀릴 수 있다.

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
