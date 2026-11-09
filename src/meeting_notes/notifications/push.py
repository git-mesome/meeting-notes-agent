"""처리가 끝나면 핸드폰으로 웹 푸시 알림을 보낸다.

알림 내용은 기기까지 암호화되지만, 잠금 화면에 보이므로 회의 제목이나 내용은 넣지 않는다.
"""

import base64
import json
import logging
import threading
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from meeting_notes.files import write_private

logger = logging.getLogger("meeting_notes.push")

# 푸시 서비스가 요구하는 발신자 연락처. 개인 메일 대신 쓰며, 라이브러리가 경로 없는 주소만 받는다.
VAPID_SUBJECT = "https://github.com"
GONE_STATUSES = {404, 410}


def default_send(subscription, payload, key_path):
    from pywebpush import webpush

    webpush(
        subscription_info=subscription,
        data=payload,
        vapid_private_key=str(key_path),
        vapid_claims={"sub": VAPID_SUBJECT},
        timeout=15,
    )


class PushCenter:
    def __init__(self, root, send=None):
        root = Path(root)
        self.key_path = root / "push-key.pem"
        self.subscriptions_path = root / "push-subscriptions.json"
        self.send = send or default_send
        self.lock = threading.Lock()

    def public_key(self):
        with self.lock:
            if not self.key_path.exists():
                key = ec.generate_private_key(ec.SECP256R1())
                pem = key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
                write_private(self.key_path, pem.decode())
            key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
        raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def _load(self):
        if not self.subscriptions_path.exists():
            return []
        return json.loads(self.subscriptions_path.read_text(encoding="utf-8"))

    def _save(self, subscriptions):
        write_private(self.subscriptions_path, json.dumps(subscriptions))

    def subscribe(self, subscription):
        with self.lock:
            subscriptions = [s for s in self._load() if s["endpoint"] != subscription["endpoint"]]
            subscriptions.append(subscription)
            self._save(subscriptions)

    def unsubscribe(self, endpoint):
        with self.lock:
            self._save([s for s in self._load() if s["endpoint"] != endpoint])

    def notify(self, title, body, url):
        """보내지 못해도 처리 결과에는 영향을 주지 않는다."""
        self.public_key()
        with self.lock:
            subscriptions = self._load()
        payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
        for subscription in subscriptions:
            try:
                self.send(subscription, payload, self.key_path)
            except Exception as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                if status in GONE_STATUSES:
                    self.unsubscribe(subscription["endpoint"])
                else:
                    logger.warning("푸시 알림을 보내지 못했다: %s %s", type(error).__name__, status)
