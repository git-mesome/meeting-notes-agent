"""회의 조회와 수정. 라우터는 요청을 받아 이 서비스를 부르기만 한다."""

import json
import logging
import os
import re
import shutil
import uuid

from meeting_notes.errors import AppError, Conflict, NotFound, Upstream
from meeting_notes.jobs.search import plain_text, search_pattern, snippet
from meeting_notes.jobs.store import ACTIVE_STATUSES, now
from meeting_notes.jobs.views import public_jobs
from meeting_notes.pipeline.audio import find_audio, probe_duration
from meeting_notes.pipeline.notes import notes_title
from meeting_notes.pipeline.spelling import fix_spelling
from meeting_notes.pipeline.templates import DEFAULT_TEMPLATE, TEMPLATES
from meeting_notes.pipeline.turns import format_transcript
from meeting_notes.speakers.embeddings import load_embeddings
from meeting_notes.speakers.names import FORBIDDEN_NAME_CHARS, SPEAKER_LABEL, apply_speaker_names, speaker_list

logger = logging.getLogger(__name__)

STILL_STOPPING_MESSAGE = "아직 멈추는 중이에요. 잠시 후 다시 시도해 주세요."


def require_template(template):
    if template not in TEMPLATES:
        raise AppError("없는 양식이에요.")


class JobService:
    def __init__(self, store, worker, voices, answer, issue_links=None):
        self.store = store
        self.worker = worker
        self.voices = voices
        self.answer = answer
        # 등록한 이슈에 트래커 주소를 붙인다(issues.service.link_issues).
        self.issue_links = issue_links or (lambda items: items)

    # 읽기

    def get(self, job_id):
        job = self.store.read(job_id)
        if job is None:
            raise NotFound("회의록을 찾을 수 없어요.")
        return job

    @staticmethod
    def require_done(job):
        if job["status"] != "done":
            raise Conflict("아직 회의록이 완성되지 않았어요.")

    def turns(self, job_id):
        return json.loads((self.store.path(job_id) / "turns.json").read_text(encoding="utf-8"))

    def notes(self, job_id):
        return (self.store.path(job_id) / "notes.md").read_text(encoding="utf-8")

    def questions(self, job_id):
        path = self.store.path(job_id) / "questions.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def speakers(self, job, turns=None):
        turns = self.turns(job["id"]) if turns is None else turns
        voiced = load_embeddings(self.store.path(job["id"]))
        return speaker_list(turns, job.get("speaker_names") or {}, job.get("auto_speakers"), voiced)

    def named_notes(self, job, speakers=None):
        """화자 라벨을 정한 이름으로 바꾼 회의록."""
        return apply_speaker_names(self.notes(job["id"]), speakers or self.speakers(job))

    def list(self):
        return public_jobs(self.store)

    def detail(self, job_id):
        self.get(job_id)
        view = next(view for view in public_jobs(self.store) if view["id"] == job_id)
        if view["status"] == "done":
            # 목록을 읽기 전에 읽은 상태를 쓰면, 그 사이에 끝난 작업의 화자 이름이 빠진다.
            job = self.get(job_id)
            job_dir = self.store.path(job_id)
            view["notes"] = self.notes(job_id)
            view["turns"] = self.turns(job_id)
            view["speakers"] = self.speakers(job, view["turns"])
            view["edited"] = (job_dir / "notes.draft.md").exists()
            view["template"] = job.get("template", DEFAULT_TEMPLATE)
            view["questions"] = self.questions(job_id)
            view["issues"] = self.issue_links(job.get("issues") or [])
        return view

    def audio_path(self, job_id):
        self.get(job_id)
        return find_audio(self.store.path(job_id))

    def download(self, job_id):
        """화자 이름을 넣은 회의록과 파일 이름에 쓸 제목을 돌려준다."""
        job = self.get(job_id)
        self.require_done(job)
        speakers = self.speakers(job)
        title = apply_speaker_names(job["title"] or job["name"], speakers)
        return re.sub(r'[\\/:*?"<>|\r\n]', "_", title)[:80], self.named_notes(job, speakers)

    def search(self, query):
        pattern = search_pattern(query[:100])
        if pattern is None:
            return []
        results = []
        for job in self.store.all():
            if job["status"] != "done":
                continue
            turns = self.turns(job["id"])
            speakers = self.speakers(job, turns)
            names = {speaker["label"]: speaker["name"] for speaker in speakers}
            title = apply_speaker_names(job.get("title") or job["name"], speakers)
            notes = plain_text(self.named_notes(job, speakers))
            hits = [
                {"start": turn["start"], "speaker": names.get(turn["speaker"], ""), "text": snippet(turn["text"], found)}
                for turn in turns
                if (found := pattern.search(turn["text"]))
            ]
            in_notes = pattern.search(notes)
            if not (hits or in_notes or pattern.search(title)):
                continue
            results.append(
                {
                    "id": job["id"],
                    "title": title,
                    "created_at": job["created_at"],
                    "duration_seconds": job["duration_seconds"],
                    "notes": snippet(notes, in_notes) if in_notes else None,
                    "hits": hits[:3],
                    "hit_count": len(hits),
                }
            )
        return results

    # 올리기

    def new_job_dir(self):
        job_id = uuid.uuid4().hex
        job_dir = self.store.path(job_id)
        job_dir.mkdir()
        return job_id, job_dir

    def add(self, job_id, name, suffix, incoming, template, owner):
        """올라온 파일이 오디오인지 확인하고 처리 대기열에 넣는다."""
        audio = incoming.with_name(f"audio{suffix}")
        os.replace(incoming, audio)
        duration = probe_duration(audio)
        self.store.write(
            {
                "id": job_id,
                "name": name,
                "title": None,
                "status": "queued",
                "created_at": now(),
                "duration_seconds": duration,
                "error": None,
                "confirmed_at": None,
                "template": template,
                "owner": owner,
            }
        )
        self.worker.queue.put(job_id)
        return next(view for view in public_jobs(self.store) if view["id"] == job_id)

    def discard(self, job_id):
        shutil.rmtree(self.store.path(job_id), ignore_errors=True)

    def requeue_interrupted(self):
        """처리 중에 서버가 꺼졌던 작업을 오래된 순서대로 다시 넣는다."""
        interrupted = [job for job in self.store.all() if job["status"] in ACTIVE_STATUSES]
        for job in sorted(interrupted, key=lambda job: job["created_at"]):
            self.store.update(job["id"], status="queued")
            self.worker.queue.put(job["id"])

    # 고치기

    def edit_notes(self, job_id, notes):
        job = self.get(job_id)
        self.require_done(job)
        notes = fix_spelling(notes)
        notes_path = self.store.path(job_id) / "notes.md"
        draft_path = self.store.path(job_id) / "notes.draft.md"
        if not draft_path.exists():
            shutil.copyfile(notes_path, draft_path)
        temp = notes_path.with_suffix(".tmp")
        temp.write_text(notes, encoding="utf-8")
        os.replace(temp, notes_path)
        self.store.update(job_id, title=notes_title(notes, job["name"]), confirmed_at=None)
        return self.detail(job_id)

    def rename_speaker(self, job_id, label, name, remember):
        job = self.get(job_id)
        self.require_done(job)
        if not SPEAKER_LABEL.fullmatch(label) or all(turn["speaker"] != label for turn in self.turns(job_id)):
            raise NotFound("화자를 찾을 수 없어요.")
        name = " ".join(name.split())
        if FORBIDDEN_NAME_CHARS.search(name):
            raise AppError("이름에 | * [ ] 기호는 쓸 수 없어요.")
        if remember and name:
            embedding = load_embeddings(self.store.path(job_id)).get(label)
            if embedding is None:
                raise Conflict("이 회의에는 목소리 정보가 없어요. 새로 올린 녹음부터 등록할 수 있어요.")
            self.voices.register(name, embedding)
        names = dict(job.get("speaker_names") or {})
        if name:
            names[label] = name
        else:
            names.pop(label, None)
        auto = {key: value for key, value in (job.get("auto_speakers") or {}).items() if key != label}
        self.store.update(job_id, speaker_names=names, auto_speakers=auto, confirmed_at=None)
        return self.detail(job_id)

    def ask(self, job_id, question):
        job = self.get(job_id)
        self.require_done(job)
        turns = self.turns(job_id)
        speakers = self.speakers(job, turns)
        transcript = apply_speaker_names(format_transcript(turns), speakers)
        question = question.strip()
        try:
            text = self.answer(transcript, self.named_notes(job, speakers), question)
        except Exception as error:
            logger.error("작업 %s 질문에 답하지 못했다", job_id, exc_info=error)
            raise Upstream("답을 받지 못했어요. 잠시 후 다시 시도해 주세요.") from error
        item = {"question": question, "answer": text, "asked_at": now()}
        questions = self.questions(job_id) + [item]
        (self.store.path(job_id) / "questions.json").write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
        return item

    def confirm(self, job_id):
        self.require_done(self.get(job_id))
        self.store.update(job_id, confirmed_at=now())
        return self.detail(job_id)

    # 처리 다시 하기, 멈추기, 지우기

    def regenerate(self, job_id, template):
        job = self.get(job_id)
        self.require_done(job)
        require_template(template)
        if self.worker.is_running(job_id):
            raise Conflict(STILL_STOPPING_MESSAGE)
        job_dir = self.store.path(job_id)
        shutil.copyfile(job_dir / "notes.md", job_dir / "notes.previous.md")
        (job_dir / "notes.draft.md").unlink(missing_ok=True)
        self.store.update(job_id, status="queued", template=template, confirmed_at=None, error=None)
        self.worker.queue.put(job_id)
        return self.detail(job_id)

    def retry(self, job_id):
        job = self.get(job_id)
        if job["status"] not in ("failed", "canceled"):
            raise Conflict("실패하거나 멈춘 작업만 다시 시작할 수 있어요.")
        if self.worker.is_running(job_id):
            raise Conflict(STILL_STOPPING_MESSAGE)
        self.store.update(job_id, status="queued", error=None)
        self.worker.queue.put(job_id)
        return self.detail(job_id)

    def cancel(self, job_id):
        job = self.get(job_id)
        if job["status"] not in ACTIVE_STATUSES:
            raise Conflict("처리 중인 작업만 멈출 수 있어요.")
        self.worker.cancel(job_id)
        return self.detail(job_id)

    def delete(self, job_id):
        job = self.get(job_id)
        if job["status"] in ACTIVE_STATUSES:
            raise Conflict("처리 중인 회의록은 먼저 멈춰 주세요.")
        if self.worker.is_running(job_id):
            raise Conflict(STILL_STOPPING_MESSAGE)
        shutil.rmtree(self.store.path(job_id))
